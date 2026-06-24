"""JWT authentication and role-based access control for the Data Quality Platform.

Provides:
- JWT token validation against Cognito (signature, expiration, issuer)
- Role extraction from cognito:groups
- Role-based access control decorators
- RBAC permission matrix

Roles:
- AdminDatos: Full CRUD access to all platform resources
- AnalistaDatos: Read access + trigger operations (validation, scoring, cleaning, reports)

Uses python-jose for JWT verification and fetches JWKS from Cognito.

Requirements: 1.3, 2.1, 2.2, 2.3, 2.6
"""

from __future__ import annotations

import functools
import json
import logging
import os
import time
from typing import Any, Callable, Optional

import requests
from jose import jwt, jwk, JWTError
from jose.utils import base64url_decode

from services.shared.errors import unauthorized_error, forbidden_error

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "us-east-1_8KvqRmGSN")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "4q5odh7hskaevkpphb4p8jgl3j")

# Cognito JWKS URL
COGNITO_ISSUER = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"

# Valid platform roles
ADMIN_ROLE = "AdminDatos"
ANALYST_ROLE = "AnalistaDatos"
VALID_ROLES = {ADMIN_ROLE, ANALYST_ROLE}

# JWKS cache (avoid fetching on every request)
_jwks_cache: Optional[dict[str, Any]] = None
_jwks_cache_time: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour

# ─── RBAC Permission Matrix ──────────────────────────────────────────────

# Operations that each role can perform per resource type
_RBAC_MATRIX: dict[str, dict[str, set[str]]] = {
    ADMIN_ROLE: {
        "catalog": {"create", "read", "update", "delete"},
        "table": {"create", "read", "update", "delete"},
        "field": {"create", "read", "update", "delete"},
        "template": {"create", "read", "update", "delete"},
        "rule": {"create", "read", "update", "delete"},
        "validation": {"create", "read", "trigger"},
        "anomaly_training": {"create", "read", "update", "delete", "trigger"},
        "anomaly_scoring": {"create", "read", "trigger"},
        "cleaning": {"create", "read", "trigger", "approve", "reject"},
        "report": {"create", "read", "update", "delete", "publish"},
        "notification": {"create", "read", "update", "delete", "configure"},
        "dataset": {"create", "read", "update", "delete", "upload"},
        "audit": {"read"},
    },
    ANALYST_ROLE: {
        "catalog": {"read"},
        "table": {"read"},
        "field": {"read"},
        "template": {"read"},
        "rule": {"read"},
        "validation": {"read", "trigger"},
        "anomaly_training": {"read"},
        "anomaly_scoring": {"read", "trigger"},
        "cleaning": {"read", "trigger"},
        "report": {"read", "trigger"},
        "notification": {"read"},
        "dataset": {"read", "upload"},
        "audit": {"read"},
    },
}


# ─── Data Classes ─────────────────────────────────────────────────────────

from dataclasses import dataclass


@dataclass
class UserClaims:
    """Parsed user claims from JWT token."""

    sub: str  # User ID (Cognito subject)
    email: str
    role: str  # AdminDatos or AnalistaDatos
    cognito_groups: list[str]

    @property
    def is_admin(self) -> bool:
        """Check if user has AdminDatos role."""
        return self.role == ADMIN_ROLE

    @property
    def is_analyst(self) -> bool:
        """Check if user has AnalistaDatos role."""
        return self.role == ANALYST_ROLE

    @property
    def user_id(self) -> str:
        """Alias for sub (user identifier)."""
        return self.sub


# ─── JWKS Fetching ────────────────────────────────────────────────────────


def _get_jwks() -> dict[str, Any]:
    """Fetch and cache JWKS keys from Cognito.

    Returns:
        The JWKS key set as a dict.

    Raises:
        RuntimeError: If JWKS cannot be fetched.
    """
    global _jwks_cache, _jwks_cache_time

    now = time.time()
    if _jwks_cache and (now - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache

    try:
        response = requests.get(JWKS_URL, timeout=5)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = now
        logger.debug(f"Fetched JWKS from {JWKS_URL}")
        return _jwks_cache
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Failed to fetch JWKS from {JWKS_URL}: {e}")
        if _jwks_cache:
            # Use stale cache if available
            return _jwks_cache
        raise RuntimeError(f"Unable to fetch JWKS: {e}")


def _get_signing_key(token: str) -> dict[str, Any]:
    """Get the signing key for a given JWT token from the JWKS.

    Args:
        token: The JWT token string.

    Returns:
        The matching JWK key dict.

    Raises:
        JWTError: If no matching key is found.
    """
    jwks = _get_jwks()
    headers = jwt.get_unverified_headers(token)
    kid = headers.get("kid")

    if not kid:
        raise JWTError("Token header missing 'kid'")

    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key

    raise JWTError(f"No matching key found for kid: {kid}")


# ─── JWT Validation ───────────────────────────────────────────────────────


def validate_jwt_token(token: str) -> dict[str, Any]:
    """Verify a Cognito JWT token (signature, expiration, issuer).

    Validates:
    - Token signature against Cognito JWKS public keys
    - Token expiration (exp claim)
    - Token issuer matches configured Cognito User Pool
    - Token audience (client_id) for id tokens

    Args:
        token: The JWT token string (without 'Bearer ' prefix).

    Returns:
        The decoded token claims as a dict.

    Raises:
        JWTError: If token validation fails (invalid signature, expired, wrong issuer).
    """
    # Strip 'Bearer ' prefix if present
    if token.startswith("Bearer "):
        token = token[7:]

    try:
        signing_key = _get_signing_key(token)

        # Decode and verify the token
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=COGNITO_CLIENT_ID,
            issuer=COGNITO_ISSUER,
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )

        return claims

    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise


# ─── Role Extraction ──────────────────────────────────────────────────────


def get_user_role(token_claims: dict[str, Any]) -> str:
    """Extract the user's role from JWT token claims (cognito:groups).

    Priority: AdminDatos > AnalistaDatos.
    Falls back to custom:role claim if cognito:groups is not present.

    Args:
        token_claims: Decoded JWT claims dict.

    Returns:
        The role string ('AdminDatos', 'AnalistaDatos', or empty string).
    """
    groups_raw = token_claims.get("cognito:groups", "")

    if isinstance(groups_raw, str):
        groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
    elif isinstance(groups_raw, list):
        groups = groups_raw
    else:
        groups = []

    # Priority: AdminDatos > AnalistaDatos
    if ADMIN_ROLE in groups:
        return ADMIN_ROLE
    elif ANALYST_ROLE in groups:
        return ANALYST_ROLE

    # Fallback to custom:role claim
    return token_claims.get("custom:role", "")


# ─── Claims Extraction from API Gateway Event ────────────────────────────


def extract_user_claims(event: dict[str, Any]) -> Optional[UserClaims]:
    """Extract user claims from API Gateway HTTP API JWT authorizer context.

    The claims are available at:
    event['requestContext']['authorizer']['jwt']['claims']

    Args:
        event: The API Gateway Lambda proxy event.

    Returns:
        UserClaims if extraction succeeds, None otherwise.
    """
    try:
        claims = (
            event.get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )

        if not claims:
            logger.warning("No JWT claims found in event context")
            return None

        sub = claims.get("sub", "")
        email = claims.get("email", "")
        role = get_user_role(claims)

        # Extract groups
        groups_raw = claims.get("cognito:groups", "")
        if isinstance(groups_raw, str):
            groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
        elif isinstance(groups_raw, list):
            groups = groups_raw
        else:
            groups = []

        if not sub:
            logger.warning("Missing 'sub' claim in JWT")
            return None

        return UserClaims(
            sub=sub,
            email=email,
            role=role,
            cognito_groups=groups,
        )

    except (KeyError, TypeError, AttributeError) as e:
        logger.error(f"Failed to extract user claims: {e}")
        return None


# ─── RBAC Check ───────────────────────────────────────────────────────────


def is_authorized(role: str, operation: str, resource_type: str) -> bool:
    """Check if a role is authorized to perform an operation on a resource type.

    Uses the RBAC permission matrix to determine access.

    Args:
        role: The user's role ('AdminDatos' or 'AnalistaDatos').
        operation: The operation being attempted (e.g., 'create', 'read', 'delete', 'trigger').
        resource_type: The type of resource (e.g., 'catalog', 'rule', 'validation').

    Returns:
        True if the role is authorized, False otherwise.
    """
    if role not in _RBAC_MATRIX:
        return False

    role_permissions = _RBAC_MATRIX[role]
    allowed_operations = role_permissions.get(resource_type, set())
    return operation in allowed_operations


# ─── Role Enforcement (Function-based) ────────────────────────────────────


def require_role_check(
    event: dict[str, Any],
    allowed_roles: list[str],
    request_id: str = "",
) -> tuple[Optional[UserClaims], Optional[dict[str, Any]]]:
    """Validate that the request comes from a user with an allowed role.

    Args:
        event: The API Gateway Lambda proxy event.
        allowed_roles: List of roles that are permitted for this operation.
        request_id: The request ID for error responses.

    Returns:
        A tuple of (UserClaims, None) if authorized, or
        (None, error_response) if not authorized.
    """
    claims = extract_user_claims(event)

    if claims is None:
        return None, unauthorized_error(
            message="Authentication required. No valid credentials found.",
            request_id=request_id,
        )

    if not claims.role:
        return None, forbidden_error(
            message="Access denied. No recognized role assigned to this user.",
            details={"requiredRoles": allowed_roles},
            request_id=request_id,
        )

    if claims.role not in VALID_ROLES:
        return None, forbidden_error(
            message="Access denied. Unrecognized role in session token.",
            details={"role": claims.role, "requiredRoles": allowed_roles},
            request_id=request_id,
        )

    if claims.role not in allowed_roles:
        return None, forbidden_error(
            message="You do not have permission to perform this action.",
            details={"userRole": claims.role, "requiredRoles": allowed_roles},
            request_id=request_id,
        )

    return claims, None


# ─── Role Enforcement (Decorator) ────────────────────────────────────────


def require_role(allowed_roles: list[str]) -> Callable:
    """Decorator to enforce role-based access on Lambda handler functions.

    The decorated handler must accept (event, context) as parameters.
    If the user does not have an allowed role, a 403 response is returned
    without invoking the handler.

    Args:
        allowed_roles: List of roles permitted for this handler.

    Returns:
        Decorator function.

    Usage:
        @require_role([ADMIN_ROLE])
        def handler(event, context, user_claims):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(event: dict[str, Any], context: Any) -> dict[str, Any]:
            request_id = get_request_id(event)
            claims, error = require_role_check(event, allowed_roles, request_id)

            if error:
                return error

            # Pass user_claims as third argument to the handler
            return func(event, context, claims)

        return wrapper

    return decorator


# ─── Utility Functions ────────────────────────────────────────────────────


def get_request_id(event: dict[str, Any]) -> str:
    """Extract the request ID from the API Gateway event context.

    Args:
        event: The API Gateway Lambda proxy event.

    Returns:
        The request ID string, or empty string if not available.
    """
    return (
        event.get("requestContext", {}).get("requestId", "")
        or event.get("headers", {}).get("x-amzn-requestid", "")
        or ""
    )
