"""Glue Python Shell script for executing validation rules.

This script is executed as an AWS Glue Python Shell job.
It performs the following workflow:
1. Load dataset from S3 (CSV/Parquet via pandas)
2. Parse rules configuration from job arguments
3. For each rule: load rule script from S3, execute against each record
4. Write per-record results to DynamoDB in batches of 25
5. Compute quality score: (passed/total) * 100
6. Store run summary in the validation runs table

Job Arguments:
- --RUN_ID: The validation run identifier
- --DATASET_S3_PATH: S3 path to the dataset file
- --RULES_JSON: JSON array of rules with script S3 keys
- --RESULTS_TABLE: DynamoDB table for per-record results
- --RAW_BUCKET: S3 bucket for raw datasets
- --SCRIPTS_BUCKET: S3 bucket for rule scripts

Requirements: 10.1, 10.2, 10.3
"""

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS region
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# DynamoDB batch write size limit
BATCH_SIZE = 25


def main():
    """Main entry point for the Glue validation job."""
    from awsglue.utils import getResolvedOptions

    # Parse job arguments
    args = getResolvedOptions(sys.argv, [
        "RUN_ID",
        "DATASET_S3_PATH",
        "RULES_JSON",
        "RESULTS_TABLE",
        "RAW_BUCKET",
        "SCRIPTS_BUCKET",
    ])

    run_id = args["RUN_ID"]
    dataset_s3_path = args["DATASET_S3_PATH"]
    rules_json = args["RULES_JSON"]
    results_table = args.get("RESULTS_TABLE", "dq-validation-results")
    raw_bucket = args.get("RAW_BUCKET", "dq-raw-108782054634")
    scripts_bucket = args.get("SCRIPTS_BUCKET", "dq-scripts-108782054634")
    runs_table = os.environ.get("VALIDATION_RUNS_TABLE", "dq-validation-runs")

    logger.info(f"Starting validation job for run: {run_id}")
    logger.info(f"Dataset path: {dataset_s3_path}")

    # Parse rules
    try:
        rules = json.loads(rules_json)
        logger.info(f"Loaded {len(rules)} rules")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse RULES_JSON: {e}")
        _update_run_status(runs_table, run_id, "failed", error_message=str(e))
        sys.exit(1)

    # Load dataset from S3
    try:
        df = _load_dataset(raw_bucket, dataset_s3_path)
        logger.info(f"Loaded dataset with {len(df)} records and {len(df.columns)} columns")
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        _update_run_status(runs_table, run_id, "failed", error_message=f"Dataset load error: {e}")
        sys.exit(1)

    # Execute rules against each record
    total_evaluations = 0
    passed_evaluations = 0
    failed_evaluations = 0
    error_evaluations = 0
    results_buffer: list[dict[str, Any]] = []

    s3_client = boto3.client("s3", region_name=AWS_REGION)

    for rule in rules:
        rule_id = rule.get("id", "unknown")
        rule_name = rule.get("name", "unnamed")
        script_s3_key = rule.get("scriptS3Key", "")

        if not script_s3_key:
            logger.warning(f"Rule {rule_id} has no script S3 key, skipping")
            continue

        # Load rule script from S3
        try:
            script_code = _load_rule_script(s3_client, scripts_bucket, script_s3_key)
        except Exception as e:
            logger.error(f"Failed to load script for rule {rule_id}: {e}")
            continue

        # Compile rule function
        try:
            rule_func = _compile_rule_function(script_code)
        except Exception as e:
            logger.error(f"Failed to compile script for rule {rule_id}: {e}")
            continue

        # Execute rule against each record
        for idx, row in df.iterrows():
            total_evaluations += 1
            record_dict = row.to_dict()

            try:
                result = rule_func(record_dict)
                passed = bool(result) if result is not None else False

                if passed:
                    passed_evaluations += 1
                else:
                    failed_evaluations += 1

                result_item = {
                    "PK": f"RUN#{run_id}",
                    "SK": f"RECORD#{idx}#RULE#{rule_id}",
                    "runId": run_id,
                    "recordId": str(idx),
                    "ruleId": rule_id,
                    "ruleName": rule_name,
                    "passed": passed,
                    "message": "" if passed else "Rule condition not met",
                    "fieldValues": {k: str(v) for k, v in record_dict.items()},
                    "evaluatedAt": datetime.now(timezone.utc).isoformat(),
                }

                results_buffer.append(result_item)

                # Flush buffer in batches
                if len(results_buffer) >= BATCH_SIZE:
                    _batch_write_results(results_table, results_buffer)
                    results_buffer = []

            except Exception as e:
                error_evaluations += 1
                logger.warning(
                    f"Error executing rule {rule_id} on record {idx}: {e}"
                )

                result_item = {
                    "PK": f"RUN#{run_id}",
                    "SK": f"RECORD#{idx}#RULE#{rule_id}",
                    "runId": run_id,
                    "recordId": str(idx),
                    "ruleId": rule_id,
                    "ruleName": rule_name,
                    "passed": False,
                    "message": f"Execution error: {str(e)}",
                    "fieldValues": {k: str(v) for k, v in record_dict.items()},
                    "evaluatedAt": datetime.now(timezone.utc).isoformat(),
                }
                results_buffer.append(result_item)

                if len(results_buffer) >= BATCH_SIZE:
                    _batch_write_results(results_table, results_buffer)
                    results_buffer = []

    # Flush remaining results
    if results_buffer:
        _batch_write_results(results_table, results_buffer)

    # Compute quality score
    quality_score = 0.0
    if total_evaluations > 0:
        quality_score = round((passed_evaluations / total_evaluations) * 100, 2)

    # Store run summary
    summary = {
        "totalRecords": len(df),
        "totalEvaluations": total_evaluations,
        "passed": passed_evaluations,
        "failed": failed_evaluations,
        "errors": error_evaluations,
        "qualityScore": quality_score,
        "rulesExecuted": len(rules),
    }

    logger.info(f"Validation complete. Score: {quality_score}%, "
                f"Passed: {passed_evaluations}, Failed: {failed_evaluations}, "
                f"Errors: {error_evaluations}")

    _update_run_status(runs_table, run_id, "completed", score=quality_score, summary=summary)


def _load_dataset(bucket: str, s3_path: str) -> pd.DataFrame:
    """Load a dataset from S3 (CSV or Parquet).

    Args:
        bucket: S3 bucket name.
        s3_path: S3 object key for the dataset.

    Returns:
        Loaded DataFrame.
    """
    s3_uri = f"s3://{bucket}/{s3_path}"

    if s3_path.endswith(".parquet"):
        return pd.read_parquet(s3_uri)
    else:
        return pd.read_csv(s3_uri)


def _load_rule_script(s3_client: Any, bucket: str, key: str) -> str:
    """Load a rule script from S3.

    Args:
        s3_client: boto3 S3 client.
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        The script source code as a string.
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _compile_rule_function(script_code: str) -> Any:
    """Compile a rule script and extract the validation function.

    The script must define a function named `validate_record(record: dict) -> bool`.

    Args:
        script_code: Python source code of the rule.

    Returns:
        The validate_record function.

    Raises:
        ValueError: If the script doesn't define validate_record.
    """
    namespace: dict[str, Any] = {}
    exec(script_code, namespace)

    if "validate_record" not in namespace:
        raise ValueError("Rule script must define a 'validate_record' function")

    return namespace["validate_record"]


def _batch_write_results(table_name: str, items: list[dict[str, Any]]) -> None:
    """Write results to DynamoDB in batches of 25.

    Args:
        table_name: DynamoDB table name.
        items: List of items to write.
    """
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(table_name)

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        with table.batch_writer() as writer:
            for item in batch:
                writer.put_item(Item=item)

    logger.debug(f"Wrote {len(items)} results to {table_name}")


def _update_run_status(
    table_name: str,
    run_id: str,
    status: str,
    score: float = None,
    summary: dict = None,
    error_message: str = None,
) -> None:
    """Update the validation run status in DynamoDB.

    Args:
        table_name: DynamoDB table name.
        run_id: Validation run ID.
        status: New status (completed, failed).
        score: Quality score (if completed).
        summary: Run summary dict (if completed).
        error_message: Error message (if failed).
    """
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(table_name)
    now = datetime.now(timezone.utc).isoformat()

    update_expr = "SET #s = :status, completedAt = :ca, GSI1PK = :gsi"
    expr_values: dict[str, Any] = {
        ":status": status,
        ":ca": now,
        ":gsi": status,
    }
    expr_names = {"#s": "status"}

    if score is not None:
        update_expr += ", score = :score"
        expr_values[":score"] = score

    if summary:
        update_expr += ", summary = :summary"
        expr_values[":summary"] = summary

    if error_message:
        update_expr += ", errorMessage = :em"
        expr_values[":em"] = error_message

    try:
        table.update_item(
            Key={"PK": f"VALIDATION#{run_id}", "SK": "METADATA"},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
        )
        logger.info(f"Updated run {run_id} status to {status}")
    except ClientError as e:
        logger.error(f"Failed to update run status: {e}")


if __name__ == "__main__":
    main()
