"""S3 helper utilities for the Data Quality Platform.

Provides:
- File upload/download operations
- Presigned URL generation (upload and download)
- Multipart upload initiation, completion, and abort
- Content type detection

Bucket: dq-platform-storage-108782054634

Requirements: 4.1, 4.3, 4.5, 4.6
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DEFAULT_BUCKET = os.environ.get(
    "S3_STORAGE_BUCKET", "dq-platform-storage-108782054634"
)
PRESIGNED_URL_EXPIRATION = 3600  # 1 hour in seconds
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
MULTIPART_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB per part

# Allowed file types for dataset upload
ALLOWED_CONTENT_TYPES = {
    "csv": "text/csv",
    "parquet": "application/octet-stream",
}

ALLOWED_EXTENSIONS = {"csv", "parquet"}


class S3Helper:
    """High-level S3 operations wrapper for the Data Quality Platform."""

    def __init__(self, bucket: str = DEFAULT_BUCKET, region: str = AWS_REGION):
        """Initialize S3Helper.

        Args:
            bucket: The S3 bucket name.
            region: AWS region.
        """
        self._bucket = bucket
        self._region = region
        self._client = boto3.client("s3", region_name=region)

    @property
    def bucket(self) -> str:
        """Get the bucket name."""
        return self._bucket

    # ─── Upload Operations ────────────────────────────────────────────────

    def upload_file(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Upload a file to S3.

        Args:
            key: The S3 object key (path).
            body: File content as bytes.
            content_type: MIME type of the file.
            metadata: Optional metadata dict.

        Returns:
            S3 put_object response.

        Raises:
            ClientError: If upload fails.
        """
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if metadata:
            kwargs["Metadata"] = metadata

        try:
            response = self._client.put_object(**kwargs)
            logger.info(f"Uploaded file to s3://{self._bucket}/{key}")
            return response
        except ClientError as e:
            logger.error(f"Failed to upload to s3://{self._bucket}/{key}: {e}")
            raise

    def upload_fileobj(
        self,
        key: str,
        fileobj: Any,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload a file-like object to S3.

        Args:
            key: The S3 object key.
            fileobj: File-like object to upload.
            content_type: MIME type.

        Raises:
            ClientError: If upload fails.
        """
        try:
            self._client.upload_fileobj(
                Fileobj=fileobj,
                Bucket=self._bucket,
                Key=key,
                ExtraArgs={"ContentType": content_type},
            )
            logger.info(f"Uploaded fileobj to s3://{self._bucket}/{key}")
        except ClientError as e:
            logger.error(f"Failed to upload fileobj to s3://{self._bucket}/{key}: {e}")
            raise

    # ─── Download Operations ──────────────────────────────────────────────

    def download_file(self, key: str) -> bytes:
        """Download a file from S3.

        Args:
            key: The S3 object key.

        Returns:
            File content as bytes.

        Raises:
            ClientError: If download fails (e.g., key not found).
        """
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"].read()
            logger.debug(f"Downloaded s3://{self._bucket}/{key} ({len(body)} bytes)")
            return body
        except ClientError as e:
            logger.error(f"Failed to download s3://{self._bucket}/{key}: {e}")
            raise

    def get_object_metadata(self, key: str) -> Optional[dict[str, Any]]:
        """Get object metadata (head object).

        Args:
            key: The S3 object key.

        Returns:
            Object metadata dict, or None if not found.
        """
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
            return {
                "content_length": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", ""),
                "last_modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {}),
            }
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            raise

    # ─── Presigned URLs ───────────────────────────────────────────────────

    def generate_presigned_download_url(
        self,
        key: str,
        expiration: int = PRESIGNED_URL_EXPIRATION,
    ) -> str:
        """Generate a presigned URL for downloading a file.

        Args:
            key: The S3 object key.
            expiration: URL validity in seconds (default 1 hour).

        Returns:
            Presigned download URL.

        Raises:
            ClientError: If URL generation fails.
        """
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate download URL for {key}: {e}")
            raise

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiration: int = PRESIGNED_URL_EXPIRATION,
    ) -> str:
        """Generate a presigned URL for uploading a file (single-part upload).

        Args:
            key: The S3 object key.
            content_type: Expected content type.
            expiration: URL validity in seconds (default 1 hour).

        Returns:
            Presigned upload URL.

        Raises:
            ClientError: If URL generation fails.
        """
        try:
            url = self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate upload URL for {key}: {e}")
            raise

    # ─── Multipart Upload ─────────────────────────────────────────────────

    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> str:
        """Initiate a multipart upload.

        Args:
            key: The S3 object key.
            content_type: MIME type of the final object.
            metadata: Optional metadata.

        Returns:
            The upload ID for subsequent part uploads.

        Raises:
            ClientError: If initiation fails.
        """
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "ContentType": content_type,
        }
        if metadata:
            kwargs["Metadata"] = metadata

        try:
            response = self._client.create_multipart_upload(**kwargs)
            upload_id = response["UploadId"]
            logger.info(
                f"Initiated multipart upload for s3://{self._bucket}/{key}: {upload_id}"
            )
            return upload_id
        except ClientError as e:
            logger.error(f"Failed to initiate multipart upload for {key}: {e}")
            raise

    def generate_presigned_part_urls(
        self,
        key: str,
        upload_id: str,
        num_parts: int,
        expiration: int = PRESIGNED_URL_EXPIRATION,
    ) -> list[dict[str, Any]]:
        """Generate presigned URLs for each part of a multipart upload.

        Args:
            key: The S3 object key.
            upload_id: The multipart upload ID.
            num_parts: Number of parts to generate URLs for.
            expiration: URL validity in seconds.

        Returns:
            List of dicts with 'partNumber' and 'url'.

        Raises:
            ClientError: If URL generation fails.
        """
        urls = []
        for part_number in range(1, num_parts + 1):
            try:
                url = self._client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": self._bucket,
                        "Key": key,
                        "UploadId": upload_id,
                        "PartNumber": part_number,
                    },
                    ExpiresIn=expiration,
                )
                urls.append({"partNumber": part_number, "url": url})
            except ClientError as e:
                logger.error(
                    f"Failed to generate presigned URL for part {part_number}: {e}"
                )
                raise

        return urls

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Complete a multipart upload.

        Args:
            key: The S3 object key.
            upload_id: The multipart upload ID.
            parts: List of completed parts, each with 'ETag' and 'PartNumber'.

        Returns:
            S3 complete_multipart_upload response.

        Raises:
            ClientError: If completion fails.
        """
        try:
            response = self._client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            logger.info(
                f"Completed multipart upload for s3://{self._bucket}/{key}"
            )
            return response
        except ClientError as e:
            logger.error(f"Failed to complete multipart upload for {key}: {e}")
            raise

    def abort_multipart_upload(self, key: str, upload_id: str) -> dict[str, Any]:
        """Abort a multipart upload and clean up uploaded parts.

        Args:
            key: The S3 object key.
            upload_id: The multipart upload ID to abort.

        Returns:
            S3 abort response.

        Raises:
            ClientError: If abort fails.
        """
        try:
            response = self._client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
            )
            logger.info(
                f"Aborted multipart upload for s3://{self._bucket}/{key}: {upload_id}"
            )
            return response
        except ClientError as e:
            logger.error(f"Failed to abort multipart upload for {key}: {e}")
            raise

    # ─── Delete Operations ────────────────────────────────────────────────

    def delete_object(self, key: str) -> dict[str, Any]:
        """Delete an object from S3.

        Args:
            key: The S3 object key.

        Returns:
            S3 delete response.

        Raises:
            ClientError: If delete fails.
        """
        try:
            response = self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.info(f"Deleted s3://{self._bucket}/{key}")
            return response
        except ClientError as e:
            logger.error(f"Failed to delete s3://{self._bucket}/{key}: {e}")
            raise

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects with a given prefix.

        Args:
            prefix: The S3 key prefix to delete.

        Returns:
            Number of objects deleted.

        Raises:
            ClientError: If delete fails.
        """
        deleted_count = 0
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                objects = page.get("Contents", [])
                if not objects:
                    continue

                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": delete_keys},
                )
                deleted_count += len(delete_keys)

            logger.info(
                f"Deleted {deleted_count} objects with prefix "
                f"s3://{self._bucket}/{prefix}"
            )
            return deleted_count
        except ClientError as e:
            logger.error(f"Failed to delete prefix {prefix}: {e}")
            raise

    # ─── Copy Operations ──────────────────────────────────────────────────

    def copy_object(
        self,
        source_key: str,
        destination_key: str,
        source_bucket: Optional[str] = None,
    ) -> dict[str, Any]:
        """Copy an object within S3.

        Args:
            source_key: Source object key.
            destination_key: Destination object key.
            source_bucket: Source bucket (defaults to same bucket).

        Returns:
            S3 copy response.

        Raises:
            ClientError: If copy fails.
        """
        src_bucket = source_bucket or self._bucket
        try:
            response = self._client.copy_object(
                Bucket=self._bucket,
                Key=destination_key,
                CopySource={"Bucket": src_bucket, "Key": source_key},
            )
            logger.info(
                f"Copied s3://{src_bucket}/{source_key} → "
                f"s3://{self._bucket}/{destination_key}"
            )
            return response
        except ClientError as e:
            logger.error(f"Failed to copy {source_key} → {destination_key}: {e}")
            raise

    # ─── Utility Functions ────────────────────────────────────────────────

    def object_exists(self, key: str) -> bool:
        """Check if an object exists in S3.

        Args:
            key: The S3 object key.

        Returns:
            True if object exists, False otherwise.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise


# ─── Standalone Module-Level Functions ────────────────────────────────────


def generate_presigned_url(
    bucket: str,
    key: str,
    method: str = "get_object",
    expires_in: int = 3600,
) -> str:
    """Generate a presigned URL for an S3 object.

    Args:
        bucket: The S3 bucket name.
        key: The S3 object key.
        method: The S3 client method ('get_object' or 'put_object').
        expires_in: URL expiration in seconds (default 3600 = 1 hour).

    Returns:
        The presigned URL string.

    Raises:
        ClientError: If URL generation fails.
    """
    client = boto3.client("s3", region_name=AWS_REGION)
    try:
        url = client.generate_presigned_url(
            method,
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL for {bucket}/{key}: {e}")
        raise


def initiate_multipart_upload(
    bucket: str,
    key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Initiate a multipart upload and return the upload ID.

    Args:
        bucket: The S3 bucket name.
        key: The S3 object key.
        content_type: MIME type of the final object.

    Returns:
        The upload ID for subsequent part uploads.

    Raises:
        ClientError: If initiation fails.
    """
    client = boto3.client("s3", region_name=AWS_REGION)
    try:
        response = client.create_multipart_upload(
            Bucket=bucket,
            Key=key,
            ContentType=content_type,
        )
        upload_id = response["UploadId"]
        logger.info(f"Initiated multipart upload for s3://{bucket}/{key}: {upload_id}")
        return upload_id
    except ClientError as e:
        logger.error(f"Failed to initiate multipart upload for {bucket}/{key}: {e}")
        raise


def complete_multipart_upload(
    bucket: str,
    key: str,
    upload_id: str,
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Complete a multipart upload.

    Args:
        bucket: The S3 bucket name.
        key: The S3 object key.
        upload_id: The multipart upload ID.
        parts: List of completed parts, each with 'ETag' and 'PartNumber'.

    Returns:
        S3 complete_multipart_upload response.

    Raises:
        ClientError: If completion fails.
    """
    client = boto3.client("s3", region_name=AWS_REGION)
    try:
        response = client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        logger.info(f"Completed multipart upload for s3://{bucket}/{key}")
        return response
    except ClientError as e:
        logger.error(f"Failed to complete multipart upload for {bucket}/{key}: {e}")
        raise


def abort_multipart_upload(
    bucket: str,
    key: str,
    upload_id: str,
) -> dict[str, Any]:
    """Abort a multipart upload and clean up uploaded parts.

    Args:
        bucket: The S3 bucket name.
        key: The S3 object key.
        upload_id: The multipart upload ID to abort.

    Returns:
        S3 abort response.

    Raises:
        ClientError: If abort fails.
    """
    client = boto3.client("s3", region_name=AWS_REGION)
    try:
        response = client.abort_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
        )
        logger.info(f"Aborted multipart upload for s3://{bucket}/{key}: {upload_id}")
        return response
    except ClientError as e:
        logger.error(f"Failed to abort multipart upload for {bucket}/{key}: {e}")
        raise


def calculate_num_parts(file_size: int, chunk_size: int = MULTIPART_CHUNK_SIZE) -> int:
    """Calculate the number of parts needed for a multipart upload.

    Args:
        file_size: Total file size in bytes.
        chunk_size: Size of each part in bytes.

    Returns:
        Number of parts needed.
    """
    return (file_size + chunk_size - 1) // chunk_size


def validate_upload_file(
    file_name: str, file_size: int
) -> tuple[bool, Optional[str]]:
    """Validate a file for upload (type and size constraints).

    Args:
        file_name: The file name to validate.
        file_size: The file size in bytes.

    Returns:
        Tuple of (is_valid, error_message).
        error_message is None if valid.
    """
    # Check extension
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        return False, (
            f"Invalid file type '.{extension}'. "
            f"Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Check size
    if file_size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE // (1024 * 1024)
        actual_mb = file_size / (1024 * 1024)
        return False, (
            f"File size ({actual_mb:.1f} MB) exceeds maximum allowed size ({max_mb} MB)"
        )

    if file_size <= 0:
        return False, "File size must be greater than 0"

    return True, None


def get_content_type(file_name: str) -> str:
    """Get the content type for a file based on its extension.

    Args:
        file_name: The file name.

    Returns:
        The MIME type string.
    """
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return ALLOWED_CONTENT_TYPES.get(extension, "application/octet-stream")
