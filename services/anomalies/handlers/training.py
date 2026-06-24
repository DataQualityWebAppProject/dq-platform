"""Anomaly Training Lambda handler.

Handles HTTP API routes for anomaly detection training:
- POST /anomalies/training → launch training job

Validates hyperparameters, creates SageMaker training job,
and stores metadata in DynamoDB.

DynamoDB Table: dq-anomaly-training
- PK: TRAINING#{training_id}
- SK: METADATA

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7
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
    extract_user_claims,
    get_request_id,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    forbidden_error,
    internal_error,
    success_response,
    unauthorized_error,
    validation_error,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
TRAINING_TABLE = os.environ.get("TRAINING_TABLE", "dq-anomaly-training")
MODELS_BUCKET = os.environ.get("MODELS_BUCKET", "dq-mlflow-108782054634")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "dq-raw-108782054634")
SAGEMAKER_ROLE_ARN = os.environ.get("SAGEMAKER_ROLE_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Hyperparameter validation bounds
HYPERPARAMETER_BOUNDS = {
    "learningRate": {"min": 0.0001, "max": 0.01},
    "epochs": {"min": 10, "max": 500},
    "batchSize": {"min": 16, "max": 256},
    "encodingDimension": {"min": 4, "max": 64},
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for anomaly training.

    Routes:
    - POST /anomalies/training → launch training job

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
            return _launch_training(event, request_id)
        else:
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in training handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the training request.",
            request_id=request_id,
        )


def _launch_training(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Launch a new anomaly training job.

    Validates hyperparameters and creates a SageMaker training job.

    Expected body:
    {
        "datasetId": "...",
        "datasetS3Path": "...",
        "hyperparameters": {
            "learningRate": 0.001,
            "epochs": 100,
            "batchSize": 32,
            "encodingDimension": 16
        }
    }

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with training job metadata.
    """
    # Authorization: AdminDatos only
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role != ADMIN_ROLE:
        return forbidden_error(
            message="Only AdminDatos can launch training jobs.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    # Validate required fields
    dataset_id = body.get("datasetId")
    dataset_s3_path = body.get("datasetS3Path")
    hyperparameters = body.get("hyperparameters", {})

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

    # Validate hyperparameters
    hp_errors = _validate_hyperparameters(hyperparameters)
    if hp_errors:
        return validation_error(
            message="Invalid hyperparameters.",
            details={"hyperparameters": hp_errors},
            request_id=request_id,
        )

    # Create training job record
    training_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    training_item = {
        "PK": f"TRAINING#{training_id}",
        "SK": "METADATA",
        "id": training_id,
        "datasetId": dataset_id,
        "datasetS3Path": dataset_s3_path,
        "hyperparameters": hyperparameters,
        "status": "in-progress",
        "startedAt": now,
        "completedAt": None,
        "launchedBy": claims.user_id,
        "modelArtifactPath": None,
        "sagemakerJobName": None,
        "errorMessage": None,
        # GSI keys
        "GSI1PK": dataset_id,
        "GSI1SK": now,
    }

    db = DynamoHelper(TRAINING_TABLE)

    try:
        db.put_item(training_item)
    except ClientError as e:
        logger.error(f"Failed to create training record: {e}")
        return internal_error(
            message="Failed to create training job record.",
            request_id=request_id,
        )

    # Launch SageMaker training job
    sagemaker_job_name = f"dq-anomaly-{training_id}"

    try:
        sagemaker_client = boto3.client("sagemaker", region_name=AWS_REGION)

        training_params = {
            "TrainingJobName": sagemaker_job_name,
            "RoleArn": SAGEMAKER_ROLE_ARN,
            "AlgorithmSpecification": {
                "TrainingImage": f"763104351884.dkr.ecr.{AWS_REGION}.amazonaws.com/tensorflow-training:2.13-cpu-py310",
                "TrainingInputMode": "File",
            },
            "InputDataConfig": [
                {
                    "ChannelName": "training",
                    "DataSource": {
                        "S3DataSource": {
                            "S3DataType": "S3Prefix",
                            "S3Uri": f"s3://{RAW_BUCKET}/{dataset_s3_path}",
                            "S3DataDistributionType": "FullyReplicated",
                        }
                    },
                }
            ],
            "OutputDataConfig": {
                "S3OutputPath": f"s3://{MODELS_BUCKET}/models/{training_id}/",
            },
            "ResourceConfig": {
                "InstanceType": "ml.m5.large",
                "InstanceCount": 1,
                "VolumeSizeInGB": 30,
            },
            "StoppingCondition": {
                "MaxRuntimeInSeconds": 14400,  # 4 hours max
            },
            "HyperParameters": {
                "learning_rate": str(hyperparameters.get("learningRate", 0.001)),
                "epochs": str(hyperparameters.get("epochs", 100)),
                "batch_size": str(hyperparameters.get("batchSize", 32)),
                "encoding_dimension": str(hyperparameters.get("encodingDimension", 16)),
            },
        }

        sagemaker_client.create_training_job(**training_params)
        logger.info(f"Created SageMaker training job: {sagemaker_job_name}")

        # Update record with SageMaker job name
        db.update_item(
            pk=f"TRAINING#{training_id}",
            sk="METADATA",
            update_expression="SET sagemakerJobName = :sjn",
            expression_values={":sjn": sagemaker_job_name},
        )

    except ClientError as e:
        logger.error(f"Failed to create SageMaker training job: {e}")
        # Update record to reflect failure
        db.update_item(
            pk=f"TRAINING#{training_id}",
            sk="METADATA",
            update_expression="SET #s = :s, errorMessage = :em",
            expression_values={
                ":s": "failed",
                ":em": f"SageMaker job creation failed: {str(e)}",
            },
            expression_names={"#s": "status"},
        )
        return internal_error(
            message="Failed to launch SageMaker training job.",
            details={"trainingId": training_id},
            request_id=request_id,
        )

    return success_response(
        {
            "trainingId": training_id,
            "status": "in-progress",
            "startedAt": now,
            "datasetId": dataset_id,
            "hyperparameters": hyperparameters,
            "sagemakerJobName": sagemaker_job_name,
        },
        status_code=202,
    )


def _validate_hyperparameters(params: dict[str, Any]) -> dict[str, str]:
    """Validate hyperparameters against allowed bounds.

    Args:
        params: The hyperparameters dict.

    Returns:
        Dict of param_name → error message for invalid params.
    """
    errors: dict[str, str] = {}

    for param_name, bounds in HYPERPARAMETER_BOUNDS.items():
        value = params.get(param_name)
        if value is None:
            continue  # Optional, will use defaults

        try:
            value = float(value)
        except (ValueError, TypeError):
            errors[param_name] = f"Must be a number."
            continue

        if value < bounds["min"] or value > bounds["max"]:
            errors[param_name] = (
                f"Must be between {bounds['min']} and {bounds['max']}. Got: {value}"
            )

    return errors


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
