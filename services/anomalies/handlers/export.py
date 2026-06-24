"""Anomaly Export Lambda handler.

Handles HTTP API routes for exporting anomaly results:
- GET /anomalies/scoring/{id}/export → generate CSV of anomalous records

Queries anomalous records from DynamoDB, generates a CSV file,
uploads to S3, and returns a presigned URL (60 min validity).

DynamoDB Table: dq-anomaly-scores
S3 Bucket: dq-exports-108782054634

Requirements: 13.4, 13.5, 13.6
"""

from __future__ import annotations

import csv
import io
import logging
import os
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
EXPORTS_BUCKET = os.environ.get("EXPORTS_BUCKET", "dq-exports-108782054634")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Presigned URL expiration: 60 minutes
PRESIGNED_URL_EXPIRATION = 3600


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for anomaly export.

    Routes:
    - GET /anomalies/scoring/{id}/export → export anomalous records as CSV

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

        # Extract scoring ID from path
        path = event.get("rawPath", "") or event.get("path", "")
        scoring_id = _extract_scoring_id(path)

        if not scoring_id:
            return validation_error(
                message="Scoring ID is required in the path.",
                request_id=request_id,
            )

        return _export_anomalies(event, scoring_id, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in export handler: {e}")
        return internal_error(
            message="An unexpected error occurred while exporting anomaly results.",
            request_id=request_id,
        )


def _extract_scoring_id(path: str) -> Optional[str]:
    """Extract scoring ID from path /anomalies/scoring/{id}/export."""
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /anomalies/scoring/{id}/export
    if len(parts) >= 4 and parts[0] == "anomalies" and parts[1] == "scoring" and parts[3] == "export":
        return parts[2]

    return None


def _export_anomalies(
    event: dict[str, Any], scoring_id: str, request_id: str
) -> dict[str, Any]:
    """Export anomalous records as CSV and return a presigned download URL.

    Args:
        event: API Gateway event.
        scoring_id: The scoring job ID.
        request_id: The request ID.

    Returns:
        Response with presigned URL for the exported CSV.
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
            message="You do not have permission to export anomaly results.",
            request_id=request_id,
        )

    # Verify scoring job exists
    db = DynamoHelper(SCORING_TABLE)
    metadata = db.get_item(pk=f"SCORING#{scoring_id}", sk="METADATA")

    if metadata is None:
        return not_found_error(
            message=f"Scoring job '{scoring_id}' not found.",
            details={"scoringId": scoring_id},
            request_id=request_id,
        )

    if metadata.get("status") != "completed":
        return validation_error(
            message=f"Scoring job is not complete. Status: {metadata.get('status')}",
            details={"scoringId": scoring_id, "status": metadata.get("status")},
            request_id=request_id,
        )

    # Query all anomalous records for this scoring job
    from boto3.dynamodb.conditions import Attr

    anomalous_records: list[dict[str, Any]] = []
    next_token: Optional[str] = None

    while True:
        from services.shared.pagination import PaginationParams
        pagination = PaginationParams(page_size=100, next_token=next_token)
        result = db.query(
            pk_value=f"SCORING#{scoring_id}",
            filter_expression=Attr("isAnomaly").eq(True),
            pagination=pagination,
        )
        anomalous_records.extend(result.get("items", []))
        next_token = result.get("next_token")
        if not next_token:
            break

    if not anomalous_records:
        return success_response({
            "scoringId": scoring_id,
            "message": "No anomalous records found.",
            "recordCount": 0,
            "downloadUrl": None,
        })

    # Generate CSV
    csv_content = _generate_csv(anomalous_records)

    # Upload to S3
    now = datetime.now(timezone.utc)
    s3_key = f"exports/anomalies/{scoring_id}/{now.strftime('%Y%m%d_%H%M%S')}_anomalies.csv"

    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_client.put_object(
            Bucket=EXPORTS_BUCKET,
            Key=s3_key,
            Body=csv_content.encode("utf-8"),
            ContentType="text/csv",
            Metadata={
                "scoringId": scoring_id,
                "exportedBy": claims.user_id,
                "exportedAt": now.isoformat(),
            },
        )
        logger.info(f"Exported CSV to s3://{EXPORTS_BUCKET}/{s3_key}")
    except ClientError as e:
        logger.error(f"Failed to upload export CSV: {e}")
        return internal_error(
            message="Failed to upload export file.",
            request_id=request_id,
        )

    # Generate presigned URL (60 min validity)
    try:
        download_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": EXPORTS_BUCKET, "Key": s3_key},
            ExpiresIn=PRESIGNED_URL_EXPIRATION,
        )
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        return internal_error(
            message="Failed to generate download URL.",
            request_id=request_id,
        )

    return success_response({
        "scoringId": scoring_id,
        "recordCount": len(anomalous_records),
        "downloadUrl": download_url,
        "expiresIn": PRESIGNED_URL_EXPIRATION,
        "s3Key": s3_key,
    })


def _generate_csv(records: list[dict[str, Any]]) -> str:
    """Generate CSV content from anomalous records.

    CSV columns: recordId, reconstructionError, severity, field values...

    Args:
        records: List of anomalous record items.

    Returns:
        CSV content as a string.
    """
    output = io.StringIO()

    # Determine field columns from first record
    field_columns: list[str] = []
    if records:
        sample_fields = records[0].get("fieldValues", {})
        field_columns = sorted(sample_fields.keys())

    # Write header
    headers = ["recordId", "reconstructionError", "severity"] + field_columns
    writer = csv.writer(output)
    writer.writerow(headers)

    # Write data rows
    for record in records:
        row = [
            record.get("recordId", ""),
            record.get("reconstructionError", ""),
            record.get("severity", ""),
        ]
        field_values = record.get("fieldValues", {})
        for col in field_columns:
            row.append(field_values.get(col, ""))
        writer.writerow(row)

    return output.getvalue()
