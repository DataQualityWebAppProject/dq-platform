"""Anomaly Scoring Lambda handler.

Handles HTTP API routes for anomaly scoring:
- POST /anomalies/scoring → trigger anomaly scoring

Checks that a model exists, scores records using reconstruction error,
classifies severity, and stores results in DynamoDB.

Severity classification:
- critical: reconstruction error > 3x threshold
- high: reconstruction error > 2x threshold
- medium: reconstruction error > 1.5x threshold
- low: reconstruction error > 1x threshold
- normal: reconstruction error <= threshold

DynamoDB Table: dq-anomaly-scores
- PK: SCORING#{scoring_id}
- SK: RECORD#{record_id}

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
"""

from __future__ import annotations

import json
import logging
import os
import ulid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

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
SCORING_TABLE = os.environ.get("SCORING_TABLE", "dq-anomaly-scores")
TRAINING_TABLE = os.environ.get("TRAINING_TABLE", "dq-anomaly-training")
MODELS_BUCKET = os.environ.get("MODELS_BUCKET", "dq-mlflow-108782054634")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Default threshold when none is defined by user
DEFAULT_THRESHOLD = 0.5


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for anomaly scoring.

    Routes:
    - POST /anomalies/scoring → trigger scoring

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)

    try:
        http_method = event.get("requestContext", {}).get("http", {}).get("method", "")

        if http_method == "POST":
            return _trigger_scoring(event, request_id)
        else:
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in scoring handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the scoring request.",
            request_id=request_id,
        )


def _trigger_scoring(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Trigger anomaly scoring for a dataset.

    Expected body:
    {
        "modelId": "...",
        "datasetId": "...",
        "datasetS3Path": "...",
        "threshold": 0.5  (optional)
    }

    Workflow:
    1. Validate model exists and is ready
    2. Score records using reconstruction error
    3. Classify severity based on threshold
    4. Store results in DynamoDB

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Scoring results summary.
    """
    # Authentication check
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Both AdminDatos and AnalistaDatos can trigger scoring
    if claims.role not in [ADMIN_ROLE, ANALYST_ROLE]:
        from services.shared.errors import forbidden_error
        return forbidden_error(
            message="You do not have permission to trigger scoring.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    model_id = body.get("modelId")
    dataset_id = body.get("datasetId")
    dataset_s3_path = body.get("datasetS3Path")
    threshold = body.get("threshold", DEFAULT_THRESHOLD)

    if not model_id:
        return validation_error(
            message="modelId is required.",
            details={"field": "modelId"},
            request_id=request_id,
        )

    if not dataset_id:
        return validation_error(
            message="datasetId is required.",
            details={"field": "datasetId"},
            request_id=request_id,
        )

    if not dataset_s3_path:
        return validation_error(
            message="datasetS3Path is required.",
            details={"field": "datasetS3Path"},
            request_id=request_id,
        )

    # Validate threshold
    try:
        threshold = float(threshold)
        if threshold <= 0:
            return validation_error(
                message="Threshold must be a positive number.",
                details={"field": "threshold", "value": threshold},
                request_id=request_id,
            )
    except (ValueError, TypeError):
        return validation_error(
            message="Threshold must be a valid number.",
            details={"field": "threshold"},
            request_id=request_id,
        )

    # Check model exists
    training_db = DynamoHelper(TRAINING_TABLE)
    model_item = training_db.get_item(pk=f"TRAINING#{model_id}", sk="METADATA")

    if model_item is None:
        return not_found_error(
            message=f"Model '{model_id}' not found. Please train a model first.",
            details={"modelId": model_id},
            request_id=request_id,
        )

    if model_item.get("status") != "completed":
        return validation_error(
            message=f"Model '{model_id}' is not ready. Current status: {model_item.get('status')}",
            details={"modelId": model_id, "status": model_item.get("status")},
            request_id=request_id,
        )

    # Create scoring job record
    scoring_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    scoring_metadata = {
        "PK": f"SCORING#{scoring_id}",
        "SK": "METADATA",
        "id": scoring_id,
        "modelId": model_id,
        "datasetId": dataset_id,
        "datasetS3Path": dataset_s3_path,
        "threshold": str(threshold),
        "status": "in-progress",
        "startedAt": now,
        "completedAt": None,
        "triggeredBy": claims.user_id,
        "summary": None,
    }

    scoring_db = DynamoHelper(SCORING_TABLE)

    try:
        scoring_db.put_item(scoring_metadata)
    except ClientError as e:
        logger.error(f"Failed to create scoring record: {e}")
        return internal_error(
            message="Failed to create scoring job record.",
            request_id=request_id,
        )

    # Invoke SageMaker endpoint for scoring (or simulate)
    try:
        results = _invoke_scoring_endpoint(
            model_id=model_id,
            dataset_s3_path=dataset_s3_path,
            threshold=threshold,
        )

        # Classify and store results
        classified_results = _classify_results(results, threshold)

        # Store per-record results in batches
        result_items = []
        for record in classified_results:
            result_item = {
                "PK": f"SCORING#{scoring_id}",
                "SK": f"RECORD#{record['recordId']}",
                "scoringId": scoring_id,
                "recordId": record["recordId"],
                "reconstructionError": str(record["reconstructionError"]),
                "severity": record["severity"],
                "isAnomaly": record["isAnomaly"],
                "fieldValues": record.get("fieldValues", {}),
                "scoredAt": now,
            }
            result_items.append(result_item)

        if result_items:
            scoring_db.batch_write(result_items)

        # Compute summary
        total = len(classified_results)
        anomalies = sum(1 for r in classified_results if r["isAnomaly"])
        severity_counts = {}
        for r in classified_results:
            sev = r["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary = {
            "totalRecords": total,
            "anomalyCount": anomalies,
            "anomalyPercentage": round((anomalies / total) * 100, 2) if total > 0 else 0,
            "severityCounts": severity_counts,
            "threshold": threshold,
        }

        # Update scoring record with results
        scoring_db.update_item(
            pk=f"SCORING#{scoring_id}",
            sk="METADATA",
            update_expression="SET #s = :s, completedAt = :ca, summary = :sum",
            expression_values={
                ":s": "completed",
                ":ca": datetime.now(timezone.utc).isoformat(),
                ":sum": summary,
            },
            expression_names={"#s": "status"},
        )

        return success_response(
            {
                "scoringId": scoring_id,
                "status": "completed",
                "summary": summary,
            },
            status_code=200,
        )

    except ClientError as e:
        logger.error(f"Scoring failed: {e}")
        scoring_db.update_item(
            pk=f"SCORING#{scoring_id}",
            sk="METADATA",
            update_expression="SET #s = :s, errorMessage = :em",
            expression_values={
                ":s": "failed",
                ":em": str(e),
            },
            expression_names={"#s": "status"},
        )
        return internal_error(
            message="Scoring job failed.",
            details={"scoringId": scoring_id},
            request_id=request_id,
        )


def _invoke_scoring_endpoint(
    model_id: str,
    dataset_s3_path: str,
    threshold: float,
) -> list[dict[str, Any]]:
    """Invoke SageMaker endpoint for anomaly scoring.

    In production, this would invoke a real SageMaker endpoint.
    For now, it returns simulated reconstruction errors.

    Args:
        model_id: The trained model ID.
        dataset_s3_path: S3 path to the dataset.
        threshold: The anomaly threshold.

    Returns:
        List of records with reconstruction errors.
    """
    # In production, invoke SageMaker endpoint
    sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)

    try:
        # Attempt to invoke the endpoint
        endpoint_name = f"dq-anomaly-{model_id}"
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Body=json.dumps({"datasetS3Path": dataset_s3_path}),
        )
        result_body = json.loads(response["Body"].read().decode("utf-8"))
        return result_body.get("records", [])

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ValidationError":
            # Endpoint doesn't exist - return empty for now
            logger.warning(f"SageMaker endpoint not found for model {model_id}")
            raise
        raise


def _classify_results(
    results: list[dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    """Classify anomaly results by severity.

    Severity levels:
    - critical: error > 3x threshold
    - high: error > 2x threshold
    - medium: error > 1.5x threshold
    - low: error > 1x threshold
    - normal: error <= threshold

    Args:
        results: List of records with reconstructionError.
        threshold: The anomaly threshold.

    Returns:
        Records enriched with severity and isAnomaly fields.
    """
    classified = []

    for record in results:
        error = float(record.get("reconstructionError", 0))

        if error > threshold * 3:
            severity = "critical"
            is_anomaly = True
        elif error > threshold * 2:
            severity = "high"
            is_anomaly = True
        elif error > threshold * 1.5:
            severity = "medium"
            is_anomaly = True
        elif error > threshold:
            severity = "low"
            is_anomaly = True
        else:
            severity = "normal"
            is_anomaly = False

        classified.append({
            **record,
            "severity": severity,
            "isAnomaly": is_anomaly,
        })

    return classified


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
