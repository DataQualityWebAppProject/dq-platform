"""Anomaly Training Status Lambda handler.

Handles HTTP API routes for checking training job status:
- GET /anomalies/training/{id} → get training job status

DynamoDB Table: dq-anomaly-training

Requirements: 12.5, 12.6
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
TRAINING_TABLE = os.environ.get("TRAINING_TABLE", "dq-anomaly-training")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for training status queries.

    Routes:
    - GET /anomalies/training/{id} → get training job status

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

        # Extract training ID from path
        path = event.get("rawPath", "") or event.get("path", "")
        training_id = _extract_training_id(path)

        if not training_id:
            return validation_error(
                message="Training ID is required in the path.",
                request_id=request_id,
            )

        return _get_training_status(event, training_id, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in training status handler: {e}")
        return internal_error(
            message="An unexpected error occurred while querying training status.",
            request_id=request_id,
        )


def _extract_training_id(path: str) -> Optional[str]:
    """Extract training ID from path /anomalies/training/{id}."""
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /anomalies/training/{id}
    if len(parts) >= 3 and parts[0] == "anomalies" and parts[1] == "training":
        return parts[2]

    return None


def _get_training_status(
    event: dict[str, Any], training_id: str, request_id: str
) -> dict[str, Any]:
    """Get the status of a training job.

    Args:
        event: API Gateway event.
        training_id: The training job ID.
        request_id: The request ID.

    Returns:
        Training job status and metadata.
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
            message="You do not have permission to view training status.",
            request_id=request_id,
        )

    db = DynamoHelper(TRAINING_TABLE)
    item = db.get_item(pk=f"TRAINING#{training_id}", sk="METADATA")

    if item is None:
        return not_found_error(
            message=f"Training job '{training_id}' not found.",
            details={"trainingId": training_id},
            request_id=request_id,
        )

    response_body = {
        "id": item.get("id"),
        "datasetId": item.get("datasetId"),
        "status": item.get("status"),
        "hyperparameters": item.get("hyperparameters", {}),
        "startedAt": item.get("startedAt"),
        "completedAt": item.get("completedAt"),
        "launchedBy": item.get("launchedBy"),
        "sagemakerJobName": item.get("sagemakerJobName"),
        "modelArtifactPath": item.get("modelArtifactPath"),
        "errorMessage": item.get("errorMessage"),
    }

    return success_response(response_body)
