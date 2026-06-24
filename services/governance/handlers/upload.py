"""Dataset upload handler for the Governance Service.

Handles multipart upload lifecycle for CSV and Parquet files:
- POST /upload/initiate         → Initiate multipart upload
- POST /upload/{id}/complete    → Complete multipart upload
- POST /upload/{id}/abort       → Abort upload and clean up
- GET  /dataset/{id}/preview    → Read first 100 rows, infer types

Validation constraints:
- Allowed file types: CSV, Parquet
- Maximum file size: 500 MB

S3 bucket: dq-raw-108782054634
S3 prefix: raw/

DynamoDB table: dq-catalogs (dataset metadata stored as items)

Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import ulid
from datetime import datetime, timezone
from typing import Any, Optional

from services.shared.auth import (
    extract_user_claims,
    get_request_id,
    require_role,
    ADMIN_ROLE,
    ANALYST_ROLE,
)
from services.shared.audit import create_audit_record
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    build_error_response,
    ErrorCode,
    internal_error,
    not_found_error,
    success_response,
    validation_error,
)
from services.shared.s3_helper import (
    S3Helper,
    calculate_num_parts,
    get_content_type,
    validate_upload_file,
    MULTIPART_CHUNK_SIZE,
)

logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_RAW_BUCKET", "dq-raw-108782054634")
S3_RAW_PREFIX = "raw/"
CATALOGS_TABLE = os.environ.get("CATALOGS_TABLE_NAME", "dq-catalogs")

# Preview settings
PREVIEW_MAX_ROWS = 100


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for dataset upload operations.

    Routes:
    - POST /catalog/{id}/upload → initiate_upload
    - POST /upload/{uploadId}/complete → complete_upload
    - POST /upload/{uploadId}/abort → abort_upload

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)
    http_method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "") or event.get("path", "")

    try:
        # Route based on path pattern
        if http_method == "GET" and "/dataset/" in path and "/preview" in path:
            return _handle_dataset_preview(event, request_id)
        elif "/upload/" in path and path.endswith("/complete"):
            return _handle_complete_upload(event, request_id)
        elif "/upload/" in path and path.endswith("/abort"):
            return _handle_abort_upload(event, request_id)
        elif "/upload/initiate" in path or ("/catalog/" in path and path.endswith("/upload")):
            return _handle_initiate_upload(event, request_id)
        else:
            return validation_error(
                message="Unknown upload route",
                details={"path": path, "method": http_method},
                request_id=request_id,
            )
    except Exception as e:
        logger.exception(f"Unhandled error in upload handler: {e}")
        return internal_error(
            message="An unexpected error occurred during upload operation",
            details={"error": str(e)},
            request_id=request_id,
        )


# ─── Upload Initiation ────────────────────────────────────────────────────


def _handle_initiate_upload(
    event: dict[str, Any], request_id: str
) -> dict[str, Any]:
    """Initiate a multipart upload for a dataset file.

    Validates:
    - File type (CSV or Parquet)
    - File size (≤ 500 MB)
    - Catalog exists

    Generates presigned URLs for each upload part.

    Args:
        event: API Gateway event.
        request_id: Request ID.

    Returns:
        Response with uploadId, presigned URLs, and part size.
    """
    # Authenticate (both roles can upload)
    claims, error = require_role(
        event, [ADMIN_ROLE, ANALYST_ROLE], request_id
    )
    if error:
        return error

    # Parse request body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required",
            request_id=request_id,
        )

    # Extract and validate required fields
    file_name = body.get("fileName")
    file_size = body.get("fileSize")
    file_type = body.get("fileType")

    if not file_name:
        return validation_error(
            message="fileName is required",
            details={"missingFields": ["fileName"]},
            request_id=request_id,
        )

    if file_size is None:
        return validation_error(
            message="fileSize is required",
            details={"missingFields": ["fileSize"]},
            request_id=request_id,
        )

    try:
        file_size = int(file_size)
    except (ValueError, TypeError):
        return validation_error(
            message="fileSize must be a valid integer (bytes)",
            request_id=request_id,
        )

    # Validate file using shared s3_helper
    is_valid, error_message = validate_upload_file(file_name, file_size)
    if not is_valid:
        return validation_error(
            message=error_message,
            details={"fileName": file_name, "fileSize": file_size},
            request_id=request_id,
        )

    # Extract catalog ID from path
    catalog_id = _extract_catalog_id(event)
    if not catalog_id:
        return validation_error(
            message="Catalog ID is required in path",
            request_id=request_id,
        )

    # Verify catalog exists
    dynamo = DynamoHelper(CATALOGS_TABLE, region=AWS_REGION)
    catalog = dynamo.get_item(pk=f"CATALOG#{catalog_id}", sk="METADATA")
    if not catalog:
        return not_found_error(
            message=f"Catalog '{catalog_id}' not found",
            details={"catalogId": catalog_id},
            request_id=request_id,
        )

    # Generate dataset ID and S3 key
    dataset_id = str(ulid.new())
    s3_key = f"{S3_RAW_PREFIX}{catalog_id}/{dataset_id}/{file_name}"
    content_type = get_content_type(file_name)

    # Initiate multipart upload
    s3 = S3Helper(bucket=S3_BUCKET, region=AWS_REGION)
    upload_id = s3.initiate_multipart_upload(
        key=s3_key,
        content_type=content_type,
        metadata={
            "catalog-id": catalog_id,
            "dataset-id": dataset_id,
            "uploaded-by": claims.user_id,
        },
    )

    # Calculate number of parts
    num_parts = calculate_num_parts(file_size, MULTIPART_CHUNK_SIZE)

    # Generate presigned URLs for each part
    presigned_urls = s3.generate_presigned_part_urls(
        key=s3_key,
        upload_id=upload_id,
        num_parts=num_parts,
    )

    # Store upload metadata in DynamoDB
    now = datetime.now(timezone.utc).isoformat()
    upload_metadata = {
        "PK": f"UPLOAD#{upload_id}",
        "SK": "METADATA",
        "uploadId": upload_id,
        "datasetId": dataset_id,
        "catalogId": catalog_id,
        "fileName": file_name,
        "fileSize": file_size,
        "fileType": file_type or file_name.rsplit(".", 1)[-1].lower(),
        "s3Key": s3_key,
        "s3Bucket": S3_BUCKET,
        "status": "in_progress",
        "uploadedBy": claims.user_id,
        "createdAt": now,
        "updatedAt": now,
        "numParts": num_parts,
        "partSize": MULTIPART_CHUNK_SIZE,
    }
    dynamo.put_item(upload_metadata)

    logger.info(
        f"Initiated multipart upload: uploadId={upload_id}, "
        f"file={file_name}, parts={num_parts}, catalog={catalog_id}"
    )

    return success_response(
        body={
            "uploadId": upload_id,
            "datasetId": dataset_id,
            "presignedUrls": presigned_urls,
            "partSize": MULTIPART_CHUNK_SIZE,
            "numParts": num_parts,
            "s3Key": s3_key,
        },
        status_code=201,
    )


# ─── Upload Completion ────────────────────────────────────────────────────


def _handle_complete_upload(
    event: dict[str, Any], request_id: str
) -> dict[str, Any]:
    """Complete a multipart upload and trigger preview generation.

    After completing the S3 multipart upload, generates a preview
    containing the first 100 rows and inferred column types.

    Args:
        event: API Gateway event.
        request_id: Request ID.

    Returns:
        Response with dataset metadata and preview.
    """
    # Authenticate
    claims, error = require_role(
        event, [ADMIN_ROLE, ANALYST_ROLE], request_id
    )
    if error:
        return error

    # Parse body with parts info
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required with completed parts",
            request_id=request_id,
        )

    parts = body.get("parts")
    if not parts or not isinstance(parts, list):
        return validation_error(
            message="'parts' array is required with ETag and PartNumber for each part",
            request_id=request_id,
        )

    # Extract upload ID from path
    upload_id = _extract_upload_id(event)
    if not upload_id:
        return validation_error(
            message="Upload ID is required in path",
            request_id=request_id,
        )

    # Retrieve upload metadata
    dynamo = DynamoHelper(CATALOGS_TABLE, region=AWS_REGION)
    upload_meta = dynamo.get_item(pk=f"UPLOAD#{upload_id}", sk="METADATA")
    if not upload_meta:
        return not_found_error(
            message=f"Upload '{upload_id}' not found",
            details={"uploadId": upload_id},
            request_id=request_id,
        )

    if upload_meta.get("status") != "in_progress":
        return validation_error(
            message=f"Upload '{upload_id}' is not in progress (status: {upload_meta.get('status')})",
            request_id=request_id,
        )

    s3_key = upload_meta["s3Key"]
    s3 = S3Helper(bucket=S3_BUCKET, region=AWS_REGION)

    # Complete multipart upload in S3
    formatted_parts = [
        {"ETag": p["ETag"], "PartNumber": int(p["PartNumber"])}
        for p in parts
    ]
    try:
        s3.complete_multipart_upload(
            key=s3_key,
            upload_id=upload_id,
            parts=formatted_parts,
        )
    except Exception as e:
        logger.error(f"Failed to complete multipart upload: {e}")
        return internal_error(
            message="Failed to complete file upload in S3",
            details={"uploadId": upload_id, "error": str(e)},
            request_id=request_id,
        )

    # Generate preview (first 100 rows + inferred column types)
    preview = _generate_preview(s3, s3_key, upload_meta.get("fileType", "csv"))

    # Store dataset metadata in DynamoDB
    now = datetime.now(timezone.utc).isoformat()
    dataset_id = upload_meta["datasetId"]
    catalog_id = upload_meta["catalogId"]

    dataset_item = {
        "PK": f"CATALOG#{catalog_id}",
        "SK": f"DATASET#{dataset_id}",
        "datasetId": dataset_id,
        "catalogId": catalog_id,
        "fileName": upload_meta["fileName"],
        "fileSize": upload_meta["fileSize"],
        "fileType": upload_meta["fileType"],
        "s3Key": s3_key,
        "s3Bucket": S3_BUCKET,
        "status": "uploaded",
        "uploadedBy": claims.user_id,
        "createdAt": upload_meta["createdAt"],
        "completedAt": now,
        "preview": preview,
    }
    dynamo.put_item(dataset_item)

    # Update upload status to completed
    dynamo.update_item(
        pk=f"UPLOAD#{upload_id}",
        sk="METADATA",
        update_expression="SET #s = :status, updatedAt = :now, completedAt = :now",
        expression_values={":status": "completed", ":now": now},
        expression_names={"#s": "status"},
    )

    # Create audit record for dataset upload
    create_audit_record(
        user_id=claims.user_id,
        action_type="create",
        resource_type="dataset",
        resource_id=dataset_id,
        details={
            "catalogId": catalog_id,
            "fileName": upload_meta["fileName"],
            "fileSize": upload_meta["fileSize"],
            "fileType": upload_meta["fileType"],
            "s3Key": s3_key,
        },
    )

    logger.info(
        f"Upload completed: uploadId={upload_id}, datasetId={dataset_id}, "
        f"file={upload_meta['fileName']}"
    )

    return success_response(
        body={
            "datasetId": dataset_id,
            "catalogId": catalog_id,
            "fileName": upload_meta["fileName"],
            "fileSize": upload_meta["fileSize"],
            "fileType": upload_meta["fileType"],
            "s3Key": s3_key,
            "status": "uploaded",
            "completedAt": now,
            "preview": preview,
        },
        status_code=200,
    )


# ─── Upload Abort ─────────────────────────────────────────────────────────


def _handle_abort_upload(
    event: dict[str, Any], request_id: str
) -> dict[str, Any]:
    """Abort a multipart upload and clean up partial S3 objects.

    Args:
        event: API Gateway event.
        request_id: Request ID.

    Returns:
        Response confirming abort.
    """
    # Authenticate
    claims, error = require_role(
        event, [ADMIN_ROLE, ANALYST_ROLE], request_id
    )
    if error:
        return error

    # Extract upload ID from path
    upload_id = _extract_upload_id(event)
    if not upload_id:
        return validation_error(
            message="Upload ID is required in path",
            request_id=request_id,
        )

    # Retrieve upload metadata
    dynamo = DynamoHelper(CATALOGS_TABLE, region=AWS_REGION)
    upload_meta = dynamo.get_item(pk=f"UPLOAD#{upload_id}", sk="METADATA")
    if not upload_meta:
        return not_found_error(
            message=f"Upload '{upload_id}' not found",
            details={"uploadId": upload_id},
            request_id=request_id,
        )

    if upload_meta.get("status") != "in_progress":
        return validation_error(
            message=f"Upload '{upload_id}' cannot be aborted (status: {upload_meta.get('status')})",
            request_id=request_id,
        )

    s3_key = upload_meta["s3Key"]
    s3 = S3Helper(bucket=S3_BUCKET, region=AWS_REGION)

    # Abort the multipart upload in S3 (cleans up partial parts)
    try:
        s3.abort_multipart_upload(key=s3_key, upload_id=upload_id)
    except Exception as e:
        logger.warning(
            f"Error aborting multipart upload in S3 (may already be aborted): {e}"
        )

    # Update upload status to aborted
    now = datetime.now(timezone.utc).isoformat()
    dynamo.update_item(
        pk=f"UPLOAD#{upload_id}",
        sk="METADATA",
        update_expression="SET #s = :status, updatedAt = :now, abortedAt = :now",
        expression_values={":status": "aborted", ":now": now},
        expression_names={"#s": "status"},
    )

    logger.info(
        f"Upload aborted: uploadId={upload_id}, file={upload_meta.get('fileName')}"
    )

    return success_response(
        body={
            "uploadId": upload_id,
            "status": "aborted",
            "message": "Upload aborted and partial objects cleaned up",
        },
        status_code=200,
    )


# ─── Dataset Preview ───────────────────────────────────────────────────


def _handle_dataset_preview(
    event: dict[str, Any], request_id: str
) -> dict[str, Any]:
    """Get a preview of a dataset (first 100 rows with inferred column types).

    Route: GET /dataset/{id}/preview

    Args:
        event: API Gateway event.
        request_id: Request ID.

    Returns:
        Response with rows, columns, and inferred column types.
    """
    # Authenticate (both roles can read)
    claims, error = require_role(
        event, [ADMIN_ROLE, ANALYST_ROLE], request_id
    )
    if error:
        return error

    # Extract dataset ID from path
    dataset_id = _extract_dataset_id(event)
    if not dataset_id:
        return validation_error(
            message="Dataset ID is required in path",
            request_id=request_id,
        )

    # Find the dataset in DynamoDB (scan for it by datasetId)
    dynamo = DynamoHelper(CATALOGS_TABLE, region=AWS_REGION)

    from boto3.dynamodb.conditions import Attr
    result = dynamo.scan(
        filter_expression=Attr("datasetId").eq(dataset_id) & Attr("SK").begins_with("DATASET#"),
    )

    items = result.get("items", [])
    if not items:
        return not_found_error(
            message=f"Dataset '{dataset_id}' not found",
            details={"datasetId": dataset_id},
            request_id=request_id,
        )

    dataset_item = items[0]
    s3_key = dataset_item.get("s3Key", "")
    file_type = dataset_item.get("fileType", "csv")

    if not s3_key:
        return internal_error(
            message="Dataset has no S3 key reference.",
            request_id=request_id,
        )

    # Generate preview from S3
    s3 = S3Helper(bucket=S3_BUCKET, region=AWS_REGION)
    preview = _generate_preview(s3, s3_key, file_type)

    return success_response(
        body={
            "datasetId": dataset_id,
            "fileName": dataset_item.get("fileName", ""),
            "fileType": file_type,
            "preview": preview,
        },
        status_code=200,
    )


def _extract_dataset_id(event: dict[str, Any]) -> Optional[str]:
    """Extract dataset ID from path parameters or path.

    Path pattern: /dataset/{id}/preview

    Args:
        event: API Gateway event.

    Returns:
        Dataset ID or None.
    """
    path_params = event.get("pathParameters") or {}
    dataset_id = path_params.get("id") or path_params.get("datasetId")
    if dataset_id:
        return dataset_id

    # Fallback: parse from path
    path = event.get("rawPath", "") or event.get("path", "")
    parts = path.strip("/").split("/")
    try:
        idx = parts.index("dataset")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass

    return None


# ─── Preview Generation ───────────────────────────────────────────────────


def _generate_preview(
    s3: S3Helper, s3_key: str, file_type: str
) -> dict[str, Any]:
    """Generate a preview of the uploaded dataset.

    Reads the first 100 rows and infers column types.

    Args:
        s3: S3Helper instance.
        s3_key: The S3 object key.
        file_type: File type ('csv' or 'parquet').

    Returns:
        Preview dict with rows, columns, and inferred types.
    """
    try:
        if file_type == "parquet":
            return _generate_parquet_preview(s3, s3_key)
        else:
            return _generate_csv_preview(s3, s3_key)
    except Exception as e:
        logger.error(f"Failed to generate preview for {s3_key}: {e}")
        return {
            "rows": [],
            "columns": [],
            "columnTypes": {},
            "totalPreviewRows": 0,
            "error": f"Preview generation failed: {str(e)}",
        }


def _generate_csv_preview(s3: S3Helper, s3_key: str) -> dict[str, Any]:
    """Generate preview from a CSV file (first 100 rows).

    Uses streaming to avoid loading the entire file into memory.

    Args:
        s3: S3Helper instance.
        s3_key: S3 object key.

    Returns:
        Preview dict with rows, columns, and inferred types.
    """
    # Download file content (for large files, we'd use range requests,
    # but for preview we read enough to get 100 rows)
    file_bytes = s3.download_file(s3_key)
    text = file_bytes.decode("utf-8", errors="replace")

    # Parse CSV
    reader = csv.DictReader(io.StringIO(text))
    columns = reader.fieldnames or []

    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= PREVIEW_MAX_ROWS:
            break
        rows.append(dict(row))

    # Infer column types from the preview data
    column_types = _infer_column_types(rows, columns)

    return {
        "rows": rows,
        "columns": list(columns),
        "columnTypes": column_types,
        "totalPreviewRows": len(rows),
    }


def _generate_parquet_preview(s3: S3Helper, s3_key: str) -> dict[str, Any]:
    """Generate preview from a Parquet file (first 100 rows).

    Uses pandas for Parquet reading if available, otherwise returns
    a limited preview.

    Args:
        s3: S3Helper instance.
        s3_key: S3 object key.

    Returns:
        Preview dict with rows, columns, and inferred types.
    """
    try:
        import pandas as pd

        file_bytes = s3.download_file(s3_key)
        buffer = io.BytesIO(file_bytes)
        df = pd.read_parquet(buffer)

        # Take first 100 rows
        preview_df = df.head(PREVIEW_MAX_ROWS)
        columns = list(preview_df.columns)

        # Convert to list of dicts
        rows = preview_df.astype(str).to_dict(orient="records")

        # Map pandas dtypes to simple type names
        column_types = {}
        for col in columns:
            dtype = str(df[col].dtype)
            column_types[col] = _map_pandas_dtype(dtype)

        return {
            "rows": rows,
            "columns": columns,
            "columnTypes": column_types,
            "totalPreviewRows": len(rows),
        }
    except ImportError:
        logger.warning("pandas not available; falling back to metadata-only preview")
        return {
            "rows": [],
            "columns": [],
            "columnTypes": {},
            "totalPreviewRows": 0,
            "error": "Parquet preview requires pandas library",
        }


def _infer_column_types(
    rows: list[dict[str, str]], columns: list[str]
) -> dict[str, str]:
    """Infer column types from CSV preview rows.

    Analyzes sample values to determine likely data types:
    - integer: All non-empty values are valid integers
    - float: All non-empty values are valid floats
    - boolean: All non-empty values are true/false/yes/no/0/1
    - date: Values match common date patterns
    - string: Default fallback

    Args:
        rows: List of row dicts.
        columns: Column names.

    Returns:
        Dict mapping column name to inferred type string.
    """
    column_types: dict[str, str] = {}

    for col in columns:
        values = [row.get(col, "") for row in rows if row.get(col, "").strip()]

        if not values:
            column_types[col] = "string"
            continue

        column_types[col] = _infer_type_from_values(values)

    return column_types


def _infer_type_from_values(values: list[str]) -> str:
    """Infer the data type from a sample of string values.

    Args:
        values: Non-empty string values from a column.

    Returns:
        Inferred type name.
    """
    # Check boolean
    boolean_values = {"true", "false", "yes", "no", "0", "1"}
    if all(v.lower().strip() in boolean_values for v in values):
        return "boolean"

    # Check integer
    try:
        for v in values:
            int(v.strip())
        return "integer"
    except ValueError:
        pass

    # Check float
    try:
        for v in values:
            float(v.strip())
        return "float"
    except ValueError:
        pass

    # Check date patterns (ISO 8601 and common formats)
    if _looks_like_dates(values):
        return "date"

    return "string"


def _looks_like_dates(values: list[str]) -> bool:
    """Check if values look like date strings.

    Args:
        values: Sample values to check.

    Returns:
        True if most values appear to be dates.
    """
    from datetime import datetime as dt

    date_formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
    ]

    date_count = 0
    for v in values[:20]:  # Sample first 20 for performance
        v = v.strip()
        for fmt in date_formats:
            try:
                dt.strptime(v, fmt)
                date_count += 1
                break
            except ValueError:
                continue

    # If 80%+ of sampled values match a date format
    return date_count >= len(values[:20]) * 0.8


def _map_pandas_dtype(dtype: str) -> str:
    """Map a pandas dtype string to a simple type name.

    Args:
        dtype: Pandas dtype as string (e.g., 'int64', 'float64').

    Returns:
        Simple type name.
    """
    dtype_lower = dtype.lower()
    if "int" in dtype_lower:
        return "integer"
    elif "float" in dtype_lower:
        return "float"
    elif "bool" in dtype_lower:
        return "boolean"
    elif "datetime" in dtype_lower:
        return "datetime"
    elif "object" in dtype_lower:
        return "string"
    else:
        return "string"


# ─── Utility Functions ────────────────────────────────────────────────────


def _parse_body(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse the JSON request body from an API Gateway event.

    Args:
        event: API Gateway event.

    Returns:
        Parsed body dict, or None if no/invalid body.
    """
    body_str = event.get("body")
    if not body_str:
        return None

    # Handle base64-encoded bodies
    if event.get("isBase64Encoded"):
        import base64

        body_str = base64.b64decode(body_str).decode("utf-8")

    try:
        return json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_catalog_id(event: dict[str, Any]) -> Optional[str]:
    """Extract catalog ID from path parameters or path.

    Path pattern: /catalog/{id}/upload

    Args:
        event: API Gateway event.

    Returns:
        Catalog ID or None.
    """
    # Try path parameters first (API Gateway v2)
    path_params = event.get("pathParameters") or {}
    catalog_id = path_params.get("id") or path_params.get("catalogId")
    if catalog_id:
        return catalog_id

    # Fallback: parse from path
    path = event.get("rawPath", "") or event.get("path", "")
    parts = path.strip("/").split("/")
    # Pattern: catalog/{id}/upload
    try:
        idx = parts.index("catalog")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass

    return None


def _extract_upload_id(event: dict[str, Any]) -> Optional[str]:
    """Extract upload ID from path parameters or path.

    Path pattern: /upload/{uploadId}/complete or /upload/{uploadId}/abort

    Args:
        event: API Gateway event.

    Returns:
        Upload ID or None.
    """
    # Try path parameters first
    path_params = event.get("pathParameters") or {}
    upload_id = path_params.get("uploadId")
    if upload_id:
        return upload_id

    # Fallback: parse from path
    path = event.get("rawPath", "") or event.get("path", "")
    parts = path.strip("/").split("/")
    # Pattern: upload/{uploadId}/complete or upload/{uploadId}/abort
    try:
        idx = parts.index("upload")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass

    return None
