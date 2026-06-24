"""Table CRUD handler for the Governance Service.

Implements table management with bidirectional catalog-table references.
When a table is associated with a catalog, both the catalog item and the
table item are updated to maintain bidirectional navigability.

DynamoDB Table: dq-catalogs
- Table metadata: PK=TABLE#{table_id}, SK=METADATA
- Catalog association (catalog side): PK=CATALOG#{catalog_id}, SK=TABLE#{table_id}
- Table→Catalog back-reference stored in table metadata item

Lambda function: table-crud
Handler: handlers/tables.handler

Requirements: 3.2, 3.4, 3.6
"""

from __future__ import annotations

import json
import logging
import os
import ulid
from datetime import datetime, timezone
from typing import Any, Optional

from services.shared.auth import require_role, extract_user_claims, ADMIN_ROLE, get_request_id
from services.shared.audit import write_with_audit
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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for table CRUD operations.

    Routes:
        POST   /tables              → create table
        GET    /tables/{id}         → get table by ID
        GET    /tables              → list tables
        PUT    /tables/{id}         → update table
        DELETE /tables/{id}         → delete table
        POST   /catalog/{id}/tables → associate table to catalog

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    http_method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("path") or event.get("rawPath", "")
    request_id = get_request_id(event)

    try:
        # Route: POST /catalog/{id}/tables (associate table to catalog)
        if http_method == "POST" and "/tables" in path and "/catalog" in path:
            return _associate_table_to_catalog(event, request_id)

        # Route: POST /tables (create)
        if http_method == "POST":
            return _create_table(event, request_id)

        # Route: GET /tables/{id}
        if http_method == "GET" and _get_path_param(event, "id"):
            return _get_table(event, request_id)

        # Route: GET /tables (list)
        if http_method == "GET":
            return _list_tables(event, request_id)

        # Route: PUT /tables/{id}
        if http_method == "PUT":
            return _update_table(event, request_id)

        # Route: DELETE /tables/{id}
        if http_method == "DELETE":
            return _delete_table(event, request_id)

        return validation_error(
            message=f"Unsupported method: {http_method}",
            request_id=request_id,
        )

    except Exception as e:
        logger.exception(f"Unhandled error in table handler: {e}")
        return internal_error(
            message="An internal error occurred while processing the table request.",
            request_id=request_id,
        )


# ─── CRUD Operations ─────────────────────────────────────────────────────


def _create_table(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Create a new table metadata entry.

    AdminDatos only. Creates table item in dq-catalogs with PK=TABLE#{id}, SK=METADATA.
    """
    # Auth: AdminDatos only for write operations
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required.",
            request_id=request_id,
        )

    # Validate required fields
    name = body.get("name", "").strip()
    if not name:
        return validation_error(
            message="Missing required field: name",
            details={"missingFields": ["name"]},
            request_id=request_id,
        )

    if len(name) > 200:
        return validation_error(
            message="Table name must not exceed 200 characters.",
            request_id=request_id,
        )

    # Build table item
    table_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "PK": f"TABLE#{table_id}",
        "SK": "METADATA",
        "id": table_id,
        "name": name,
        "description": body.get("description", "").strip()[:500],
        "schema_info": body.get("schema_info", {}),
        "catalog_id": body.get("catalog_id", ""),
        "owner": claims.user_id,
        "created_at": now,
        "updated_at": now,
        "field_count": 0,
    }

    # Write with audit
    write_with_audit(
        operation_item=item,
        operation_table=CATALOGS_TABLE,
        operation_type="Put",
        user_id=claims.user_id,
        action_type="create",
        resource_type="table",
        resource_id=table_id,
        details={"name": name},
    )

    return success_response(
        body={"message": "Table created successfully.", "table": _format_table(item)},
        status_code=201,
    )


def _get_table(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Get a table by ID. Any authenticated user can read."""
    claims = extract_user_claims(event)
    if claims is None:
        return validation_error(
            message="Authentication required.",
            request_id=request_id,
        )

    table_id = _get_path_param(event, "id")
    if not table_id:
        return validation_error(
            message="Table ID is required.",
            request_id=request_id,
        )

    db = DynamoHelper(CATALOGS_TABLE)
    item = db.get_item(pk=f"TABLE#{table_id}", sk="METADATA")

    if not item:
        return not_found_error(
            message=f"Table with ID '{table_id}' not found.",
            details={"resource_type": "table", "resource_id": table_id},
            request_id=request_id,
        )

    return success_response(body={"table": _format_table(item)})


def _list_tables(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List all tables with pagination.

    Supports filtering by catalog_id via query string parameter.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return validation_error(
            message="Authentication required.",
            request_id=request_id,
        )

    params = event.get("queryStringParameters") or {}
    catalog_id = params.get("catalogId") or params.get("catalog_id")
    pagination = PaginationParams.from_event(event)

    db = DynamoHelper(CATALOGS_TABLE)

    if catalog_id:
        # Query tables associated with a specific catalog
        from boto3.dynamodb.conditions import Key

        result = db.query(
            pk_value=f"CATALOG#{catalog_id}",
            sk_condition=Key("SK").begins_with("TABLE#"),
            pagination=pagination,
        )
    else:
        # Scan for all TABLE# items (with METADATA sort key)
        from boto3.dynamodb.conditions import Key, Attr

        result = db.scan(
            filter_expression=Attr("SK").eq("METADATA") & Attr("PK").begins_with("TABLE#"),
            pagination=pagination,
        )

    items = [_format_table(item) for item in result.get("items", [])]
    total_count = result.get("count", len(items))
    next_token = result.get("next_token")

    return success_response(
        body=paginate_response(
            items=items,
            total_count=total_count,
            page_size=pagination.page_size,
            next_token=next_token,
        )
    )


def _update_table(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Update a table. AdminDatos only."""
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    table_id = _get_path_param(event, "id")
    if not table_id:
        return validation_error(
            message="Table ID is required.",
            request_id=request_id,
        )

    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required.",
            request_id=request_id,
        )

    # Verify the table exists
    db = DynamoHelper(CATALOGS_TABLE)
    existing = db.get_item(pk=f"TABLE#{table_id}", sk="METADATA")
    if not existing:
        return not_found_error(
            message=f"Table with ID '{table_id}' not found.",
            details={"resource_type": "table", "resource_id": table_id},
            request_id=request_id,
        )

    # Build update expression
    now = datetime.now(timezone.utc).isoformat()
    update_parts = ["#updated_at = :updated_at"]
    expr_values: dict[str, Any] = {":updated_at": now}
    expr_names: dict[str, str] = {"#updated_at": "updated_at"}

    if "name" in body:
        name = body["name"].strip()
        if not name:
            return validation_error(
                message="Name cannot be empty.",
                request_id=request_id,
            )
        if len(name) > 200:
            return validation_error(
                message="Table name must not exceed 200 characters.",
                request_id=request_id,
            )
        update_parts.append("#name = :name")
        expr_values[":name"] = name
        expr_names["#name"] = "name"

    if "description" in body:
        update_parts.append("#description = :description")
        expr_values[":description"] = body["description"].strip()[:500]
        expr_names["#description"] = "description"

    if "schema_info" in body:
        update_parts.append("#schema_info = :schema_info")
        expr_values[":schema_info"] = body["schema_info"]
        expr_names["#schema_info"] = "schema_info"

    update_expression = "SET " + ", ".join(update_parts)

    response = db.update_item(
        pk=f"TABLE#{table_id}",
        sk="METADATA",
        update_expression=update_expression,
        expression_values=expr_values,
        expression_names=expr_names,
    )

    # Create audit record separately (update cannot use write_with_audit directly)
    from services.shared.audit import create_audit_record

    create_audit_record(
        user_id=claims.user_id,
        action_type="update",
        resource_type="table",
        resource_id=table_id,
        details={"updatedFields": list(body.keys())},
    )

    updated_item = response.get("Attributes", existing)
    return success_response(body={"message": "Table updated.", "table": _format_table(updated_item)})


def _delete_table(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Delete a table. AdminDatos only."""
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    table_id = _get_path_param(event, "id")
    if not table_id:
        return validation_error(
            message="Table ID is required.",
            request_id=request_id,
        )

    db = DynamoHelper(CATALOGS_TABLE)
    existing = db.get_item(pk=f"TABLE#{table_id}", sk="METADATA")
    if not existing:
        return not_found_error(
            message=f"Table with ID '{table_id}' not found.",
            details={"resource_type": "table", "resource_id": table_id},
            request_id=request_id,
        )

    # Delete with audit
    key_item = {"PK": f"TABLE#{table_id}", "SK": "METADATA"}
    write_with_audit(
        operation_item=key_item,
        operation_table=CATALOGS_TABLE,
        operation_type="Delete",
        user_id=claims.user_id,
        action_type="delete",
        resource_type="table",
        resource_id=table_id,
        details={"name": existing.get("name", "")},
    )

    # Also remove any catalog association referencing this table
    catalog_id = existing.get("catalog_id", "")
    if catalog_id:
        try:
            db.delete_item(pk=f"CATALOG#{catalog_id}", sk=f"TABLE#{table_id}")
        except Exception as e:
            logger.warning(f"Failed to remove catalog association for table {table_id}: {e}")

    return success_response(body={"message": f"Table '{table_id}' deleted successfully."})


# ─── Association Operations ───────────────────────────────────────────────


def _associate_table_to_catalog(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Associate a table to a catalog with bidirectional reference.

    Validates that the table exists before creating the association.
    Updates both:
    1. Catalog item: PK=CATALOG#{catalog_id}, SK=TABLE#{table_id} (catalog→table)
    2. Table metadata item: sets catalog_id field (table→catalog back-reference)

    Requirements: 3.4, 3.6
    """
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Extract catalog_id from path
    path_params = event.get("pathParameters") or {}
    catalog_id = path_params.get("id") or path_params.get("catalogId") or ""

    if not catalog_id:
        return validation_error(
            message="Catalog ID is required in the URL path.",
            request_id=request_id,
        )

    # Parse body for table_id
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required.",
            request_id=request_id,
        )

    table_id = body.get("table_id", "").strip() or body.get("tableId", "").strip()
    if not table_id:
        return validation_error(
            message="Missing required field: table_id",
            details={"missingFields": ["table_id"]},
            request_id=request_id,
        )

    db = DynamoHelper(CATALOGS_TABLE)

    # Validate catalog exists
    catalog = db.get_item(pk=f"CATALOG#{catalog_id}", sk="METADATA")
    if not catalog:
        return not_found_error(
            message=f"Catalog with ID '{catalog_id}' not found.",
            details={"resource_type": "catalog", "resource_id": catalog_id},
            request_id=request_id,
        )

    # Validate table exists (Requirement 3.6)
    table = db.get_item(pk=f"TABLE#{table_id}", sk="METADATA")
    if not table:
        return not_found_error(
            message=f"Table with ID '{table_id}' not found. Cannot associate a non-existent table.",
            details={"resource_type": "table", "resource_id": table_id},
            request_id=request_id,
        )

    now = datetime.now(timezone.utc).isoformat()

    # 1. Create catalog→table association item
    association_item = {
        "PK": f"CATALOG#{catalog_id}",
        "SK": f"TABLE#{table_id}",
        "table_id": table_id,
        "table_name": table.get("name", ""),
        "associated_at": now,
        "associated_by": claims.user_id,
    }
    db.put_item(item=association_item)

    # 2. Update table metadata to set catalog_id back-reference
    db.update_item(
        pk=f"TABLE#{table_id}",
        sk="METADATA",
        update_expression="SET #catalog_id = :catalog_id, #updated_at = :updated_at",
        expression_values={
            ":catalog_id": catalog_id,
            ":updated_at": now,
        },
        expression_names={
            "#catalog_id": "catalog_id",
            "#updated_at": "updated_at",
        },
    )

    # Audit the association
    from services.shared.audit import create_audit_record

    create_audit_record(
        user_id=claims.user_id,
        action_type="create",
        resource_type="table",
        resource_id=table_id,
        details={
            "action": "associate_to_catalog",
            "catalog_id": catalog_id,
            "table_id": table_id,
        },
    )

    return success_response(
        body={
            "message": f"Table '{table_id}' associated to catalog '{catalog_id}' successfully.",
            "association": {
                "catalogId": catalog_id,
                "tableId": table_id,
                "associatedAt": now,
            },
        },
        status_code=201,
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
    return body


def _get_path_param(event: dict[str, Any], param: str) -> str:
    """Extract a path parameter from the event."""
    path_params = event.get("pathParameters") or {}
    return path_params.get(param, "")


def _format_table(item: dict[str, Any]) -> dict[str, Any]:
    """Format a table item for API response (strip internal keys)."""
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "schemaInfo": item.get("schema_info", {}),
        "catalogId": item.get("catalog_id", ""),
        "owner": item.get("owner", ""),
        "createdAt": item.get("created_at", ""),
        "updatedAt": item.get("updated_at", ""),
        "fieldCount": item.get("field_count", 0),
    }
