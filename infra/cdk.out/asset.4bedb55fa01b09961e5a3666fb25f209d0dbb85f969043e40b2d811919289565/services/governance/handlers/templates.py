"""Mapping Template CRUD handler for the Governance Service.

Implements template management for defining field mappings:
- POST   /templates           → create template
- GET    /templates           → list templates
- GET    /templates/{id}      → get template with fields
- PUT    /templates/{id}      → update template
- DELETE /templates/{id}      → delete template

A template defines a set of expected fields (field_name, field_type, required)
that can be associated with catalog entries for validation purposes.

DynamoDB Table: dq-templates
- PK: TEMPLATE#{template_id}
- SK: METADATA (template metadata)

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
TEMPLATES_TABLE = os.environ.get("TEMPLATES_TABLE_NAME", "dq-templates")
CATALOGS_TABLE = os.environ.get("CATALOGS_TABLE_NAME", "dq-catalogs")

# Valid field types for template fields
VALID_FIELD_TYPES = {"string", "number", "date", "boolean"}

# Validation limits
MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for mapping template CRUD operations.

    Routes:
        POST   /templates           → create template
        GET    /templates           → list templates
        GET    /templates/{id}      → get template
        PUT    /templates/{id}      → update template
        DELETE /templates/{id}      → delete template

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
        # Extract template_id from path parameters or path
        path_params = event.get("pathParameters") or {}
        template_id = path_params.get("id") or path_params.get("templateId") or _extract_template_id(path)

        if http_method == "POST" and not template_id:
            return _create_template(event, request_id)
        elif http_method == "GET" and template_id:
            return _get_template(event, template_id, request_id)
        elif http_method == "GET" and not template_id:
            return _list_templates(event, request_id)
        elif http_method == "PUT" and template_id:
            return _update_template(event, template_id, request_id)
        elif http_method == "DELETE" and template_id:
            return _delete_template(event, template_id, request_id)
        else:
            return validation_error(
                message=f"Unsupported method or path: {http_method} {path}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in template handler: {e}")
        return internal_error(
            message="An internal error occurred while processing the template request.",
            request_id=request_id,
        )


# ─── Create Template ──────────────────────────────────────────────────────


def _create_template(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Create a new mapping template. AdminDatos only.

    Body:
    {
        "name": "Template Name" (required, max 100 chars),
        "description": "..." (optional, max 500 chars),
        "catalogId": "..." (optional, associate with catalog),
        "fields": [
            {"field_name": "col1", "field_type": "string", "required": true},
            ...
        ]
    }
    """
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    # Validate name
    name = body.get("name", "").strip() if body.get("name") else ""
    if not name:
        return validation_error(
            message="Name is required.",
            details={"missingFields": ["name"]},
            request_id=request_id,
        )
    if len(name) > MAX_NAME_LENGTH:
        return validation_error(
            message=f"Name must not exceed {MAX_NAME_LENGTH} characters.",
            request_id=request_id,
        )

    # Validate description
    description = body.get("description", "").strip() if body.get("description") else ""
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return validation_error(
            message=f"Description must not exceed {MAX_DESCRIPTION_LENGTH} characters.",
            request_id=request_id,
        )

    # Validate fields list
    fields = body.get("fields", [])
    if not isinstance(fields, list):
        return validation_error(
            message="Fields must be a list.",
            request_id=request_id,
        )

    validated_fields = []
    for i, field in enumerate(fields):
        field_error = _validate_template_field(field, i)
        if field_error:
            return validation_error(
                message=field_error,
                request_id=request_id,
            )
        validated_fields.append({
            "field_name": field["field_name"].strip(),
            "field_type": field["field_type"].strip().lower(),
            "required": bool(field.get("required", False)),
        })

    # Optional catalog association
    catalog_id = body.get("catalogId", "").strip() if body.get("catalogId") else ""

    # If catalog_id provided, verify catalog exists
    if catalog_id:
        catalogs_db = DynamoHelper(CATALOGS_TABLE)
        catalog = catalogs_db.get_item(pk=f"CATALOG#{catalog_id}", sk="METADATA")
        if not catalog:
            return not_found_error(
                message=f"Catalog '{catalog_id}' not found. Cannot associate template.",
                details={"catalogId": catalog_id},
                request_id=request_id,
            )

    template_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "PK": f"TEMPLATE#{template_id}",
        "SK": "METADATA",
        "id": template_id,
        "name": name,
        "description": description,
        "fields": validated_fields,
        "catalog_id": catalog_id,
        "created_at": now,
        "updated_at": now,
        "created_by": claims.user_id,
        "field_count": len(validated_fields),
    }

    # Write with audit
    try:
        write_with_audit(
            operation_item=item,
            operation_table=TEMPLATES_TABLE,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="create",
            resource_type="template",
            resource_id=template_id,
            details={"name": name, "field_count": len(validated_fields)},
        )
    except Exception as e:
        logger.error(f"Failed to create template with audit: {e}")
        return internal_error(
            message="Failed to create template.",
            request_id=request_id,
        )

    # If catalog association, write the reference in catalogs table
    if catalog_id:
        try:
            catalogs_db = DynamoHelper(CATALOGS_TABLE)
            catalogs_db.put_item(item={
                "PK": f"CATALOG#{catalog_id}",
                "SK": f"TEMPLATE#{template_id}",
                "template_id": template_id,
                "template_name": name,
                "associated_at": now,
                "associated_by": claims.user_id,
            })
        except Exception as e:
            logger.warning(f"Failed to write catalog-template association: {e}")

    return success_response(
        body={"message": "Template created successfully.", "template": _format_template(item)},
        status_code=201,
    )


# ─── Get Template ─────────────────────────────────────────────────────────


def _get_template(
    event: dict[str, Any], template_id: str, request_id: str
) -> dict[str, Any]:
    """Get a template by ID. Any authenticated user can read."""
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    db = DynamoHelper(TEMPLATES_TABLE)
    item = db.get_item(pk=f"TEMPLATE#{template_id}", sk="METADATA")

    if not item:
        return not_found_error(
            message=f"Template with ID '{template_id}' not found.",
            details={"resource_type": "template", "resource_id": template_id},
            request_id=request_id,
        )

    return success_response(body={"template": _format_template(item)})


# ─── List Templates ───────────────────────────────────────────────────────


def _list_templates(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List all templates with pagination.

    Supports filtering by catalogId via query string.
    """
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    params = event.get("queryStringParameters") or {}
    catalog_id = params.get("catalogId") or params.get("catalog_id") or ""
    pagination = PaginationParams.from_event(event)

    db = DynamoHelper(TEMPLATES_TABLE)

    if catalog_id:
        # Query templates associated with a catalog from the catalogs table
        from boto3.dynamodb.conditions import Key
        catalogs_db = DynamoHelper(CATALOGS_TABLE)
        result = catalogs_db.query(
            pk_value=f"CATALOG#{catalog_id}",
            sk_condition=Key("SK").begins_with("TEMPLATE#"),
            pagination=pagination,
        )
        # The association items don't have full template data, fetch templates
        items = []
        for assoc in result.get("items", []):
            tid = assoc.get("template_id", "")
            if tid:
                template_item = db.get_item(pk=f"TEMPLATE#{tid}", sk="METADATA")
                if template_item:
                    items.append(_format_template(template_item))
        next_token = result.get("next_token")
        total_count = result.get("count", len(items))
    else:
        # Scan all templates
        from boto3.dynamodb.conditions import Attr
        result = db.scan(
            filter_expression=Attr("SK").eq("METADATA"),
            pagination=pagination,
        )
        items = [_format_template(item) for item in result.get("items", [])]
        next_token = result.get("next_token")
        total_count = result.get("count", len(items))

    return success_response(
        body=paginate_response(
            items=items,
            total_count=total_count,
            page_size=pagination.page_size,
            next_token=next_token,
        )
    )


# ─── Update Template ──────────────────────────────────────────────────────


def _update_template(
    event: dict[str, Any], template_id: str, request_id: str
) -> dict[str, Any]:
    """Update a template. AdminDatos only.

    Updatable fields: name, description, fields list.
    """
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required.",
            request_id=request_id,
        )

    db = DynamoHelper(TEMPLATES_TABLE)
    existing = db.get_item(pk=f"TEMPLATE#{template_id}", sk="METADATA")
    if not existing:
        return not_found_error(
            message=f"Template with ID '{template_id}' not found.",
            details={"resource_type": "template", "resource_id": template_id},
            request_id=request_id,
        )

    # Build update
    now = datetime.now(timezone.utc).isoformat()
    updated_item = dict(existing)
    updated_item["updated_at"] = now
    changes: dict[str, Any] = {}

    if "name" in body:
        name = body["name"].strip() if body["name"] else ""
        if not name:
            return validation_error(message="Name cannot be empty.", request_id=request_id)
        if len(name) > MAX_NAME_LENGTH:
            return validation_error(
                message=f"Name must not exceed {MAX_NAME_LENGTH} characters.",
                request_id=request_id,
            )
        updated_item["name"] = name
        changes["name"] = name

    if "description" in body:
        description = body["description"].strip() if body["description"] else ""
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return validation_error(
                message=f"Description must not exceed {MAX_DESCRIPTION_LENGTH} characters.",
                request_id=request_id,
            )
        updated_item["description"] = description
        changes["description"] = description

    if "fields" in body:
        fields = body["fields"]
        if not isinstance(fields, list):
            return validation_error(message="Fields must be a list.", request_id=request_id)

        validated_fields = []
        for i, field in enumerate(fields):
            field_error = _validate_template_field(field, i)
            if field_error:
                return validation_error(message=field_error, request_id=request_id)
            validated_fields.append({
                "field_name": field["field_name"].strip(),
                "field_type": field["field_type"].strip().lower(),
                "required": bool(field.get("required", False)),
            })

        updated_item["fields"] = validated_fields
        updated_item["field_count"] = len(validated_fields)
        changes["fields"] = validated_fields

    if not changes:
        return validation_error(
            message="At least one field (name, description, or fields) must be provided for update.",
            request_id=request_id,
        )

    # Write updated item with audit
    try:
        write_with_audit(
            operation_item=updated_item,
            operation_table=TEMPLATES_TABLE,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="update",
            resource_type="template",
            resource_id=template_id,
            details={"changes": list(changes.keys())},
        )
    except Exception as e:
        logger.error(f"Failed to update template with audit: {e}")
        return internal_error(
            message="Failed to update template.",
            request_id=request_id,
        )

    return success_response(
        body={"message": "Template updated.", "template": _format_template(updated_item)}
    )


# ─── Delete Template ──────────────────────────────────────────────────────


def _delete_template(
    event: dict[str, Any], template_id: str, request_id: str
) -> dict[str, Any]:
    """Delete a template. AdminDatos only."""
    claims, error_response = require_role(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    db = DynamoHelper(TEMPLATES_TABLE)
    existing = db.get_item(pk=f"TEMPLATE#{template_id}", sk="METADATA")
    if not existing:
        return not_found_error(
            message=f"Template with ID '{template_id}' not found.",
            details={"resource_type": "template", "resource_id": template_id},
            request_id=request_id,
        )

    # Delete with audit
    delete_key = {"PK": f"TEMPLATE#{template_id}", "SK": "METADATA"}
    try:
        write_with_audit(
            operation_item=delete_key,
            operation_table=TEMPLATES_TABLE,
            operation_type="Delete",
            user_id=claims.user_id,
            action_type="delete",
            resource_type="template",
            resource_id=template_id,
            details={"name": existing.get("name", "")},
        )
    except Exception as e:
        logger.error(f"Failed to delete template with audit: {e}")
        return internal_error(
            message="Failed to delete template.",
            request_id=request_id,
        )

    # Remove catalog association if exists
    catalog_id = existing.get("catalog_id", "")
    if catalog_id:
        try:
            catalogs_db = DynamoHelper(CATALOGS_TABLE)
            catalogs_db.delete_item(pk=f"CATALOG#{catalog_id}", sk=f"TEMPLATE#{template_id}")
        except Exception as e:
            logger.warning(f"Failed to remove catalog-template association: {e}")

    return success_response(
        body={"message": f"Template '{template_id}' deleted successfully."},
        status_code=200,
    )


# ─── Validation ───────────────────────────────────────────────────────────


def _validate_template_field(field: Any, index: int) -> Optional[str]:
    """Validate a single field definition in a template.

    Each field must have:
    - field_name: non-empty string
    - field_type: one of string/number/date/boolean
    - required: optional boolean

    Args:
        field: The field dict to validate.
        index: The position in the fields list (for error messages).

    Returns:
        Error message string if invalid, None if valid.
    """
    if not isinstance(field, dict):
        return f"Field at index {index} must be an object."

    field_name = field.get("field_name", "").strip() if field.get("field_name") else ""
    if not field_name:
        return f"Field at index {index}: 'field_name' is required."

    field_type = field.get("field_type", "").strip().lower() if field.get("field_type") else ""
    if not field_type:
        return f"Field at index {index}: 'field_type' is required."

    if field_type not in VALID_FIELD_TYPES:
        return (
            f"Field at index {index}: invalid field_type '{field_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}"
        )

    return None


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


def _extract_template_id(path: str) -> str:
    """Extract template ID from path like /templates/{id}."""
    parts = [p for p in path.strip("/").split("/") if p]
    try:
        idx = parts.index("templates")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return ""


def _format_template(item: dict[str, Any]) -> dict[str, Any]:
    """Format a template item for API response (strip internal keys)."""
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "fields": item.get("fields", []),
        "catalogId": item.get("catalog_id", ""),
        "fieldCount": item.get("field_count", 0),
        "createdAt": item.get("created_at", ""),
        "updatedAt": item.get("updated_at", ""),
        "createdBy": item.get("created_by", ""),
    }
