"""Cleaning Orchestrator Lambda handler.

Handles HTTP API routes for data cleaning operations:
- POST /cleaning/generate      → generate cleaning script via Bedrock Haiku
- POST /cleaning/{id}/execute  → execute an approved cleaning script

On execute:
1. Backup dataset to S3 dq-backups bucket
2. Start Glue job with the cleaning script
3. On failure: restore from backup

DynamoDB Table: dq-cleaning-jobs
- PK: CLEANING#{job_id}
- SK: METADATA

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7
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
    forbidden_error,
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
RAW_BUCKET = os.environ.get("RAW_BUCKET", "dq-raw-108782054634")
BACKUPS_BUCKET = os.environ.get("BACKUPS_BUCKET", "dq-backups-108782054634")
CLEAN_BUCKET = os.environ.get("CLEAN_BUCKET", "dq-clean-108782054634")
SCRIPTS_BUCKET = os.environ.get("SCRIPTS_BUCKET", "dq-scripts-108782054634")
GLUE_JOB_NAME = os.environ.get("CLEANING_GLUE_JOB", "dq-cleaning-job")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Bedrock model for script generation
BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
BEDROCK_MAX_TOKENS = 4096
BEDROCK_TIMEOUT = 30  # 30 seconds max


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for cleaning orchestration.

    Routes:
    - POST /cleaning/generate     → generate cleaning script
    - POST /cleaning/{id}/execute → execute approved script

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

        if http_method != "POST":
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

        # Determine route
        job_id, is_execute = _parse_path(path)

        if is_execute and job_id:
            return _execute_cleaning(event, job_id, request_id)
        elif not job_id:
            return _generate_script(event, request_id)
        else:
            return validation_error(
                message="Invalid path.",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in cleaning orchestrator: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the cleaning request.",
            request_id=request_id,
        )


def _parse_path(path: str) -> tuple[Optional[str], bool]:
    """Parse path to determine route.

    Returns:
        Tuple of (job_id, is_execute).
    """
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # POST /cleaning/{id}/execute
    if len(parts) >= 3 and parts[0] == "cleaning" and parts[2] == "execute":
        return parts[1], True

    # POST /cleaning/generate
    if len(parts) >= 2 and parts[0] == "cleaning" and parts[1] == "generate":
        return None, False

    return None, False


def _generate_script(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Generate a cleaning script using Bedrock Claude 3 Haiku.

    Expected body:
    {
        "datasetId": "...",
        "datasetS3Path": "...",
        "issues": ["missing values in column X", "outliers in column Y", ...]
    }

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Generated cleaning script and description.
    """
    # Authentication check
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role not in [ADMIN_ROLE, ANALYST_ROLE]:
        return forbidden_error(
            message="You do not have permission to generate cleaning scripts.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    dataset_id = body.get("datasetId")
    dataset_s3_path = body.get("datasetS3Path")
    issues = body.get("issues", [])

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

    if not issues or not isinstance(issues, list):
        return validation_error(
            message="issues must be a non-empty list of data quality issues.",
            details={"field": "issues"},
            request_id=request_id,
        )

    # Generate cleaning script via Bedrock
    try:
        script_content, description = _invoke_bedrock_for_script(issues, dataset_s3_path)
    except Exception as e:
        logger.error(f"Bedrock script generation failed: {e}")
        return internal_error(
            message="Failed to generate cleaning script. Please try again.",
            request_id=request_id,
        )

    # Create cleaning job record (status: pending_approval)
    job_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    job_item = {
        "PK": f"CLEANING#{job_id}",
        "SK": "METADATA",
        "id": job_id,
        "datasetId": dataset_id,
        "datasetS3Path": dataset_s3_path,
        "issues": issues,
        "script": script_content,
        "description": description,
        "status": "pending_approval",
        "createdAt": now,
        "createdBy": claims.user_id,
        "executedAt": None,
        "completedAt": None,
        "summary": None,
        "backupS3Path": None,
        "errorMessage": None,
    }

    db = DynamoHelper(CLEANING_TABLE)

    try:
        db.put_item(job_item)
    except ClientError as e:
        logger.error(f"Failed to create cleaning job record: {e}")
        return internal_error(
            message="Failed to save cleaning job.",
            request_id=request_id,
        )

    return success_response(
        {
            "jobId": job_id,
            "status": "pending_approval",
            "script": script_content,
            "description": description,
            "datasetId": dataset_id,
            "createdAt": now,
        },
        status_code=201,
    )


def _execute_cleaning(
    event: dict[str, Any], job_id: str, request_id: str
) -> dict[str, Any]:
    """Execute an approved cleaning script.

    Workflow:
    1. Verify job exists and is in pending_approval status
    2. Backup dataset to S3 dq-backups
    3. Upload cleaning script to S3 dq-scripts
    4. Start Glue job
    5. On failure: restore from backup

    Args:
        event: API Gateway event.
        job_id: The cleaning job ID.
        request_id: The request ID.

    Returns:
        Execution status.
    """
    # Authentication check
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role != ADMIN_ROLE:
        return forbidden_error(
            message="Only AdminDatos can execute cleaning scripts.",
            request_id=request_id,
        )

    # Verify job exists and is pending
    db = DynamoHelper(CLEANING_TABLE)
    job_item = db.get_item(pk=f"CLEANING#{job_id}", sk="METADATA")

    if job_item is None:
        return not_found_error(
            message=f"Cleaning job '{job_id}' not found.",
            details={"jobId": job_id},
            request_id=request_id,
        )

    if job_item.get("status") != "pending_approval":
        return validation_error(
            message=f"Job is not pending approval. Current status: {job_item.get('status')}",
            details={"jobId": job_id, "status": job_item.get("status")},
            request_id=request_id,
        )

    dataset_s3_path = job_item.get("datasetS3Path", "")
    script_content = job_item.get("script", "")
    now = datetime.now(timezone.utc).isoformat()

    s3_client = boto3.client("s3", region_name=AWS_REGION)

    # Step 1: Backup dataset
    backup_key = f"backups/{job_id}/{os.path.basename(dataset_s3_path)}"
    try:
        s3_client.copy_object(
            Bucket=BACKUPS_BUCKET,
            Key=backup_key,
            CopySource={"Bucket": RAW_BUCKET, "Key": dataset_s3_path},
        )
        logger.info(f"Backup created at s3://{BACKUPS_BUCKET}/{backup_key}")
    except ClientError as e:
        logger.error(f"Failed to create backup: {e}")
        return internal_error(
            message="Failed to create dataset backup before cleaning.",
            request_id=request_id,
        )

    # Step 2: Upload cleaning script to S3
    script_key = f"cleaning-scripts/{job_id}/clean.py"
    try:
        s3_client.put_object(
            Bucket=SCRIPTS_BUCKET,
            Key=script_key,
            Body=script_content.encode("utf-8"),
            ContentType="text/x-python",
        )
        logger.info(f"Script uploaded to s3://{SCRIPTS_BUCKET}/{script_key}")
    except ClientError as e:
        logger.error(f"Failed to upload cleaning script: {e}")
        return internal_error(
            message="Failed to upload cleaning script.",
            request_id=request_id,
        )

    # Step 3: Update job status and start Glue job
    try:
        db.update_item(
            pk=f"CLEANING#{job_id}",
            sk="METADATA",
            update_expression="SET #s = :s, executedAt = :ea, backupS3Path = :bp, approvedBy = :ab",
            expression_values={
                ":s": "running",
                ":ea": now,
                ":bp": f"s3://{BACKUPS_BUCKET}/{backup_key}",
                ":ab": claims.user_id,
            },
            expression_names={"#s": "status"},
        )
    except ClientError as e:
        logger.error(f"Failed to update job status: {e}")

    # Step 4: Start Glue job
    try:
        glue_client = boto3.client("glue", region_name=AWS_REGION)
        glue_response = glue_client.start_job_run(
            JobName=GLUE_JOB_NAME,
            Arguments={
                "--JOB_ID": job_id,
                "--DATASET_S3_PATH": dataset_s3_path,
                "--SCRIPT_S3_PATH": f"s3://{SCRIPTS_BUCKET}/{script_key}",
                "--RAW_BUCKET": RAW_BUCKET,
                "--CLEAN_BUCKET": CLEAN_BUCKET,
                "--BACKUP_S3_PATH": f"s3://{BACKUPS_BUCKET}/{backup_key}",
                "--CLEANING_TABLE": CLEANING_TABLE,
            },
        )
        glue_run_id = glue_response.get("JobRunId", "")
        logger.info(f"Started cleaning Glue job, run ID: {glue_run_id}")

        db.update_item(
            pk=f"CLEANING#{job_id}",
            sk="METADATA",
            update_expression="SET glueJobRunId = :gjr",
            expression_values={":gjr": glue_run_id},
        )

    except ClientError as e:
        logger.error(f"Failed to start Glue job: {e}")

        # Restore from backup on failure
        _restore_from_backup(s3_client, backup_key, dataset_s3_path)

        db.update_item(
            pk=f"CLEANING#{job_id}",
            sk="METADATA",
            update_expression="SET #s = :s, errorMessage = :em",
            expression_values={
                ":s": "failed",
                ":em": f"Failed to start Glue job: {str(e)}",
            },
            expression_names={"#s": "status"},
        )

        return internal_error(
            message="Failed to start cleaning job. Dataset has been restored from backup.",
            details={"jobId": job_id},
            request_id=request_id,
        )

    return success_response(
        {
            "jobId": job_id,
            "status": "running",
            "executedAt": now,
            "backupPath": f"s3://{BACKUPS_BUCKET}/{backup_key}",
        },
        status_code=202,
    )


def _invoke_bedrock_for_script(
    issues: list[str], dataset_s3_path: str
) -> tuple[str, str]:
    """Invoke Bedrock Claude 3 Haiku to generate a cleaning script.

    Args:
        issues: List of data quality issues to address.
        dataset_s3_path: S3 path to the dataset (for context).

    Returns:
        Tuple of (script_content, description).
    """
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    issues_text = "\n".join(f"- {issue}" for issue in issues)

    prompt = f"""Generate a Python data cleaning script that addresses the following data quality issues:

Dataset: {dataset_s3_path}

Issues to fix:
{issues_text}

Requirements:
1. The script must define a function `clean_dataset(df: pd.DataFrame) -> pd.DataFrame`
2. The function takes a pandas DataFrame and returns a cleaned DataFrame
3. Handle each issue with appropriate transformations
4. Do not drop rows unless absolutely necessary
5. Include comments explaining each transformation
6. Return the cleaned DataFrame

Also provide a brief description of what the script does (2-3 sentences).

Format your response as JSON:
{{
    "script": "# Python cleaning script\\nimport pandas as pd\\n...",
    "description": "Brief description of transformations applied."
}}"""

    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": BEDROCK_MAX_TOKENS,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
    })

    response = bedrock_client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read().decode("utf-8"))
    content = response_body.get("content", [{}])[0].get("text", "")

    # Parse the JSON response
    try:
        parsed = json.loads(content)
        script = parsed.get("script", "")
        description = parsed.get("description", "")
    except json.JSONDecodeError:
        # Fallback: treat entire response as script
        script = content
        description = "AI-generated cleaning script."

    return script, description


def _restore_from_backup(s3_client: Any, backup_key: str, dataset_s3_path: str) -> None:
    """Restore dataset from backup on failure.

    Args:
        s3_client: boto3 S3 client.
        backup_key: S3 key of the backup.
        dataset_s3_path: Original dataset S3 path to restore to.
    """
    try:
        s3_client.copy_object(
            Bucket=RAW_BUCKET,
            Key=dataset_s3_path,
            CopySource={"Bucket": BACKUPS_BUCKET, "Key": backup_key},
        )
        logger.info(f"Restored dataset from backup: {backup_key}")
    except ClientError as e:
        logger.error(f"CRITICAL: Failed to restore from backup: {e}")


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
