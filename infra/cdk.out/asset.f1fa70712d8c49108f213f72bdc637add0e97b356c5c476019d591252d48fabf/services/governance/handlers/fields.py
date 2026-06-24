"""Field CRUD handler for the Governance Service.

Implements field/column management for tables:
- POST   /tables/{id}/fields          → create field
- GET    /tables/{id}/fields           → list fields for a table
- GET    /tables/{id}/fields/{fid}     → get field by ID
- PUT    /tables/{id}/fields/{fid}     → update field
- DELETE /tables/{id}/fields/{fid}     → delete field

DynamoDB Table: dq-catalogs
- Fields stored as PK=TABLE#{table_id}, SK=FIELD#{field_id}

Each field has: name, type (string/number/date/boolean), required flag

Requirements: 3.2, 3.4, 3.6
"""

from __future__ import annotations

import json
import logging
import os
import ulid
from datetime import datetime, timezone
from typing import Any, Optional

from services.shared.auth import (
    require_role,
    extract_user_claims,
    ADMIN_ROLE,
    get_request_id,
)
from services.shared.audit import write_with_audit, create_audit_record
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    success_response,
    validation_error,
    not_found_error,
    internal_error,
)
from services.shared.pagination import PaginationParams, paginate_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
CATALOGS_TABLE = os.environ.get("CATALOGS_TABLE_NAME", "dq-catalogs")

# Valid field types
VALID_FIELD_TYPES = {"string", "number", "date", "boolean"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for field CRUD operations.

    Routes:
        POST   /tables/{id}/fields          → create field
        GET    /tables/{id}/fields           → list fields for a table
        GET    /tables/{id}/fields/{fid}     → get field by ID
        PUT    /tables/{id}/fields/{fid}     → update field
        DELETE /tables/{id}/fields/{fid}     → delete field

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method", "")
    )
    path = event.get("rawPath", "") or event.get("path", "")
    request_id = get_request_id(event)

    try:
        # Extract path parameters
        path_params = event.get("pathParameters") or {}
        table_id = path_params.get("id") or path_params.get("tableId") or _extract_table_id(path)
        field_id = path_params.get("fieldId") or path_params.get("fid") or _extract_field_id(path)

        if http_method == "POST":
            return _create_field(event, table_id, request_id)
        elif http_method == "GET" and field_id:
            return _get_field(event, table_id, field_id, request_id)
        elif http_method == "GET":
            return _list_fields(event, table_id, request_id)
        elif http_method == "PUT" and field_id:
            return _update_field(event, table_id, field_id, request_id)
        elif http_method == "DELETE" and field_id:
            return _delete_field(event, table_id, field_id, request_id)
        else:
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in field handler: {e}")
        return internal_error(
            message="An internal error occurred while processing the request.",
            request_id=request_id,
        )


# ─── Create Field ─────────────────────────────────────────────────────────


def _create_field(
    event: dict[str, Any], table_id: str, request_id: str
) -> dict[str, Any]:
    """Create a field in a table. AdminDatos only.

    Validates:
    - name: required
    - type: required, must be one of string/number/date/boolean
    - required: optional boolean flag (defaults to False)
    """
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    if not table_id:
        return validation_error(
            message="Table ID is required in the URL path.",
            request_id=request_id,
        )

    body = _parse_body(event)
    if body is None:
        return validation_error(message="Request body is required.", request_id=request_id)

    # Validate required fields
    name = body.get("name", "").strip() if body.get("name") else ""
    field_type = body.get("type", "").strip().lower() if body.get("type") else ""

    missing = []
    if not name:
        missing.append("name")
    if not field_type:
        missing.append("type")
    if missing:
        return validation_error(
            message=f"Missing required fields: {', '.join(missing)}",
            details={"missingFields": missing},
            request_id=request_id,
        )

    if field_type not in VALID_FIELD_TYPES:
        return validation_error(
            message=f"Invalid field type '{field_type}'. Must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}",
            request_id=request_id,
        )

    # Verify parent table exists
    db = DynamoHelper(CATALOGS_TABLE)
    table_item = db.get_item(pk=f"TABLE#{table_id}", sk="METADATA")
    if not table_item:
        return not_found_error(
            message=f"Parent table '{table_id}' not found.",
            details={"resource_type": "table", "resource_id": table_id},
            request_id=request_id,
        )

    field_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "PK": f"TABLE#{table_id}",
        "SK": f"FIELD#{field_id}",
        "id": field_id,
        "table_id": table_id,
        "name": name,
        "field_type": field_type,
        "required": bool(body.get("required", False)),
        "description": body.get("description", "").strip()[:500] if body.get("description") else "",
        "created_at": now,
        "updated_at": now,
        "created_by": claims.user_id,
    }

    # Write with audit
    try:
        write_with_audit(
            operation_item=item,
            operation_table=CATALOGS_TABLE,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="create",
            resource_type="field",
            resource_id=field_id,
            details={"name": name, "table_id": table_id, "type": field_type},
        )
    except Exception as e:
        logger.error(f"Failed to create field with audit: {e}")
        return internal_error(
            message="Failed to create field.",
            request_id=request_id,
        )

    # Update field count on parent table
    try:
        db.update_item(
            pk=f"TABLE#{table_id}",
            sk="METADATA",
            update_expression="SET #field_count = if_not_exists(#field_count, :zero) + :one",
            expression_values={":zero": 0, ":one": 1},
            expression_names={"#field_count": "field_count"},
        )
    except Exception as e:
        logger.warning(f"Failed to update field_count for table {table_id}: {e}")

    return success_response(
        body={"message": "Field created successfully.", "field": _format_field(item)},
        status_code=201,
    )


# ─── Get Field ────────────────────────────────────────────────────────────


def _get_field(
    event: dict[str, Any], table_id: str, field_id: str, request_id: str
) -> dict[str, Any]:
    """Get a field by ID. Any authenticated user can read."""
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if not table_id or not field_id:
        return validation_error(
            message="Table ID and Field ID are required.",
            request_id=request_id,
        )

    db = DynamoHelper(CATALOGS_TABLE)
    item = db.get_item(pk=f"TABLE#{table_id}", sk=f"FIELD#{field_id}")

    if not item:
        return not_found_error(
            message=f"Field with ID '{field_id}' not found in table '{table_id}'.",
            details={"resource_type": "field", "resource_id": field_id},
            request_id=request_id,
        )

    return success_response(body={"field": _format_field(item)})


# ─── List Fields ──────────────────────────────────────────────────────────


def _list_fields(
    event: dict[str, Any], table_id: str, request_id: str
) -> dict[str, Any]:
    """List all fields for a table with pagination."""
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if not table_id:
        return validation_error(
            message="Table ID is required.",
            request_id=request_id,
        )

    pagination = PaginationParams.from_event(event)
    db = DynamoHelper(CATALOGS_TABLE)

    from boto3.dynamodb.conditions import Key

    result = db.query(
        pk_value=f"TABLE#{table_id}",
        sk_condition=Key("SK").begins_with("FIELD#"),
        pagination=pagination,
    )

    items = [_format_field(item) for item in result.get("items", [])]
    next_token = result.get("next_token")

    return success_response(
        body=paginate_response(
            items=items,
            total_count=result.get("count", len(items)),
            page_size=pagination.page_size,
            next_token=next_token,
        )
    )


# ─── Update Field ─────────────────────────────────────────────────────────


def _update_field(
    event: dict[str, Any], table_id: str, field_id: str, request_id: str
) -> dict[str, Any]:
    """Update a field. AdminDatos only."""
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    if not table_id or not field_id:
        return validation_error(
            message="Table ID and Field ID are required.",
            request_id=request_id,
        )

    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required.",
            request_id=request_id,
        )

    db = DynamoHelper(CATALOGS_TABLE)
    existing = db.get_item(pk=f"TABLE#{table_id}", sk=f"FIELD#{field_id}")
    if not existing:
        return not_found_error(
            message=f"Field with ID '{field_id}' not found in table '{table_id}'.",
            details={"resource_type": "field", "resource_id": field_id},
            request_id=request_id,
        )

    # Build update expression
    now = datetime.now(timezone.utc).isoformat()
    update_parts = ["#updated_at = :updated_at"]
    expr_values: dict[str, Any] = {":updated_at": now}
    expr_names: dict[str, str] = {"#updated_at": "updated_at"}
    changes: dict[str, Any] = {}

    if "name" in body:
        name = body["name"].strip() if body["name"] else ""
        if not name:
            return validation_error(message="Name cannot be empty.", request_id=request_id)
        update_parts.append("#name = :name")
        expr_values[":name"] = name
        expr_names["#name"] = "name"
        changes["name"] = name

    if "type" in body:
        field_type = body["type"].strip().lower() if body["type"] else ""
        if field_type not in VALID_FIELD_TYPES:
            return validation_error(
                message=f"Invalid field type '{field_type}'. Must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}",
                request_id=request_id,
            )
        update_parts.append("#field_type = :field_type")
        expr_values[":field_type"] = field_type
        expr_names["#field_type"] = "field_type"
        changes["type"] = field_type

    if "required" in body:
        update_parts.append("#required = :required")
        expr_values[":required"] = bool(body["required"])
        expr_names["#required"] = "required"
        changes["required"] = bool(body["required"])

    if "description" in body:
        update_parts.append("#description = :description")
        expr_values[":description"] = body["description"].strip()[:500] if body["description"] else ""
        expr_names["#description"] = "description"
        changes["description"] = expr_values[":description"]

    if not changes:
        return validation_error(
            message="At least one field must be provided for update.",
            request_id=request_id,
        )

    update_expression = "SET " + ", ".join(update_parts)

    try:
        response = db.update_item(
            pk=f"TABLE#{table_id}",
            sk=f"FIELD#{field_id}",
            update_expression=update_expression,
            expression_values=expr_values,
            expression_names=expr_names,
        )
    except Exception as e:
        logger.error(f"Failed to update field: {e}")
        return internal_error(
            message="Failed to update field.",
            request_id=request_id,
        )

    # Create audit record
    create_audit_record(
        user_id=claims.user_id,
        action_type="update",
        resource_type="field",
        resource_id=field_id,
        details={"table_id": table_id, "changes": changes},
    )

    updated_item = response.get("Attributes", existing)
    return success_response(body={"message": "Field updated.", "field": _format_field(updated_item)})


# ─── Delete Field ─────────────────────────────────────────────────────────


def _delete_field(
    event: dict[str, Any], table_id: str, field_id: str, request_id: str
) -> dict[str, Any]:
    """Delete a field. AdminDatos only."""
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    if not table_id or not field_id:
        return validation_error(
            message="Table ID and Field ID are required.",
            request_id=request_id,
        )

    db = DynamoHelper(CATALOGS_TABLE)
    existing = db.get_item(pk=f"TABLE#{table_id}", sk=f"FIELD#{field_id}")
    if not existing:
        return not_found_error(
            message=f"Field with ID '{field_id}' not found in table '{table_id}'.",
            details={"resource_type": "field", "resource_id": field_id},
            request_id=request_id,
        )

    # Delete with audit
    delete_key = {"PK": f"TABLE#{table_id}", "SK": f"FIELD#{field_id}"}
    try:
        write_with_audit(
            operation_item=delete_key,
            operation_table=CATALOGS_TABLE,
            operation_type="Delete",
            user_id=claims.user_id,
            action_type="delete",
            resource_type="field",
            resource_id=field_id,
            details={"name": existing.get("name", ""), "table_id": table_id},
        )
    except Exception as e:
        logger.error(f"Failed to delete field with audit: {e}")
        return internal_error(
            message="Failed to delete field.",
            request_id=request_id,
        )

    # Decrement field count on parent table
    try:
        db.update_item(
            pk=f"TABLE#{table_id}",
            sk="METADATA",
            update_expression="SET #field_count = if_not_exists(#field_count, :one) - :one",
            expression_values={":one": 1},
            expression_names={"#field_count": "field_count"},
        )
    except Exception as e:
        logger.warning(f"Failed to decrement field_count for table {table_id}: {e}")

    return success_response(
        body={"message": f"Field '{field_id}' deleted successfully."},
        status_code=200,
    )


# ─── Utilities ────────────────────────────────────────────────────────────


def _parse_body(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse the request body from the event."""
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


def _extract_table_id(path: str) -> str:
    """Extract table ID from path like /tables/{id}/fields or /tables/{id}/fields/{fid}."""
    parts = [p for p in path.strip("/").split("/") if p]
    try:
        idx = parts.index("tables")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return ""


def _extract_field_id(path: str) -> str:
    """Extract field ID from path like /tables/{id}/fields/{fid}."""
    parts = [p for p in path.strip("/").split("/") if p]
    try:
        idx = parts.index("fields")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return ""


def _format_field(item: dict[str, Any]) -> dict[str, Any]:
    """Format a field item for API response (strip internal keys)."""
    return {
        "id": item.get("id", ""),
        "tableId": item.get("table_id", ""),
        "name": item.get("name", ""),
        "type": item.get("field_type", ""),
        "required": item.get("required", False),
        "description": item.get("description", ""),
        "createdAt": item.get("created_at", ""),
        "updatedAt": item.get("updated_at", ""),
        "createdBy": item.get("created_by", ""),
    }
