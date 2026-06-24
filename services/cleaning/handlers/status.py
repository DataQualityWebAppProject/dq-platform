"""Cleaning Status Lambda handler.

Handles HTTP API routes for checking cleaning job status:
- GET /cleaning/{id} → get job status + report

DynamoDB Table: dq-cleaning-jobs

Requirements: 15.4, 15.7
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from services.shared.auth import (
    ADMIN_ROLE,
    ANALYST_ROLE,
    extract_user_claims,
    get_request_id,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    internal_error,
    not_found_error,
    success_response,
    unauthorized_error,
    validation_error,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
CLEANING_TABLE = os.environ.get("CLEANING_TABLE", "dq-cleaning-jobs")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for cleaning status queries.

    Routes:
    - GET /cleaning/{id} → get job status and report

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

        # Extract job ID from path
        path = event.get("rawPath", "") or event.get("path", "")
        job_id = _extract_job_id(path)

        if not job_id:
            return validation_error(
                message="Cleaning job ID is required in the path.",
                request_id=request_id,
            )

        return _get_job_status(event, job_id, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in cleaning status handler: {e}")
        return internal_error(
            message="An unexpected error occurred while querying cleaning job status.",
            request_id=request_id,
        )


def _extract_job_id(path: str) -> Optional[str]:
    """Extract job ID from path /cleaning/{id}."""
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /cleaning/{id}
    if len(parts) >= 2 and parts[0] == "cleaning":
        # Exclude sub-paths like /cleaning/generate
        if parts[1] in ("generate",):
            return None
        return parts[1]

    return None


def _get_job_status(
    event: dict[str, Any], job_id: str, request_id: str
) -> dict[str, Any]:
    """Get the status and report of a cleaning job.

    Args:
        event: API Gateway event.
        job_id: The cleaning job ID.
        request_id: The request ID.

    Returns:
        Cleaning job status and report.
    """
    # Authentication check
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role not in [ADMIN_ROLE, ANALYST_ROLE]:
        from services.shared.errors import forbidden_error
        return forbidden_error(
            message="You do not have permission to view cleaning job status.",
            request_id=request_id,
        )

    db = DynamoHelper(CLEANING_TABLE)
    item = db.get_item(pk=f"CLEANING#{job_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Cleaning job '{job_id}' not found.",
            details={"jobId": job_id},
            request_id=request_id,
        )

    response_body = {
        "id": item.get("id"),
        "datasetId": item.get("datasetId"),
        "datasetS3Path": item.get("datasetS3Path"),
        "status": item.get("status"),
        "issues": item.get("issues", []),
        "script": item.get("script"),
        "description": item.get("description"),
        "createdAt": item.get("createdAt"),
        "createdBy": item.get("createdBy"),
        "executedAt": item.get("executedAt"),
        "completedAt": item.get("completedAt"),
        "approvedBy": item.get("approvedBy"),
        "backupS3Path": item.get("backupS3Path"),
        "summary": item.get("summary"),
        "errorMessage": item.get("errorMessage"),
    }

    return success_response(response_body)
