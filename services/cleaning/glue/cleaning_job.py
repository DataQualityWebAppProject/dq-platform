"""Glue Python Shell script for executing cleaning operations.

This script is executed as an AWS Glue Python Shell job.
Workflow:
1. Load dataset from S3
2. Load and execute the generated cleaning script
3. Track modifications per record
4. Write cleaned dataset to dq-clean bucket
5. Produce summary: total, modified, unchanged, errors
6. Update cleaning job record in DynamoDB

Job Arguments:
- --JOB_ID: The cleaning job identifier
- --DATASET_S3_PATH: S3 path to the dataset file
- --SCRIPT_S3_PATH: S3 path to the cleaning script
- --RAW_BUCKET: S3 bucket for raw datasets
- --CLEAN_BUCKET: S3 bucket for cleaned datasets
- --BACKUP_S3_PATH: S3 path of the backup (for restore on failure)
- --CLEANING_TABLE: DynamoDB table for cleaning jobs

Max execution time: 60 minutes (Python Shell, 1 DPU)

Requirements: 15.3, 15.4, 20.4
"""

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS region
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def main():
    """Main entry point for the Glue cleaning job."""
    from awsglue.utils import getResolvedOptions

    # Parse job arguments
    args = getResolvedOptions(sys.argv, [
        "JOB_ID",
        "DATASET_S3_PATH",
        "SCRIPT_S3_PATH",
        "RAW_BUCKET",
        "CLEAN_BUCKET",
        "BACKUP_S3_PATH",
        "CLEANING_TABLE",
    ])

    job_id = args["JOB_ID"]
    dataset_s3_path = args["DATASET_S3_PATH"]
    script_s3_path = args["SCRIPT_S3_PATH"]
    raw_bucket = args["RAW_BUCKET"]
    clean_bucket = args["CLEAN_BUCKET"]
    backup_s3_path = args["BACKUP_S3_PATH"]
    cleaning_table = args["CLEANING_TABLE"]

    logger.info(f"Starting cleaning job: {job_id}")
    logger.info(f"Dataset: s3://{raw_bucket}/{dataset_s3_path}")
    logger.info(f"Script: {script_s3_path}")

    s3_client = boto3.client("s3", region_name=AWS_REGION)

    # Step 1: Load dataset
    try:
        df_original = _load_dataset(s3_client, raw_bucket, dataset_s3_path)
        total_records = len(df_original)
        logger.info(f"Loaded dataset with {total_records} records")
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        _update_job_status(cleaning_table, job_id, "failed",
                          error_message=f"Dataset load error: {e}")
        _restore_backup(s3_client, backup_s3_path, raw_bucket, dataset_s3_path)
        sys.exit(1)

    # Step 2: Load cleaning script
    try:
        script_code = _load_script(s3_client, script_s3_path)
        logger.info("Cleaning script loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load cleaning script: {e}")
        _update_job_status(cleaning_table, job_id, "failed",
                          error_message=f"Script load error: {e}")
        _restore_backup(s3_client, backup_s3_path, raw_bucket, dataset_s3_path)
        sys.exit(1)

    # Step 3: Execute cleaning script
    try:
        # Compile and run the cleaning function
        namespace: dict[str, Any] = {"pd": pd}
        exec(script_code, namespace)

        if "clean_dataset" not in namespace:
            raise ValueError("Script must define a 'clean_dataset(df)' function")

        clean_func = namespace["clean_dataset"]
        df_cleaned = clean_func(df_original.copy())

        if not isinstance(df_cleaned, pd.DataFrame):
            raise ValueError("clean_dataset must return a pandas DataFrame")

        logger.info(f"Cleaning complete. Output: {len(df_cleaned)} records")

    except Exception as e:
        logger.error(f"Cleaning script execution failed: {e}")
        logger.error(traceback.format_exc())
        _update_job_status(cleaning_table, job_id, "failed",
                          error_message=f"Script execution error: {e}")
        _restore_backup(s3_client, backup_s3_path, raw_bucket, dataset_s3_path)
        sys.exit(1)

    # Step 4: Track modifications
    try:
        modified_count, unchanged_count, error_count = _count_modifications(
            df_original, df_cleaned
        )
    except Exception as e:
        logger.warning(f"Error counting modifications: {e}")
        modified_count = total_records
        unchanged_count = 0
        error_count = 0

    # Step 5: Write cleaned dataset to clean bucket
    clean_key = f"cleaned/{job_id}/{os.path.basename(dataset_s3_path)}"
    try:
        _write_dataset(s3_client, clean_bucket, clean_key, df_cleaned, dataset_s3_path)
        logger.info(f"Cleaned dataset written to s3://{clean_bucket}/{clean_key}")
    except Exception as e:
        logger.error(f"Failed to write cleaned dataset: {e}")
        _update_job_status(cleaning_table, job_id, "failed",
                          error_message=f"Output write error: {e}")
        _restore_backup(s3_client, backup_s3_path, raw_bucket, dataset_s3_path)
        sys.exit(1)

    # Step 6: Produce summary and update job record
    summary = {
        "totalRecords": total_records,
        "modifiedRecords": modified_count,
        "unchangedRecords": unchanged_count,
        "errorRecords": error_count,
        "outputRecords": len(df_cleaned),
        "outputS3Path": f"s3://{clean_bucket}/{clean_key}",
    }

    logger.info(f"Summary: {json.dumps(summary)}")
    _update_job_status(cleaning_table, job_id, "completed", summary=summary)


def _load_dataset(s3_client: Any, bucket: str, key: str) -> pd.DataFrame:
    """Load dataset from S3.

    Args:
        s3_client: boto3 S3 client.
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        Loaded DataFrame.
    """
    s3_uri = f"s3://{bucket}/{key}"

    if key.endswith(".parquet"):
        return pd.read_parquet(s3_uri)
    else:
        return pd.read_csv(s3_uri)


def _load_script(s3_client: Any, script_s3_path: str) -> str:
    """Load cleaning script from S3.

    Args:
        s3_client: boto3 S3 client.
        script_s3_path: Full S3 URI (s3://bucket/key).

    Returns:
        Script source code.
    """
    parsed = urlparse(script_s3_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _count_modifications(
    df_original: pd.DataFrame, df_cleaned: pd.DataFrame
) -> tuple[int, int, int]:
    """Count modified and unchanged records.

    Compares original and cleaned DataFrames row by row.

    Args:
        df_original: Original DataFrame.
        df_cleaned: Cleaned DataFrame.

    Returns:
        Tuple of (modified_count, unchanged_count, error_count).
    """
    # If shapes differ, all records were modified
    if df_original.shape != df_cleaned.shape:
        return len(df_cleaned), 0, abs(len(df_original) - len(df_cleaned))

    # Compare row by row
    try:
        comparison = df_original.compare(df_cleaned)
        modified_count = len(comparison)
        unchanged_count = len(df_original) - modified_count
        return modified_count, unchanged_count, 0
    except Exception:
        # Fallback: assume all modified if comparison fails
        return len(df_cleaned), 0, 0


def _write_dataset(
    s3_client: Any,
    bucket: str,
    key: str,
    df: pd.DataFrame,
    original_path: str,
) -> None:
    """Write cleaned dataset to S3.

    Preserves original format (CSV/Parquet).

    Args:
        s3_client: boto3 S3 client.
        bucket: Target S3 bucket.
        key: Target S3 key.
        df: Cleaned DataFrame.
        original_path: Original file path (to determine format).
    """
    import io

    if original_path.endswith(".parquet"):
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        body = buffer.getvalue()
        content_type = "application/octet-stream"
    else:
        body = df.to_csv(index=False).encode("utf-8")
        content_type = "text/csv"

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def _restore_backup(
    s3_client: Any, backup_s3_path: str, raw_bucket: str, dataset_s3_path: str
) -> None:
    """Restore dataset from backup on failure.

    Args:
        s3_client: boto3 S3 client.
        backup_s3_path: Full S3 URI of the backup.
        raw_bucket: Raw data bucket.
        dataset_s3_path: Original dataset S3 key.
    """
    try:
        parsed = urlparse(backup_s3_path)
        backup_bucket = parsed.netloc
        backup_key = parsed.path.lstrip("/")

        s3_client.copy_object(
            Bucket=raw_bucket,
            Key=dataset_s3_path,
            CopySource={"Bucket": backup_bucket, "Key": backup_key},
        )
        logger.info(f"Restored dataset from backup: {backup_s3_path}")
    except ClientError as e:
        logger.error(f"CRITICAL: Failed to restore from backup: {e}")


def _update_job_status(
    table_name: str,
    job_id: str,
    status: str,
    summary: dict = None,
    error_message: str = None,
) -> None:
    """Update cleaning job status in DynamoDB.

    Args:
        table_name: DynamoDB table name.
        job_id: Cleaning job ID.
        status: New status.
        summary: Job summary (if completed).
        error_message: Error message (if failed).
    """
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(table_name)
    now = datetime.now(timezone.utc).isoformat()

    update_expr = "SET #s = :status, completedAt = :ca"
    expr_values: dict[str, Any] = {
        ":status": status,
        ":ca": now,
    }
    expr_names = {"#s": "status"}

    if summary:
        update_expr += ", summary = :summary"
        expr_values[":summary"] = summary

    if error_message:
        update_expr += ", errorMessage = :em"
        expr_values[":em"] = error_message

    try:
        table.update_item(
            Key={"PK": f"CLEANING#{job_id}", "SK": "METADATA"},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
        )
        logger.info(f"Updated job {job_id} status to {status}")
    except ClientError as e:
        logger.error(f"Failed to update job status: {e}")


if __name__ == "__main__":
    main()
