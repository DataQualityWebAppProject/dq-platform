"""Validation Results Lambda handler.

Handles HTTP API routes for querying validation results:
- GET /validations              → list validation runs (paginated, sorted by date desc)
- GET /validations/{id}         → get run details + summary
- GET /validations/{id}/results → per-record results (paginated)

DynamoDB Tables: dq-validation-runs, dq-validation-results

Requirements: 10.3, 11.1, 11.4, 11.5, 11.6
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from boto3.dynamodb.conditions import Key, Attr

from services.shared.auth import (
    extract_user_claims,
    get_request_id,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    internal_error,
    not_found_error,
    success_response,
    validation_error,
    unauthorized_error,
)
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
VALIDATION_RUNS_TABLE = os.environ.get("VALIDATION_RUNS_TABLE", "dq-validation-runs")
VALIDATION_RESULTS_TABLE = os.environ.get("VALIDATION_RESULTS_TABLE", "dq-validation-results")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for validation results queries.

    Routes:
    - GET /validations              → list runs
    - GET /validations/{id}         → get run details
    - GET /validations/{id}/results → per-record results

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

        if http_method != "GET":
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

        # Parse path
        run_id, is_results_path = _parse_path(path)

        if run_id and is_results_path:
            return _get_run_results(event, run_id, request_id)
        elif run_id:
            return _get_run_details(event, run_id, request_id)
        else:
            return _list_validation_runs(event, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in validation results handler: {e}")
        return internal_error(
            message="An unexpected error occurred while querying validation results.",
            request_id=request_id,
        )


def _parse_path(path: str) -> tuple[Optional[str], bool]:
    """Parse the request path to extract run ID and determine if results sub-path.

    Args:
        path: The raw request path.

    Returns:
        Tuple of (run_id, is_results_path).
    """
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # /validations/{id}/results
    if len(parts) >= 3 and parts[0] == "validations" and parts[2] == "results":
        return parts[1], True

    # /validations/{id}
    if len(parts) >= 2 and parts[0] == "validations":
        return parts[1], False

    # /validations
    return None, False


def _list_validation_runs(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List validation runs, paginated and sorted by date descending.

    Supports query params:
    - pageSize: items per page (default 20, max 100)
    - nextToken: pagination cursor
    - datasetId: filter by dataset
    - status: filter by status (running, completed, failed)

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Paginated list of validation runs.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    pagination = PaginationParams.from_event(event, default_page_size=20, max_page_size=100)
    params = event.get("queryStringParameters") or {}
    filter_dataset = params.get("datasetId")
    filter_status = params.get("status")

    db = DynamoHelper(VALIDATION_RUNS_TABLE)

    # Build filter expression
    filter_expr = Attr("SK").eq("METADATA")
    if filter_dataset:
        filter_expr = filter_expr & Attr("datasetId").eq(filter_dataset)
    if filter_status:
        filter_expr = filter_expr & Attr("status").eq(filter_status)

    result = db.scan(
        filter_expression=filter_expr,
        pagination=pagination,
    )

    # Sort items by startedAt descending
    items = sorted(
        result.get("items", []),
        key=lambda x: x.get("startedAt", ""),
        reverse=True,
    )

    formatted_items = [_format_run_summary(item) for item in items]

    response_body = paginate_response(
        items=formatted_items,
        total_count=result.get("count", len(formatted_items)),
        page_size=pagination.page_size,
        next_token=result.get("next_token"),
    )

    return success_response(response_body)


def _get_run_details(
    event: dict[str, Any], run_id: str, request_id: str
) -> dict[str, Any]:
    """Get validation run details and summary.

    Args:
        event: API Gateway event.
        run_id: The validation run ID.
        request_id: The request ID.

    Returns:
        Run details with summary statistics.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    db = DynamoHelper(VALIDATION_RUNS_TABLE)
    item = db.get_item(pk=f"VALIDATION#{run_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Validation run '{run_id}' not found.",
            details={"runId": run_id},
            request_id=request_id,
        )

    response_body = _format_run_detail(item)
    return success_response(response_body)


def _get_run_results(
    event: dict[str, Any], run_id: str, request_id: str
) -> dict[str, Any]:
    """Get per-record results for a validation run (paginated).

    Args:
        event: API Gateway event.
        run_id: The validation run ID.
        request_id: The request ID.

    Returns:
        Paginated per-record validation results.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Verify run exists
    runs_db = DynamoHelper(VALIDATION_RUNS_TABLE)
    run_item = runs_db.get_item(pk=f"VALIDATION#{run_id}", sk="METADATA")
    if run_item is None:
        return not_found_error(
            message=f"Validation run '{run_id}' not found.",
            details={"runId": run_id},
            request_id=request_id,
        )

    # Query per-record results
    pagination = PaginationParams.from_event(event, default_page_size=20, max_page_size=100)
    results_db = DynamoHelper(VALIDATION_RESULTS_TABLE)

    result = results_db.query(
        pk_value=f"RUN#{run_id}",
        pagination=pagination,
        scan_forward=True,
    )

    formatted_items = [_format_record_result(item) for item in result.get("items", [])]

    response_body = paginate_response(
        items=formatted_items,
        total_count=result.get("count", len(formatted_items)),
        page_size=pagination.page_size,
        next_token=result.get("next_token"),
    )

    return success_response(response_body)


def _format_run_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Format a validation run item for list view."""
    return {
        "id": item.get("id"),
        "datasetId": item.get("datasetId"),
        "status": item.get("status"),
        "score": item.get("score"),
        "rulesCount": item.get("rulesCount"),
        "startedAt": item.get("startedAt"),
        "completedAt": item.get("completedAt"),
        "triggeredBy": item.get("triggeredBy"),
    }


def _format_run_detail(item: dict[str, Any]) -> dict[str, Any]:
    """Format a validation run item for detail view."""
    return {
        "id": item.get("id"),
        "datasetId": item.get("datasetId"),
        "datasetS3Path": item.get("datasetS3Path"),
        "status": item.get("status"),
        "score": item.get("score"),
        "rulesCount": item.get("rulesCount"),
        "ruleIds": item.get("ruleIds", []),
        "startedAt": item.get("startedAt"),
        "completedAt": item.get("completedAt"),
        "triggeredBy": item.get("triggeredBy"),
        "glueJobRunId": item.get("glueJobRunId"),
        "errorMessage": item.get("errorMessage"),
        "summary": item.get("summary", {}),
    }


def _format_record_result(item: dict[str, Any]) -> dict[str, Any]:
    """Format a per-record validation result."""
    return {
        "recordId": item.get("recordId"),
        "ruleId": item.get("ruleId"),
        "ruleName": item.get("ruleName"),
        "passed": item.get("passed"),
        "message": item.get("message", ""),
        "fieldValues": item.get("fieldValues", {}),
        "evaluatedAt": item.get("evaluatedAt"),
    }
