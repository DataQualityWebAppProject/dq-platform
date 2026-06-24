"""Validation Orchestrator Lambda handler.

Handles HTTP API routes for triggering validation runs:
- POST /validations → trigger_validation

Creates a validation run record, fetches active rules for the dataset,
and starts a Glue job (dq-validation-job) to execute the rules.

DynamoDB Table: dq-validation-runs
- PK: VALIDATION#{run_id}
- SK: METADATA
- GSI status-index: PK=status, SK=startedAt
- GSI dataset-index: PK=datasetId, SK=startedAt

Requirements: 10.1, 10.2, 10.4, 10.5
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
    validation_error,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
VALIDATION_RUNS_TABLE = os.environ.get("VALIDATION_RUNS_TABLE", "dq-validation-runs")
RULES_TABLE = os.environ.get("RULES_TABLE", "dq-rules")
GLUE_JOB_NAME = os.environ.get("GLUE_JOB_NAME", "dq-validation-job")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "dq-raw-108782054634")
SCRIPTS_BUCKET = os.environ.get("SCRIPTS_BUCKET", "dq-scripts-108782054634")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for validation orchestration.

    Routes:
    - POST /validations → trigger a new validation run

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
            return _trigger_validation(event, request_id)
        else:
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in validation orchestrator: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the validation request.",
            request_id=request_id,
        )


def _trigger_validation(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Trigger a new validation run.

    Workflow:
    1. Validate request body (datasetId, datasetS3Path required)
    2. Fetch active rules for the dataset
    3. Reject if no active rules exist
    4. Create validation_run record (status: running)
    5. Start Glue job with RUN_ID, DATASET_S3_PATH, RULES_JSON
    6. Return runId and status

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with runId and status.
    """
    # Authentication check
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Authorization: AdminDatos and AnalistaDatos can trigger validations
    if claims.role not in [ADMIN_ROLE, ANALYST_ROLE]:
        from services.shared.errors import forbidden_error
        return forbidden_error(
            message="You do not have permission to trigger validations.",
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

    # Fetch active rules for the dataset
    rules = _fetch_active_rules(dataset_id)

    if not rules:
        return validation_error(
            message="No active rules exist for this dataset. Please create rules before running validation.",
            details={"datasetId": dataset_id},
            request_id=request_id,
        )

    # Create validation run record
    run_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    run_item = {
        "PK": f"VALIDATION#{run_id}",
        "SK": "METADATA",
        "id": run_id,
        "datasetId": dataset_id,
        "datasetS3Path": dataset_s3_path,
        "status": "running",
        "startedAt": now,
        "triggeredBy": claims.user_id,
        "rulesCount": len(rules),
        "ruleIds": [r["id"] for r in rules],
        "score": None,
        "completedAt": None,
        "errorMessage": None,
        # GSI keys
        "GSI1PK": "running",
        "GSI1SK": now,
        "GSI2PK": dataset_id,
        "GSI2SK": now,
    }

    db = DynamoHelper(VALIDATION_RUNS_TABLE)

    try:
        db.put_item(run_item)
    except ClientError as e:
        logger.error(f"Failed to create validation run record: {e}")
        return internal_error(
            message="Failed to create validation run.",
            request_id=request_id,
        )

    # Prepare rules JSON for Glue job
    rules_json = json.dumps([
        {
            "id": r["id"],
            "name": r.get("name", ""),
            "scriptS3Key": r.get("scriptS3Key", ""),
            "scope": r.get("scope", ""),
            "targetFields": r.get("targetFields", []),
        }
        for r in rules
    ])

    # Start Glue job
    try:
        glue_client = boto3.client("glue", region_name=AWS_REGION)
        glue_response = glue_client.start_job_run(
            JobName=GLUE_JOB_NAME,
            Arguments={
                "--RUN_ID": run_id,
                "--DATASET_S3_PATH": dataset_s3_path,
                "--RULES_JSON": rules_json,
                "--RESULTS_TABLE": VALIDATION_RUNS_TABLE,
                "--RAW_BUCKET": RAW_BUCKET,
                "--SCRIPTS_BUCKET": SCRIPTS_BUCKET,
            },
        )
        glue_run_id = glue_response.get("JobRunId", "")
        logger.info(f"Started Glue job {GLUE_JOB_NAME}, run ID: {glue_run_id}")

        # Update run record with Glue job run ID
        db.update_item(
            pk=f"VALIDATION#{run_id}",
            sk="METADATA",
            update_expression="SET glueJobRunId = :gjr",
            expression_values={":gjr": glue_run_id},
        )

    except ClientError as e:
        logger.error(f"Failed to start Glue job: {e}")
        # Update run status to failed
        db.update_item(
            pk=f"VALIDATION#{run_id}",
            sk="METADATA",
            update_expression="SET #s = :s, errorMessage = :em, GSI1PK = :gs",
            expression_values={
                ":s": "failed",
                ":em": f"Failed to start Glue job: {str(e)}",
                ":gs": "failed",
            },
            expression_names={"#s": "status"},
        )
        return internal_error(
            message="Failed to start validation job. The run has been marked as failed.",
            details={"runId": run_id},
            request_id=request_id,
        )

    return success_response(
        {
            "runId": run_id,
            "status": "running",
            "startedAt": now,
            "rulesCount": len(rules),
            "datasetId": dataset_id,
        },
        status_code=202,
    )


def _fetch_active_rules(dataset_id: str) -> list[dict[str, Any]]:
    """Fetch all active rules for a given dataset.

    Queries the rules table for rules that target the dataset
    and have status 'active'.

    Args:
        dataset_id: The dataset ID to find rules for.

    Returns:
        List of active rule items.
    """
    from boto3.dynamodb.conditions import Attr

    db = DynamoHelper(RULES_TABLE)

    try:
        # Query rules by dataset using scan with filter
        # In production, a GSI on datasetId+status would be more efficient
        result = db.scan(
            filter_expression=(
                Attr("status").eq("active")
                & (
                    Attr("datasetId").eq(dataset_id)
                    | Attr("scope_target").eq(dataset_id)
                )
            ),
            pagination=None,
        )
        return result.get("items", [])
    except ClientError as e:
        logger.error(f"Failed to fetch rules for dataset {dataset_id}: {e}")
        return []


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
