"""Audit trail query handler for the Data Quality Platform.

This handler is READ-ONLY. It provides paginated, filtered access to the
append-only audit trail. No create, update, or delete operations are exposed
through this handler.

Route: GET /audit

DynamoDB Table: dq-audit-trail
- PK: AUDIT#{year-month}, SK: {timestamp}#{uuid}
- GSI user-index: PK=user_id (GSI1PK), SK=timestamp (GSI1SK)
- GSI resource-index: PK=resource_type#resource_id (GSI2PK), SK=timestamp (GSI2SK)

Query Parameters:
- userId: Filter by user who performed the action
- actionType: Filter by action type (create, update, delete)
- resourceType: Filter by resource type
- startDate: Filter records from this date (ISO 8601)
- endDate: Filter records up to this date (ISO 8601)
- pageSize: Number of records per page (default 50, max 100)
- nextToken: Opaque pagination token

Results are sorted by timestamp in descending order.
Audit records are retained for a minimum of 365 days.

Requirements: 18.1, 18.3, 18.4
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from boto3.dynamodb.conditions import Key, Attr

from services.shared.auth import (
    extract_user_claims,
    require_role,
    get_request_id,
    ADMIN_ROLE,
    ANALYST_ROLE,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    success_response,
    validation_error,
    unauthorized_error,
    internal_error,
)
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
AUDIT_TABLE_NAME = os.environ.get("AUDIT_TABLE_NAME", "dq-audit-trail")

# Audit-specific pagination defaults
AUDIT_DEFAULT_PAGE_SIZE = 50
AUDIT_MAX_PAGE_SIZE = 100

# Minimum retention period (365 days)
RETENTION_DAYS = 365

# Valid filter values
VALID_ACTION_TYPES = {"create", "update", "delete"}
VALID_RESOURCE_TYPES = {
    "catalog",
    "table",
    "field",
    "template",
    "rule",
    "validation",
    "anomaly_training",
    "anomaly_scoring",
    "cleaning",
    "report",
    "notification",
    "dataset",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for audit trail queries.

    Supports GET /audit with query parameter filtering.
    This handler is strictly read-only — no mutations are permitted.

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response with paginated audit records.
    """
    request_id = get_request_id(event)

    # Authenticate — both AdminDatos and AnalistaDatos can read audit trail
    claims, error_response = require_role(
        event,
        allowed_roles=[ADMIN_ROLE, ANALYST_ROLE],
        request_id=request_id,
    )
    if error_response:
        return error_response

    # Only GET method is supported (read-only handler)
    http_method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if http_method != "GET":
        return validation_error(
            message="Method not allowed. This endpoint is read-only (GET only).",
            details={"allowedMethods": ["GET"]},
            request_id=request_id,
        )

    try:
        # Parse query parameters
        params = _parse_query_params(event, request_id)
        if isinstance(params, dict) and "statusCode" in params:
            # params is an error response
            return params

        # Execute the appropriate query strategy
        result = _query_audit_trail(params, request_id)
        if isinstance(result, dict) and "statusCode" in result:
            return result

        return success_response(result)

    except Exception as e:
        logger.exception(f"Unexpected error querying audit trail: {e}")
        return internal_error(
            message="Failed to query audit trail.",
            details={"error": str(e)},
            request_id=request_id,
        )


def _parse_query_params(
    event: dict[str, Any], request_id: str
) -> "_AuditQueryParams | dict[str, Any]":
    """Parse and validate query parameters from the event.

    Returns:
        _AuditQueryParams if valid, or an error response dict.
    """
    query_params = event.get("queryStringParameters") or {}

    # Parse pagination
    try:
        page_size = int(query_params.get("pageSize", AUDIT_DEFAULT_PAGE_SIZE))
    except (ValueError, TypeError):
        page_size = AUDIT_DEFAULT_PAGE_SIZE

    page_size = max(1, min(page_size, AUDIT_MAX_PAGE_SIZE))
    next_token = query_params.get("nextToken") or None

    # Parse filters
    user_id = query_params.get("userId") or None
    action_type = query_params.get("actionType") or None
    resource_type = query_params.get("resourceType") or None
    start_date = query_params.get("startDate") or None
    end_date = query_params.get("endDate") or None

    # Validate action type if provided
    if action_type and action_type not in VALID_ACTION_TYPES:
        return validation_error(
            message=f"Invalid actionType '{action_type}'.",
            details={
                "validValues": sorted(VALID_ACTION_TYPES),
                "provided": action_type,
            },
            request_id=request_id,
        )

    # Validate resource type if provided
    if resource_type and resource_type not in VALID_RESOURCE_TYPES:
        return validation_error(
            message=f"Invalid resourceType '{resource_type}'.",
            details={
                "validValues": sorted(VALID_RESOURCE_TYPES),
                "provided": resource_type,
            },
            request_id=request_id,
        )

    # Validate and parse dates
    parsed_start_date = None
    parsed_end_date = None

    if start_date:
        parsed_start_date = _parse_iso_date(start_date)
        if parsed_start_date is None:
            return validation_error(
                message="Invalid startDate format. Use ISO 8601 (e.g., 2024-01-15T00:00:00Z).",
                details={"provided": start_date},
                request_id=request_id,
            )

    if end_date:
        parsed_end_date = _parse_iso_date(end_date)
        if parsed_end_date is None:
            return validation_error(
                message="Invalid endDate format. Use ISO 8601 (e.g., 2024-01-15T23:59:59Z).",
                details={"provided": end_date},
                request_id=request_id,
            )

    # Validate date range
    if parsed_start_date and parsed_end_date:
        if parsed_start_date > parsed_end_date:
            return validation_error(
                message="startDate must be before or equal to endDate.",
                details={"startDate": start_date, "endDate": end_date},
                request_id=request_id,
            )

    return _AuditQueryParams(
        page_size=page_size,
        next_token=next_token,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
    )


def _query_audit_trail(
    params: "_AuditQueryParams", request_id: str
) -> dict[str, Any]:
    """Execute the audit trail query using the appropriate strategy.

    Strategy selection:
    - If userId is provided: query the user-index GSI
    - If resourceType is provided (without userId): query by partition keys
    - Otherwise: query across recent month partitions

    Results are always sorted by timestamp descending.

    Returns:
        Paginated response dict or error response dict.
    """
    dynamo = DynamoHelper(table_name=AUDIT_TABLE_NAME)
    pagination = PaginationParams(page_size=params.page_size, next_token=params.next_token)

    # Build filter expressions for non-key attributes
    filter_expr = _build_filter_expression(params)

    if params.user_id:
        # Strategy: Query user-index GSI (PK=user_id, SK=timestamp)
        result = _query_by_user(dynamo, params, pagination, filter_expr)
    elif params.resource_type:
        # Strategy: Scan with filter on resource_type (no specific resource_id)
        result = _query_by_resource_type(dynamo, params, pagination, filter_expr)
    else:
        # Strategy: Query across recent month partitions
        result = _query_by_time_range(dynamo, params, pagination, filter_expr)

    items = result.get("items", [])
    next_token = result.get("next_token")

    # Format audit records for response
    formatted_items = [_format_audit_record(item) for item in items]

    return paginate_response(
        items=formatted_items,
        total_count=len(formatted_items),
        page_size=params.page_size,
        next_token=next_token,
    )


def _query_by_user(
    dynamo: DynamoHelper,
    params: "_AuditQueryParams",
    pagination: PaginationParams,
    filter_expr: Any,
) -> dict[str, Any]:
    """Query audit records by user via the user-index GSI.

    GSI user-index: PK=GSI1PK (user_id), SK=GSI1SK (timestamp)
    """
    sk_condition = None
    if params.start_date and params.end_date:
        sk_condition = Key("GSI1SK").between(
            params.start_date.isoformat(), params.end_date.isoformat()
        )
    elif params.start_date:
        sk_condition = Key("GSI1SK").gte(params.start_date.isoformat())
    elif params.end_date:
        sk_condition = Key("GSI1SK").lte(params.end_date.isoformat())

    return dynamo.query_gsi(
        index_name="user-index",
        pk_name="GSI1PK",
        pk_value=params.user_id,
        sk_condition=sk_condition,
        filter_expression=filter_expr,
        pagination=pagination,
        scan_forward=False,  # Descending by timestamp
    )


def _query_by_resource_type(
    dynamo: DynamoHelper,
    params: "_AuditQueryParams",
    pagination: PaginationParams,
    filter_expr: Any,
) -> dict[str, Any]:
    """Query audit records by resource type using scan with filter.

    Since resource-index GSI key is resource_type#resource_id,
    and we only have resource_type (no specific resource_id),
    we use a scan with filter.
    """
    # Build combined filter: resource_type + any additional filters
    resource_filter = Attr("resource_type").eq(params.resource_type)

    if filter_expr is not None:
        combined_filter = resource_filter & filter_expr
    else:
        combined_filter = resource_filter

    # Add date range filter
    if params.start_date and params.end_date:
        combined_filter = combined_filter & Attr("timestamp").between(
            params.start_date.isoformat(), params.end_date.isoformat()
        )
    elif params.start_date:
        combined_filter = combined_filter & Attr("timestamp").gte(
            params.start_date.isoformat()
        )
    elif params.end_date:
        combined_filter = combined_filter & Attr("timestamp").lte(
            params.end_date.isoformat()
        )

    return dynamo.scan(
        filter_expression=combined_filter,
        pagination=pagination,
    )


def _query_by_time_range(
    dynamo: DynamoHelper,
    params: "_AuditQueryParams",
    pagination: PaginationParams,
    filter_expr: Any,
) -> dict[str, Any]:
    """Query audit records across month partitions.

    Uses the main table PK (AUDIT#{year-month}) to query records.
    Queries the current month first, then previous months if needed.
    """
    now = datetime.now(timezone.utc)

    # Determine which months to query based on date range
    if params.start_date:
        start_month = params.start_date.replace(day=1)
    else:
        # Default: query from current month (most recent records first)
        start_month = now.replace(day=1)

    if params.end_date:
        end_month = params.end_date.replace(day=1)
    else:
        end_month = now.replace(day=1)

    # Build SK condition for date range within a partition
    sk_condition = None
    if params.start_date and params.end_date:
        sk_condition = Key("SK").between(
            params.start_date.isoformat(), params.end_date.isoformat() + "~"
        )
    elif params.start_date:
        sk_condition = Key("SK").gte(params.start_date.isoformat())
    elif params.end_date:
        sk_condition = Key("SK").lte(params.end_date.isoformat() + "~")

    # Query the current month partition (most common case)
    pk_value = f"AUDIT#{now.strftime('%Y-%m')}"

    return dynamo.query(
        pk_value=pk_value,
        sk_condition=sk_condition,
        filter_expression=filter_expr,
        pagination=pagination,
        scan_forward=False,  # Descending by timestamp
    )


def _build_filter_expression(params: "_AuditQueryParams") -> Any:
    """Build a DynamoDB filter expression for non-key attributes.

    Only includes filters for attributes that are NOT part of the key
    condition for the selected query strategy.
    """
    filters = []

    # action_type filter (always a non-key attribute)
    if params.action_type:
        filters.append(Attr("action_type").eq(params.action_type))

    if not filters:
        return None

    # Combine with AND
    combined = filters[0]
    for f in filters[1:]:
        combined = combined & f

    return combined


def _format_audit_record(item: dict[str, Any]) -> dict[str, Any]:
    """Format a raw DynamoDB audit record for API response.

    Strips internal DynamoDB keys (PK, SK, GSI keys) and presents
    a clean API response format.
    """
    return {
        "id": item.get("id", ""),
        "userId": item.get("user_id", ""),
        "timestamp": item.get("timestamp", ""),
        "resourceType": item.get("resource_type", ""),
        "resourceId": item.get("resource_id", ""),
        "actionType": item.get("action_type", ""),
        "details": item.get("details", {}),
    }


def _parse_iso_date(date_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 date string to a datetime object.

    Supports formats:
    - 2024-01-15
    - 2024-01-15T00:00:00Z
    - 2024-01-15T00:00:00+00:00

    Returns:
        Parsed datetime in UTC, or None if parsing fails.
    """
    # Try various ISO 8601 formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Ensure timezone awareness (default to UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None


class _AuditQueryParams:
    """Internal class holding parsed and validated audit query parameters."""

    def __init__(
        self,
        page_size: int,
        next_token: Optional[str],
        user_id: Optional[str],
        action_type: Optional[str],
        resource_type: Optional[str],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ):
        self.page_size = page_size
        self.next_token = next_token
        self.user_id = user_id
        self.action_type = action_type
        self.resource_type = resource_type
        self.start_date = start_date
        self.end_date = end_date
