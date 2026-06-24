"""Validation Metrics Lambda handler.

Handles HTTP API routes for aggregated validation metrics:
- GET /validations/metrics → aggregated metrics for time range

Computes:
- Average quality score
- Total validation runs
- Pass/fail rate
- Highest and lowest scoring datasets

DynamoDB Table: dq-validation-runs

Requirements: 10.3, 11.1, 11.4, 11.5, 11.6
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from boto3.dynamodb.conditions import Attr

from services.shared.auth import (
    extract_user_claims,
    get_request_id,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    internal_error,
    success_response,
    validation_error,
    unauthorized_error,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
VALIDATION_RUNS_TABLE = os.environ.get("VALIDATION_RUNS_TABLE", "dq-validation-runs")

# Default time range: last 30 days
DEFAULT_LOOKBACK_DAYS = 30


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for validation metrics.

    Routes:
    - GET /validations/metrics → aggregated metrics

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)

    try:
        http_method = event.get("requestContext", {}).get("http", {}).get("method", "")

        if http_method != "GET":
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

        return _get_metrics(event, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in validation metrics handler: {e}")
        return internal_error(
            message="An unexpected error occurred while computing validation metrics.",
            request_id=request_id,
        )


def _get_metrics(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Compute aggregated validation metrics for a time range.

    Query params:
    - startDate: ISO 8601 date (default: 30 days ago)
    - endDate: ISO 8601 date (default: now)

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Aggregated metrics response.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Parse date range params
    params = event.get("queryStringParameters") or {}
    now = datetime.now(timezone.utc)

    end_date = params.get("endDate", now.isoformat())
    start_date = params.get(
        "startDate",
        (now - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat(),
    )

    # Validate date format
    try:
        _parse_iso_date(start_date)
        _parse_iso_date(end_date)
    except ValueError:
        return validation_error(
            message="Invalid date format. Use ISO 8601 (e.g., 2024-01-01T00:00:00Z).",
            details={"startDate": start_date, "endDate": end_date},
            request_id=request_id,
        )

    # Fetch completed validation runs in the date range
    db = DynamoHelper(VALIDATION_RUNS_TABLE)

    filter_expr = (
        Attr("SK").eq("METADATA")
        & Attr("startedAt").gte(start_date)
        & Attr("startedAt").lte(end_date)
        & Attr("status").eq("completed")
    )

    # Scan all matching runs (for metrics computation)
    all_runs: list[dict[str, Any]] = []
    next_token: Optional[str] = None

    while True:
        from services.shared.pagination import PaginationParams
        pagination = PaginationParams(page_size=100, next_token=next_token)
        result = db.scan(filter_expression=filter_expr, pagination=pagination)
        all_runs.extend(result.get("items", []))
        next_token = result.get("next_token")
        if not next_token:
            break

    # Compute metrics
    metrics = _compute_metrics(all_runs, start_date, end_date)

    return success_response(metrics)


def _compute_metrics(
    runs: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Compute aggregated metrics from validation runs.

    Args:
        runs: List of completed validation run items.
        start_date: Start of time range.
        end_date: End of time range.

    Returns:
        Metrics dictionary.
    """
    total_runs = len(runs)

    if total_runs == 0:
        return {
            "timeRange": {"startDate": start_date, "endDate": end_date},
            "totalRuns": 0,
            "averageScore": None,
            "passRate": None,
            "failRate": None,
            "highestScoringDatasets": [],
            "lowestScoringDatasets": [],
        }

    # Calculate scores
    scores = [r.get("score", 0) for r in runs if r.get("score") is not None]
    average_score = round(sum(scores) / len(scores), 2) if scores else 0

    # Pass/fail rate (score >= 80 = pass)
    pass_threshold = 80
    passed = sum(1 for s in scores if s >= pass_threshold)
    failed = len(scores) - passed

    pass_rate = round((passed / len(scores)) * 100, 2) if scores else 0
    fail_rate = round((failed / len(scores)) * 100, 2) if scores else 0

    # Dataset scores aggregation
    dataset_scores: dict[str, list[float]] = {}
    for run in runs:
        dataset_id = run.get("datasetId", "unknown")
        score = run.get("score")
        if score is not None:
            dataset_scores.setdefault(dataset_id, []).append(score)

    # Compute average score per dataset
    dataset_averages = {
        ds_id: round(sum(s_list) / len(s_list), 2)
        for ds_id, s_list in dataset_scores.items()
    }

    # Sort datasets by average score
    sorted_datasets = sorted(dataset_averages.items(), key=lambda x: x[1], reverse=True)

    highest = [
        {"datasetId": ds_id, "averageScore": avg}
        for ds_id, avg in sorted_datasets[:5]
    ]
    lowest = [
        {"datasetId": ds_id, "averageScore": avg}
        for ds_id, avg in sorted_datasets[-5:]
    ] if len(sorted_datasets) > 5 else [
        {"datasetId": ds_id, "averageScore": avg}
        for ds_id, avg in reversed(sorted_datasets[:5])
    ]

    return {
        "timeRange": {"startDate": start_date, "endDate": end_date},
        "totalRuns": total_runs,
        "averageScore": average_score,
        "passRate": pass_rate,
        "failRate": fail_rate,
        "passCount": passed,
        "failCount": failed,
        "highestScoringDatasets": highest,
        "lowestScoringDatasets": lowest,
    }


def _parse_iso_date(date_str: str) -> datetime:
    """Parse an ISO 8601 date string.

    Args:
        date_str: ISO 8601 formatted date string.

    Returns:
        Parsed datetime object.

    Raises:
        ValueError: If the date string is invalid.
    """
    # Handle various ISO formats
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid date format: {date_str}")
