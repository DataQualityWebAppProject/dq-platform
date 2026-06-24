"""Reports CRUD and Publishing Lambda handler.

Handles HTTP API routes for report management:
- GET    /reports           → list reports (paginated)
- GET    /reports/{id}      → get report content
- PUT    /reports/{id}      → update report (save edits)
- POST   /reports/{id}/publish → publish report with timestamp
- GET    /reports/{id}/versions → get version history

DynamoDB Table: dq-reports
- PK: REPORT#{report_id}
- SK: METADATA (current state) / VERSION#{n} (version history)

Requirements: 16.2, 16.3, 16.4
"""

from __future__ import annotations

import json
import logging
import os
import ulid
from datetime import datetime, timezone
from typing import Any, Optional

from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from services.shared.auth import (
    ADMIN_ROLE,
    ANALYST_ROLE,
    extract_user_claims,
    get_request_id,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    forbidden_error,
    internal_error,
    not_found_error,
    success_response,
    unauthorized_error,
    validation_error,
)
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "dq-reports")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for report CRUD and publishing.

    Routes:
    - GET    /reports              → list reports
    - GET    /reports/{id}         → get report
    - PUT    /reports/{id}         → update report
    - POST   /reports/{id}/publish → publish report
    - GET    /reports/{id}/versions → version history

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

        # Parse path
        report_id, sub_path = _parse_path(path)

        if http_method == "GET" and not report_id:
            return _list_reports(event, request_id)
        elif http_method == "GET" and report_id and sub_path == "versions":
            return _get_versions(event, report_id, request_id)
        elif http_method == "GET" and report_id:
            return _get_report(event, report_id, request_id)
        elif http_method == "PUT" and report_id:
            return _update_report(event, report_id, request_id)
        elif http_method == "POST" and report_id and sub_path == "publish":
            return _publish_report(event, report_id, request_id)
        else:
            return validation_error(
                message=f"Unsupported method or path: {http_method} {path}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in reports handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the report request.",
            request_id=request_id,
        )


def _parse_path(path: str) -> tuple[Optional[str], Optional[str]]:
    """Parse path to extract report ID and sub-path.

    Returns:
        Tuple of (report_id, sub_path).
    """
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # /reports/{id}/versions or /reports/{id}/publish
    if len(parts) >= 3 and parts[0] == "reports":
        return parts[1], parts[2]

    # /reports/{id}
    if len(parts) >= 2 and parts[0] == "reports":
        if parts[1] == "generate":
            return None, None
        return parts[1], None

    # /reports
    return None, None


def _list_reports(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List reports, paginated.

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Paginated list of reports.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    pagination = PaginationParams.from_event(event)
    params = event.get("queryStringParameters") or {}
    filter_status = params.get("status")

    db = DynamoHelper(REPORTS_TABLE)

    filter_expr = Attr("SK").eq("METADATA")
    if filter_status:
        filter_expr = filter_expr & Attr("status").eq(filter_status)

    result = db.scan(filter_expression=filter_expr, pagination=pagination)

    # Sort by createdAt descending
    items = sorted(
        result.get("items", []),
        key=lambda x: x.get("createdAt", ""),
        reverse=True,
    )

    formatted_items = [_format_report_summary(item) for item in items]

    response_body = paginate_response(
        items=formatted_items,
        total_count=result.get("count", len(formatted_items)),
        page_size=pagination.page_size,
        next_token=result.get("next_token"),
    )

    return success_response(response_body)


def _get_report(
    event: dict[str, Any], report_id: str, request_id: str
) -> dict[str, Any]:
    """Get a report by ID.

    Args:
        event: API Gateway event.
        report_id: The report ID.
        request_id: The request ID.

    Returns:
        Report content.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    db = DynamoHelper(REPORTS_TABLE)
    item = db.get_item(pk=f"REPORT#{report_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Report '{report_id}' not found.",
            details={"reportId": report_id},
            request_id=request_id,
        )

    return success_response(_format_report_detail(item))


def _update_report(
    event: dict[str, Any], report_id: str, request_id: str
) -> dict[str, Any]:
    """Update a report (save edits).

    Creates a new version entry for each edit.

    Expected body:
    {
        "content": "...",
        "title": "..." (optional)
    }

    Args:
        event: API Gateway event.
        report_id: The report ID.
        request_id: The request ID.

    Returns:
        Updated report.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role not in [ADMIN_ROLE, ANALYST_ROLE]:
        return forbidden_error(
            message="You do not have permission to edit reports.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required.",
            request_id=request_id,
        )

    content = body.get("content")
    title = body.get("title")

    if not content and not title:
        return validation_error(
            message="At least one of 'content' or 'title' must be provided.",
            request_id=request_id,
        )

    # Fetch existing report
    db = DynamoHelper(REPORTS_TABLE)
    item = db.get_item(pk=f"REPORT#{report_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Report '{report_id}' not found.",
            details={"reportId": report_id},
            request_id=request_id,
        )

    now = datetime.now(timezone.utc).isoformat()
    current_version = int(item.get("version", 1))
    new_version = current_version + 1

    # Update report metadata
    update_expr = "SET updatedAt = :ua, version = :v"
    expr_values: dict[str, Any] = {
        ":ua": now,
        ":v": new_version,
    }

    if content:
        update_expr += ", content = :c"
        expr_values[":c"] = content

    if title:
        update_expr += ", title = :t"
        expr_values[":t"] = title

    try:
        db.update_item(
            pk=f"REPORT#{report_id}",
            sk="METADATA",
            update_expression=update_expr,
            expression_values=expr_values,
        )

        # Store version entry
        version_item = {
            "PK": f"REPORT#{report_id}",
            "SK": f"VERSION#{new_version}",
            "version": new_version,
            "content": content or item.get("content"),
            "title": title or item.get("title"),
            "editedAt": now,
            "editedBy": claims.user_id,
        }
        db.put_item(version_item)

    except ClientError as e:
        logger.error(f"Failed to update report: {e}")
        return internal_error(
            message="Failed to update report.",
            request_id=request_id,
        )

    return success_response({
        "reportId": report_id,
        "version": new_version,
        "updatedAt": now,
        "status": item.get("status"),
    })


def _publish_report(
    event: dict[str, Any], report_id: str, request_id: str
) -> dict[str, Any]:
    """Publish a report with timestamp.

    Sets status to 'published' and records publish timestamp and author.

    Args:
        event: API Gateway event.
        report_id: The report ID.
        request_id: The request ID.

    Returns:
        Published report confirmation.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role != ADMIN_ROLE:
        return forbidden_error(
            message="Only AdminDatos can publish reports.",
            request_id=request_id,
        )

    # Fetch report
    db = DynamoHelper(REPORTS_TABLE)
    item = db.get_item(pk=f"REPORT#{report_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Report '{report_id}' not found.",
            details={"reportId": report_id},
            request_id=request_id,
        )

    if item.get("status") == "published":
        return validation_error(
            message="Report is already published.",
            details={"reportId": report_id},
            request_id=request_id,
        )

    now = datetime.now(timezone.utc).isoformat()

    try:
        db.update_item(
            pk=f"REPORT#{report_id}",
            sk="METADATA",
            update_expression="SET #s = :s, publishedAt = :pa, publishedBy = :pb, updatedAt = :ua",
            expression_values={
                ":s": "published",
                ":pa": now,
                ":pb": claims.user_id,
                ":ua": now,
            },
            expression_names={"#s": "status"},
        )
    except ClientError as e:
        logger.error(f"Failed to publish report: {e}")
        return internal_error(
            message="Failed to publish report.",
            request_id=request_id,
        )

    return success_response({
        "reportId": report_id,
        "status": "published",
        "publishedAt": now,
        "publishedBy": claims.user_id,
    })


def _get_versions(
    event: dict[str, Any], report_id: str, request_id: str
) -> dict[str, Any]:
    """Get version history for a report.

    Args:
        event: API Gateway event.
        report_id: The report ID.
        request_id: The request ID.

    Returns:
        List of version entries.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    db = DynamoHelper(REPORTS_TABLE)

    # Verify report exists
    item = db.get_item(pk=f"REPORT#{report_id}", sk="METADATA")
    if item is None:
        return not_found_error(
            message=f"Report '{report_id}' not found.",
            details={"reportId": report_id},
            request_id=request_id,
        )

    # Query all VERSION# entries
    result = db.query(
        pk_value=f"REPORT#{report_id}",
        sk_condition=Key("SK").begins_with("VERSION#"),
        scan_forward=False,  # Most recent first
    )

    versions = [
        {
            "version": v.get("version"),
            "editedAt": v.get("editedAt"),
            "editedBy": v.get("editedBy"),
        }
        for v in result.get("items", [])
    ]

    return success_response({
        "reportId": report_id,
        "currentVersion": item.get("version"),
        "versions": versions,
    })


def _format_report_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Format report item for list view."""
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "status": item.get("status"),
        "reportType": item.get("reportType"),
        "version": item.get("version"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "publishedAt": item.get("publishedAt"),
        "createdBy": item.get("createdBy"),
    }


def _format_report_detail(item: dict[str, Any]) -> dict[str, Any]:
    """Format report item for detail view."""
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "content": item.get("content"),
        "status": item.get("status"),
        "reportType": item.get("reportType"),
        "datasetId": item.get("datasetId"),
        "version": item.get("version"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "createdBy": item.get("createdBy"),
        "publishedAt": item.get("publishedAt"),
        "publishedBy": item.get("publishedBy"),
    }


def _parse_body(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse JSON body from API Gateway event."""
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
