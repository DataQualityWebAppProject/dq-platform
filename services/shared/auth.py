"""JWT authentication and role-based access control for the Data Quality Platform.

Provides:
- Role extraction from cognito:groups (via API Gateway JWT authorizer context)
- Role-based access control decorators
- RBAC permission matrix

Roles:
- AdminDatos: Full CRUD access to all platform resources
- AnalistaDatos: Read access + trigger operations (validation, scoring, cleaning, reports)

JWT validation is handled by API Gateway's built-in JWT authorizer.
Lambda functions only extract claims from the event context.

Requirements: 1.3, 2.1, 2.2, 2.3, 2.6
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from services.shared.errors import unauthorized_error, forbidden_error

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "us-east-1_8KvqRmGSN")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "4q5odh7hskaevkpphb4p8jgl3j")

# Valid platform roles
ADMIN_ROLE = "AdminDatos"
ANALYST_ROLE = "AnalistaDatos"
VALID_ROLES = {ADMIN_ROLE, ANALYST_ROLE}

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
        # API Gateway may pass groups as "[AdminDatos]" or "AdminDatos" or "AdminDatos,AnalistaDatos"
        cleaned = groups_raw.strip().strip("[]")
        groups = [g.strip().strip('"').strip("'") for g in cleaned.split(",") if g.strip()]
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
            cleaned = groups_raw.strip().strip("[]")
            groups = [g.strip().strip('"').strip("'") for g in cleaned.split(",") if g.strip()]
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


def require_role(
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


# Alias for backward compatibility
require_role_check = require_role


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
