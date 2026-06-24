"""Catalog CRUD Lambda handler for the Governance Service.

Handles HTTP API routes for catalog management:
- POST   /catalog           → create_catalog (AdminDatos only)
- GET    /catalog           → list_catalogs (any authenticated user)
- GET    /catalog/{id}      → get_catalog (any authenticated user)
- PUT    /catalog/{id}      → update_catalog (AdminDatos only)
- DELETE /catalog/{id}      → delete_catalog (AdminDatos only)

DynamoDB Table: dq-catalogs
- PK: CATALOG#{catalog_id}
- SK: METADATA
- GSI owner-index: PK=owner, SK=createdAt

Requirements: 3.1, 3.3, 3.5
"""

from __future__ import annotations

import json
import logging
import os
import ulid
from datetime import datetime, timezone
from typing import Any, Optional

from services.shared.auth import (
    ADMIN_ROLE,
    ANALYST_ROLE,
    extract_user_claims,
    get_request_id,
    require_role,
)
from services.shared.audit import write_with_audit
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    internal_error,
    not_found_error,
    success_response,
    validation_error,
)
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
CATALOG_TABLE_NAME = os.environ.get("CATALOG_TABLE_NAME", "dq-catalogs")
OWNER_INDEX_NAME = "owner-index"

# Validation limits
MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for catalog CRUD operations.

    Routes requests based on HTTP method and path to the appropriate handler.

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)

    try:
        http_method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "") or event.get("path", "")

        # Extract catalog_id from path if present
        catalog_id = _extract_catalog_id(path)

        if http_method == "POST" and not catalog_id:
            return _create_catalog(event, request_id)
        elif http_method == "GET" and catalog_id:
            return _get_catalog(event, catalog_id, request_id)
        elif http_method == "GET" and not catalog_id:
            return _list_catalogs(event, request_id)
        elif http_method == "PUT" and catalog_id:
            return _update_catalog(event, catalog_id, request_id)
        elif http_method == "DELETE" and catalog_id:
            return _delete_catalog(event, catalog_id, request_id)
        else:
            return validation_error(
                message=f"Unsupported method or path: {http_method} {path}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in catalog handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the catalog request.",
            request_id=request_id,
        )


def _extract_catalog_id(path: str) -> Optional[str]:
    """Extract catalog ID from the request path.

    Expected paths:
    - /catalog → None
    - /catalog/{id} → id

    Args:
        path: The raw request path.

    Returns:
        The catalog ID if present, None otherwise.
    """
    # Normalize path
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /catalog/{id}
    if len(parts) >= 2 and parts[0] == "catalog":
        return parts[1]

    return None


# ─── Create Catalog ───────────────────────────────────────────────────────────


def _create_catalog(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Create a new catalog entry (AdminDatos only).

    Validates:
    - name: required, max 100 characters
    - description: optional, max 500 characters
    - owner: required

    Args:
        event: API Gateway event.
        request_id: The request ID for error responses.

    Returns:
        API Gateway response with created catalog or error.
    """
    # Authorization: AdminDatos only
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    # Validate fields
    errors = _validate_create_request(body)
    if errors:
        return validation_error(
            message="Validation failed. Required fields are missing or invalid.",
            details={"fields": errors},
            request_id=request_id,
        )

    # Build catalog item
    catalog_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    catalog_item = {
        "PK": f"CATALOG#{catalog_id}",
        "SK": "METADATA",
        "id": catalog_id,
        "name": body["name"].strip(),
        "description": body.get("description", "").strip(),
        "owner": body["owner"].strip(),
        "createdAt": now,
        "updatedAt": now,
        "tableIds": [],
    }

    # Write with audit (transactional integrity)
    try:
        write_with_audit(
            operation_item=catalog_item,
            operation_table=CATALOG_TABLE_NAME,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="create",
            resource_type="catalog",
            resource_id=catalog_id,
            details={
                "name": catalog_item["name"],
                "owner": catalog_item["owner"],
            },
        )
    except Exception as e:
        logger.error(f"Failed to create catalog with audit: {e}")
        return internal_error(
            message="Failed to create catalog. The operation could not be completed.",
            request_id=request_id,
        )

    # Return created catalog (without DynamoDB keys)
    response_body = _format_catalog_response(catalog_item)
    return success_response(response_body, status_code=201)


def _validate_create_request(body: dict[str, Any]) -> dict[str, str]:
    """Validate the create catalog request body.

    Args:
        body: The parsed request body.

    Returns:
        Dict of field name → error message for invalid fields.
        Empty dict if all fields are valid.
    """
    errors: dict[str, str] = {}

    # Name: required, max 100 chars
    name = body.get("name")
    if not name or not str(name).strip():
        errors["name"] = "Name is required."
    elif len(str(name).strip()) > MAX_NAME_LENGTH:
        errors["name"] = f"Name must not exceed {MAX_NAME_LENGTH} characters."

    # Owner: required
    owner = body.get("owner")
    if not owner or not str(owner).strip():
        errors["owner"] = "Owner is required."

    # Description: optional, max 500 chars
    description = body.get("description", "")
    if description and len(str(description).strip()) > MAX_DESCRIPTION_LENGTH:
        errors["description"] = (
            f"Description must not exceed {MAX_DESCRIPTION_LENGTH} characters."
        )

    return errors


# ─── Get Catalog by ID ────────────────────────────────────────────────────────


def _get_catalog(
    event: dict[str, Any], catalog_id: str, request_id: str
) -> dict[str, Any]:
    """Get a catalog entry by ID (any authenticated user).

    Args:
        event: API Gateway event.
        catalog_id: The catalog ID to retrieve.
        request_id: The request ID.

    Returns:
        API Gateway response with catalog data or error.
    """
    # Any authenticated user can read
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    db = DynamoHelper(CATALOG_TABLE_NAME)
    item = db.get_item(pk=f"CATALOG#{catalog_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Catalog with ID '{catalog_id}' not found.",
            details={"catalogId": catalog_id},
            request_id=request_id,
        )

    response_body = _format_catalog_response(item)
    return success_response(response_body)


# ─── List Catalogs ────────────────────────────────────────────────────────────


def _list_catalogs(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List catalogs with pagination and optional filters.

    Supports filtering by:
    - name: substring match (case-insensitive)
    - owner: exact match via GSI
    - createdAfter: ISO 8601 date filter
    - createdBefore: ISO 8601 date filter

    Pagination: default 20, max 100 items per page.

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with paginated catalog list.
    """
    # Any authenticated user can list
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Parse pagination params
    pagination = PaginationParams.from_event(event)

    # Parse filter params
    params = event.get("queryStringParameters") or {}
    filter_name = params.get("name")
    filter_owner = params.get("owner")
    filter_created_after = params.get("createdAfter")
    filter_created_before = params.get("createdBefore")

    db = DynamoHelper(CATALOG_TABLE_NAME)

    # If filtering by owner, use the owner-index GSI
    if filter_owner:
        result = _query_by_owner(
            db, filter_owner, pagination, filter_name,
            filter_created_after, filter_created_before,
        )
    else:
        result = _scan_catalogs(
            db, pagination, filter_name,
            filter_created_after, filter_created_before,
        )

    # Format response items
    items = [_format_catalog_response(item) for item in result["items"]]

    response_body = paginate_response(
        items=items,
        total_count=result.get("total_count", result["count"]),
        page_size=pagination.page_size,
        next_token=result.get("next_token"),
    )

    return success_response(response_body)


def _query_by_owner(
    db: DynamoHelper,
    owner: str,
    pagination: PaginationParams,
    filter_name: Optional[str] = None,
    filter_created_after: Optional[str] = None,
    filter_created_before: Optional[str] = None,
) -> dict[str, Any]:
    """Query catalogs by owner using GSI.

    Args:
        db: DynamoHelper instance.
        owner: The owner to filter by.
        pagination: Pagination params.
        filter_name: Optional name substring filter.
        filter_created_after: Optional date filter (ISO 8601).
        filter_created_before: Optional date filter (ISO 8601).

    Returns:
        Query result with items, count, and optional next_token.
    """
    from boto3.dynamodb.conditions import Attr

    # Build filter expression for additional filters
    filter_expr = None

    if filter_name:
        name_filter = Attr("name").contains(filter_name)
        filter_expr = name_filter if filter_expr is None else filter_expr & name_filter

    if filter_created_after:
        after_filter = Attr("createdAt").gte(filter_created_after)
        filter_expr = after_filter if filter_expr is None else filter_expr & after_filter

    if filter_created_before:
        before_filter = Attr("createdAt").lte(filter_created_before)
        filter_expr = (
            before_filter if filter_expr is None else filter_expr & before_filter
        )

    result = db.query_gsi(
        index_name=OWNER_INDEX_NAME,
        pk_name="owner",
        pk_value=owner,
        filter_expression=filter_expr,
        pagination=pagination,
        scan_forward=False,  # Most recent first
    )

    # Get total count for the owner
    total_count = db.get_item_count(
        pk_value=owner,
        index_name=OWNER_INDEX_NAME,
        filter_expression=filter_expr,
    )
    result["total_count"] = total_count

    return result


def _scan_catalogs(
    db: DynamoHelper,
    pagination: PaginationParams,
    filter_name: Optional[str] = None,
    filter_created_after: Optional[str] = None,
    filter_created_before: Optional[str] = None,
) -> dict[str, Any]:
    """Scan catalogs with optional filters.

    Args:
        db: DynamoHelper instance.
        pagination: Pagination params.
        filter_name: Optional name substring filter.
        filter_created_after: Optional date filter.
        filter_created_before: Optional date filter.

    Returns:
        Scan result with items, count, and optional next_token.
    """
    from boto3.dynamodb.conditions import Attr

    # Always filter to only METADATA sort keys (catalog entries)
    filter_expr = Attr("SK").eq("METADATA")

    if filter_name:
        filter_expr = filter_expr & Attr("name").contains(filter_name)

    if filter_created_after:
        filter_expr = filter_expr & Attr("createdAt").gte(filter_created_after)

    if filter_created_before:
        filter_expr = filter_expr & Attr("createdAt").lte(filter_created_before)

    result = db.scan(
        filter_expression=filter_expr,
        pagination=pagination,
    )

    # For scan, total_count is approximate (use count from this page)
    result["total_count"] = result["count"]

    return result


# ─── Update Catalog ───────────────────────────────────────────────────────────


def _update_catalog(
    event: dict[str, Any], catalog_id: str, request_id: str
) -> dict[str, Any]:
    """Update a catalog entry (AdminDatos only).

    Updatable fields: name, description, owner.
    At least one field must be provided.

    Args:
        event: API Gateway event.
        catalog_id: The catalog ID to update.
        request_id: The request ID.

    Returns:
        API Gateway response with updated catalog or error.
    """
    # Authorization: AdminDatos only
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    # Validate update fields
    errors = _validate_update_request(body)
    if errors:
        return validation_error(
            message="Validation failed. One or more fields are invalid.",
            details={"fields": errors},
            request_id=request_id,
        )

    # Check catalog exists
    db = DynamoHelper(CATALOG_TABLE_NAME)
    existing = db.get_item(pk=f"CATALOG#{catalog_id}", sk="METADATA")
    if existing is None:
        return not_found_error(
            message=f"Catalog with ID '{catalog_id}' not found.",
            details={"catalogId": catalog_id},
            request_id=request_id,
        )

    # Build updated item
    now = datetime.now(timezone.utc).isoformat()
    updated_item = dict(existing)
    updated_item["updatedAt"] = now

    changes: dict[str, Any] = {}
    if "name" in body and body["name"] is not None:
        updated_item["name"] = body["name"].strip()
        changes["name"] = updated_item["name"]
    if "description" in body and body["description"] is not None:
        updated_item["description"] = body["description"].strip()
        changes["description"] = updated_item["description"]
    if "owner" in body and body["owner"] is not None:
        updated_item["owner"] = body["owner"].strip()
        changes["owner"] = updated_item["owner"]

    if not changes:
        return validation_error(
            message="At least one field (name, description, or owner) must be provided for update.",
            request_id=request_id,
        )

    # Write with audit
    try:
        write_with_audit(
            operation_item=updated_item,
            operation_table=CATALOG_TABLE_NAME,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="update",
            resource_type="catalog",
            resource_id=catalog_id,
            details={"changes": changes},
        )
    except Exception as e:
        logger.error(f"Failed to update catalog with audit: {e}")
        return internal_error(
            message="Failed to update catalog. The operation could not be completed.",
            request_id=request_id,
        )

    response_body = _format_catalog_response(updated_item)
    return success_response(response_body)


def _validate_update_request(body: dict[str, Any]) -> dict[str, str]:
    """Validate the update catalog request body.

    Args:
        body: The parsed request body.

    Returns:
        Dict of field name → error message for invalid fields.
    """
    errors: dict[str, str] = {}

    # Name: optional, but if provided must be valid
    name = body.get("name")
    if name is not None:
        if not str(name).strip():
            errors["name"] = "Name cannot be empty."
        elif len(str(name).strip()) > MAX_NAME_LENGTH:
            errors["name"] = f"Name must not exceed {MAX_NAME_LENGTH} characters."

    # Description: optional, but if provided must be valid
    description = body.get("description")
    if description is not None and len(str(description).strip()) > MAX_DESCRIPTION_LENGTH:
        errors["description"] = (
            f"Description must not exceed {MAX_DESCRIPTION_LENGTH} characters."
        )

    # Owner: optional, but if provided must not be empty
    owner = body.get("owner")
    if owner is not None and not str(owner).strip():
        errors["owner"] = "Owner cannot be empty."

    return errors


# ─── Delete Catalog ───────────────────────────────────────────────────────────


def _delete_catalog(
    event: dict[str, Any], catalog_id: str, request_id: str
) -> dict[str, Any]:
    """Delete a catalog entry (AdminDatos only).

    Args:
        event: API Gateway event.
        catalog_id: The catalog ID to delete.
        request_id: The request ID.

    Returns:
        API Gateway response confirming deletion or error.
    """
    # Authorization: AdminDatos only
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Check catalog exists
    db = DynamoHelper(CATALOG_TABLE_NAME)
    existing = db.get_item(pk=f"CATALOG#{catalog_id}", sk="METADATA")
    if existing is None:
        return not_found_error(
            message=f"Catalog with ID '{catalog_id}' not found.",
            details={"catalogId": catalog_id},
            request_id=request_id,
        )

    # Delete with audit
    delete_key = {
        "PK": f"CATALOG#{catalog_id}",
        "SK": "METADATA",
    }

    try:
        write_with_audit(
            operation_item=delete_key,
            operation_table=CATALOG_TABLE_NAME,
            operation_type="Delete",
            user_id=claims.user_id,
            action_type="delete",
            resource_type="catalog",
            resource_id=catalog_id,
            details={
                "name": existing.get("name"),
                "owner": existing.get("owner"),
            },
        )
    except Exception as e:
        logger.error(f"Failed to delete catalog with audit: {e}")
        return internal_error(
            message="Failed to delete catalog. The operation could not be completed.",
            request_id=request_id,
        )

    return success_response(
        {"message": f"Catalog '{catalog_id}' deleted successfully."},
        status_code=200,
    )


# ─── Utility Functions ────────────────────────────────────────────────────────


def _parse_body(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse the JSON body from the API Gateway event.

    Args:
        event: API Gateway event.

    Returns:
        Parsed body dict, or None if body is missing/invalid.
    """
    body = event.get("body")
    if body is None:
        return None

    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None

    if isinstance(body, dict):
        return body

    return None


def _format_catalog_response(item: dict[str, Any]) -> dict[str, Any]:
    """Format a DynamoDB catalog item for API response.

    Removes internal DynamoDB keys (PK, SK, GSI keys) and returns
    a clean response object.

    Args:
        item: The raw DynamoDB item.

    Returns:
        Formatted catalog response dict.
    """
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description", ""),
        "owner": item.get("owner"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "tableIds": item.get("tableIds", []),
    }
