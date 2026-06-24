"""Rules CRUD Lambda handler for the Rules Engine Service.

Handles HTTP API routes for rule management:
- POST   /rules           → create_rule (any authenticated user)
- GET    /rules           → list_rules (any authenticated user, unified view)
- GET    /rules/{id}      → get_rule (any authenticated user)
- PUT    /rules/{id}      → update_rule (AdminDatos only)
- DELETE /rules/{id}      → delete_rule (AdminDatos only)

DynamoDB Table: dq-rules
- PK: RULE#{rule_id}
- SK: METADATA
- GSI scope-target-index: PK=scope#catalogId, SK=createdAt
- GSI status-index: PK=status, SK=createdAt

Requirements: 5.3, 5.4, 6.3, 6.4, 7.3, 7.4, 8.1
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
    require_role_check,
)
from services.shared.audit import write_with_audit
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    internal_error,
    not_found_error,
    success_response,
    validation_error,
    forbidden_error,
)
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
RULES_TABLE_NAME = os.environ.get("RULES_TABLE_NAME", "dq-rules")
SCOPE_TARGET_INDEX = "scope-target-index"
STATUS_INDEX = "status-index"

# Validation limits
MAX_NL_LENGTH = 500
MIN_NL_LENGTH = 1

# Valid values
VALID_SCOPES = {"catalog", "table", "column"}
VALID_STATUSES = {"draft", "active", "overridden"}
VALID_TEMPLATE_CATEGORIES = {
    "cross_field",
    "statistical_outlier",
    "multi_record",
    "temporal",
    "pattern",
    "simple",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for rule CRUD operations.

    Routes requests based on HTTP method and path to the appropriate handler.

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)

    try:
        http_method = (
            event.get("requestContext", {}).get("http", {}).get("method", "")
        )
        path = event.get("rawPath", "") or event.get("path", "")

        # Extract rule_id from path if present
        rule_id = _extract_rule_id(path)

        if http_method == "POST" and not rule_id:
            return _create_rule(event, request_id)
        elif http_method == "GET" and rule_id:
            return _get_rule(event, rule_id, request_id)
        elif http_method == "GET" and not rule_id:
            return _list_rules(event, request_id)
        elif http_method == "PUT" and rule_id:
            return _update_rule(event, rule_id, request_id)
        elif http_method == "DELETE" and rule_id:
            return _delete_rule(event, rule_id, request_id)
        else:
            return validation_error(
                message=f"Unsupported method or path: {http_method} {path}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in rules handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the rule request.",
            request_id=request_id,
        )


def _extract_rule_id(path: str) -> Optional[str]:
    """Extract rule ID from the request path.

    Expected paths:
    - /rules → None
    - /rules/{id} → id

    Args:
        path: The raw request path.

    Returns:
        The rule ID if present, None otherwise.
    """
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /rules/{id} — ensure it's not a sub-resource like /rules/interpret
    if len(parts) >= 2 and parts[0] == "rules":
        potential_id = parts[1]
        # Skip known sub-paths
        if potential_id in ("interpret", "conflicts", "unified"):
            return None
        return potential_id

    return None


# ─── Create Rule ──────────────────────────────────────────────────────────────


def _create_rule(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Create a new quality rule.

    Required fields:
    - naturalLanguage: 1-500 characters
    - scope: catalog | table | column
    - catalogId: always required

    Conditional fields:
    - tableId: required if scope is 'table' or 'column'
    - columnId: required if scope is 'column'

    Optional fields:
    - structuredJson: parsed rule definition
    - templateCategory: one of the valid categories
    - status: defaults to 'draft'

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with created rule or error.
    """
    # Any authenticated user can create rules
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

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

    # Build rule item
    rule_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()
    scope = body["scope"]

    rule_item: dict[str, Any] = {
        "PK": f"RULE#{rule_id}",
        "SK": "METADATA",
        "id": rule_id,
        "scope": scope,
        "catalogId": body["catalogId"],
        "naturalLanguage": body["naturalLanguage"].strip(),
        "status": body.get("status", "draft"),
        "templateCategory": body.get("templateCategory", "simple"),
        "author": claims.user_id,
        "createdAt": now,
        "updatedAt": now,
        # GSI scope-target-index
        "GSI1PK": f"{scope}#{body['catalogId']}",
        "GSI1SK": now,
        # GSI status-index
        "GSI2PK": body.get("status", "draft"),
        "GSI2SK": now,
    }

    # Add optional scope references
    if scope in ("table", "column"):
        rule_item["tableId"] = body["tableId"]
        rule_item["GSI1PK"] = f"{scope}#{body['tableId']}"

    if scope == "column":
        rule_item["columnId"] = body["columnId"]
        rule_item["GSI1PK"] = f"{scope}#{body['columnId']}"

    # Add structured JSON if provided
    if "structuredJson" in body and body["structuredJson"]:
        rule_item["structuredJson"] = body["structuredJson"]

    # Write with audit (transactional integrity)
    try:
        write_with_audit(
            operation_item=rule_item,
            operation_table=RULES_TABLE_NAME,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="create",
            resource_type="rule",
            resource_id=rule_id,
            details={
                "scope": scope,
                "catalogId": body["catalogId"],
                "naturalLanguage": body["naturalLanguage"][:100],
            },
        )
    except Exception as e:
        logger.error(f"Failed to create rule with audit: {e}")
        return internal_error(
            message="Failed to create rule. The operation could not be completed.",
            request_id=request_id,
        )

    response_body = _format_rule_response(rule_item)
    return success_response(response_body, status_code=201)


def _validate_create_request(body: dict[str, Any]) -> dict[str, str]:
    """Validate the create rule request body.

    Args:
        body: The parsed request body.

    Returns:
        Dict of field name → error message for invalid fields.
    """
    errors: dict[str, str] = {}

    # naturalLanguage: required, 1-500 chars
    nl = body.get("naturalLanguage")
    if not nl or not str(nl).strip():
        errors["naturalLanguage"] = "Natural language rule description is required."
    elif len(str(nl).strip()) < MIN_NL_LENGTH:
        errors["naturalLanguage"] = (
            f"Natural language text must be at least {MIN_NL_LENGTH} character(s)."
        )
    elif len(str(nl).strip()) > MAX_NL_LENGTH:
        errors["naturalLanguage"] = (
            f"Natural language text must not exceed {MAX_NL_LENGTH} characters."
        )

    # scope: required, must be valid
    scope = body.get("scope")
    if not scope:
        errors["scope"] = "Scope is required (catalog, table, or column)."
    elif scope not in VALID_SCOPES:
        errors["scope"] = (
            f"Invalid scope '{scope}'. Must be one of: {', '.join(VALID_SCOPES)}."
        )

    # catalogId: always required
    catalog_id = body.get("catalogId")
    if not catalog_id or not str(catalog_id).strip():
        errors["catalogId"] = "Catalog ID is required."

    # tableId: required if scope is table or column
    if scope in ("table", "column"):
        table_id = body.get("tableId")
        if not table_id or not str(table_id).strip():
            errors["tableId"] = (
                f"Table ID is required for scope '{scope}'."
            )

    # columnId: required if scope is column
    if scope == "column":
        column_id = body.get("columnId")
        if not column_id or not str(column_id).strip():
            errors["columnId"] = "Column ID is required for scope 'column'."

    # templateCategory: optional, but must be valid if provided
    template_category = body.get("templateCategory")
    if template_category and template_category not in VALID_TEMPLATE_CATEGORIES:
        errors["templateCategory"] = (
            f"Invalid template category '{template_category}'. "
            f"Must be one of: {', '.join(VALID_TEMPLATE_CATEGORIES)}."
        )

    # status: optional, but must be valid if provided
    status = body.get("status")
    if status and status not in VALID_STATUSES:
        errors["status"] = (
            f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}."
        )

    return errors


# ─── Get Rule by ID ───────────────────────────────────────────────────────────


def _get_rule(
    event: dict[str, Any], rule_id: str, request_id: str
) -> dict[str, Any]:
    """Get a rule by ID (any authenticated user).

    Args:
        event: API Gateway event.
        rule_id: The rule ID to retrieve.
        request_id: The request ID.

    Returns:
        API Gateway response with rule data or error.
    """
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    db = DynamoHelper(RULES_TABLE_NAME)
    item = db.get_item(pk=f"RULE#{rule_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Rule with ID '{rule_id}' not found.",
            details={"ruleId": rule_id},
            request_id=request_id,
        )

    response_body = _format_rule_response(item)
    return success_response(response_body)


# ─── List Rules (Unified View) ────────────────────────────────────────────────


def _list_rules(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List rules with pagination, organized by hierarchy level.

    Supports filtering by:
    - scope: catalog | table | column
    - status: draft | active | overridden
    - catalogId: filter by catalog
    - tableId: filter by table

    Pagination: default 20, max 100 items per page.

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with paginated rule list organized by hierarchy.
    """
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    pagination = PaginationParams.from_event(event)
    params = event.get("queryStringParameters") or {}

    filter_scope = params.get("scope")
    filter_status = params.get("status")
    filter_catalog_id = params.get("catalogId")
    filter_table_id = params.get("tableId")

    db = DynamoHelper(RULES_TABLE_NAME)

    # Build filter expression
    from boto3.dynamodb.conditions import Attr

    filter_expr = Attr("SK").eq("METADATA")

    if filter_scope and filter_scope in VALID_SCOPES:
        filter_expr = filter_expr & Attr("scope").eq(filter_scope)

    if filter_status and filter_status in VALID_STATUSES:
        filter_expr = filter_expr & Attr("status").eq(filter_status)

    if filter_catalog_id:
        filter_expr = filter_expr & Attr("catalogId").eq(filter_catalog_id)

    if filter_table_id:
        filter_expr = filter_expr & Attr("tableId").eq(filter_table_id)

    # Scan with filters (for unified view across all rules)
    result = db.scan(
        filter_expression=filter_expr,
        pagination=pagination,
    )

    # Format and organize by hierarchy
    items = [_format_rule_response(item) for item in result["items"]]

    # Sort by hierarchy: catalog → table → column, then by createdAt desc
    scope_order = {"catalog": 0, "table": 1, "column": 2}
    items.sort(key=lambda r: (scope_order.get(r.get("scope", ""), 99), r.get("createdAt", "")))

    response_body = paginate_response(
        items=items,
        total_count=result.get("total_count", result["count"]),
        page_size=pagination.page_size,
        next_token=result.get("next_token"),
    )

    return success_response(response_body)


# ─── Update Rule ──────────────────────────────────────────────────────────────


def _update_rule(
    event: dict[str, Any], rule_id: str, request_id: str
) -> dict[str, Any]:
    """Update a rule (AdminDatos only).

    Updatable fields: naturalLanguage, structuredJson, status, templateCategory.

    Args:
        event: API Gateway event.
        rule_id: The rule ID to update.
        request_id: The request ID.

    Returns:
        API Gateway response with updated rule or error.
    """
    # Authorization: AdminDatos only
    claims, error_response = require_role_check(event, [ADMIN_ROLE], request_id)
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

    # Check rule exists
    db = DynamoHelper(RULES_TABLE_NAME)
    existing = db.get_item(pk=f"RULE#{rule_id}", sk="METADATA")
    if existing is None:
        return not_found_error(
            message=f"Rule with ID '{rule_id}' not found.",
            details={"ruleId": rule_id},
            request_id=request_id,
        )

    # Build updated item
    now = datetime.now(timezone.utc).isoformat()
    updated_item = dict(existing)
    updated_item["updatedAt"] = now

    changes: dict[str, Any] = {}

    if "naturalLanguage" in body and body["naturalLanguage"] is not None:
        updated_item["naturalLanguage"] = body["naturalLanguage"].strip()
        changes["naturalLanguage"] = updated_item["naturalLanguage"][:100]

    if "structuredJson" in body and body["structuredJson"] is not None:
        updated_item["structuredJson"] = body["structuredJson"]
        changes["structuredJson"] = "updated"

    if "status" in body and body["status"] is not None:
        updated_item["status"] = body["status"]
        updated_item["GSI2PK"] = body["status"]
        changes["status"] = body["status"]

    if "templateCategory" in body and body["templateCategory"] is not None:
        updated_item["templateCategory"] = body["templateCategory"]
        changes["templateCategory"] = body["templateCategory"]

    if not changes:
        return validation_error(
            message="At least one field must be provided for update.",
            request_id=request_id,
        )

    # Write with audit
    try:
        write_with_audit(
            operation_item=updated_item,
            operation_table=RULES_TABLE_NAME,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="update",
            resource_type="rule",
            resource_id=rule_id,
            details={"changes": changes},
        )
    except Exception as e:
        logger.error(f"Failed to update rule with audit: {e}")
        return internal_error(
            message="Failed to update rule. The operation could not be completed.",
            request_id=request_id,
        )

    response_body = _format_rule_response(updated_item)
    return success_response(response_body)


def _validate_update_request(body: dict[str, Any]) -> dict[str, str]:
    """Validate the update rule request body.

    Args:
        body: The parsed request body.

    Returns:
        Dict of field name → error message for invalid fields.
    """
    errors: dict[str, str] = {}

    # naturalLanguage: optional, but if provided must be valid
    nl = body.get("naturalLanguage")
    if nl is not None:
        if not str(nl).strip():
            errors["naturalLanguage"] = "Natural language text cannot be empty."
        elif len(str(nl).strip()) > MAX_NL_LENGTH:
            errors["naturalLanguage"] = (
                f"Natural language text must not exceed {MAX_NL_LENGTH} characters."
            )

    # status: optional, must be valid
    status = body.get("status")
    if status is not None and status not in VALID_STATUSES:
        errors["status"] = (
            f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}."
        )

    # templateCategory: optional, must be valid
    template_category = body.get("templateCategory")
    if template_category is not None and template_category not in VALID_TEMPLATE_CATEGORIES:
        errors["templateCategory"] = (
            f"Invalid template category '{template_category}'. "
            f"Must be one of: {', '.join(VALID_TEMPLATE_CATEGORIES)}."
        )

    return errors


# ─── Delete Rule ──────────────────────────────────────────────────────────────


def _delete_rule(
    event: dict[str, Any], rule_id: str, request_id: str
) -> dict[str, Any]:
    """Delete a rule (AdminDatos only).

    Args:
        event: API Gateway event.
        rule_id: The rule ID to delete.
        request_id: The request ID.

    Returns:
        API Gateway response confirming deletion or error.
    """
    # Authorization: AdminDatos only
    claims, error_response = require_role_check(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Check rule exists
    db = DynamoHelper(RULES_TABLE_NAME)
    existing = db.get_item(pk=f"RULE#{rule_id}", sk="METADATA")
    if existing is None:
        return not_found_error(
            message=f"Rule with ID '{rule_id}' not found.",
            details={"ruleId": rule_id},
            request_id=request_id,
        )

    # Delete with audit
    delete_key = {
        "PK": f"RULE#{rule_id}",
        "SK": "METADATA",
    }

    try:
        write_with_audit(
            operation_item=delete_key,
            operation_table=RULES_TABLE_NAME,
            operation_type="Delete",
            user_id=claims.user_id,
            action_type="delete",
            resource_type="rule",
            resource_id=rule_id,
            details={
                "scope": existing.get("scope"),
                "naturalLanguage": existing.get("naturalLanguage", "")[:100],
            },
        )
    except Exception as e:
        logger.error(f"Failed to delete rule with audit: {e}")
        return internal_error(
            message="Failed to delete rule. The operation could not be completed.",
            request_id=request_id,
        )

    return success_response(
        {"message": f"Rule '{rule_id}' deleted successfully."},
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


def _format_rule_response(item: dict[str, Any]) -> dict[str, Any]:
    """Format a DynamoDB rule item for API response.

    Removes internal DynamoDB keys (PK, SK, GSI keys) and returns
    a clean response object.

    Args:
        item: The raw DynamoDB item.

    Returns:
        Formatted rule response dict.
    """
    response: dict[str, Any] = {
        "id": item.get("id"),
        "scope": item.get("scope"),
        "catalogId": item.get("catalogId"),
        "naturalLanguage": item.get("naturalLanguage"),
        "status": item.get("status"),
        "templateCategory": item.get("templateCategory"),
        "author": item.get("author"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
    }

    # Include optional scope references
    if item.get("tableId"):
        response["tableId"] = item["tableId"]
    if item.get("columnId"):
        response["columnId"] = item["columnId"]

    # Include structured JSON if present
    if item.get("structuredJson"):
        response["structuredJson"] = item["structuredJson"]

    # Include generated script key if present
    if item.get("generatedScriptKey"):
        response["generatedScriptKey"] = item["generatedScriptKey"]

    # Include quality score if present
    if item.get("qualityScore") is not None:
        response["qualityScore"] = item["qualityScore"]

    return response
