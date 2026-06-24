"""Shared utilities package for the Data Quality Platform.

This package provides common utilities used by all Lambda handlers:
- dynamo_helper: DynamoDB CRUD wrapper with pagination
- s3_helper: S3 upload/download, presigned URLs, multipart uploads
- auth: JWT token extraction and role checking
- audit: Audit record creation with transactional integrity
- pagination: Generic pagination utilities
- errors: Standardized error response format

Usage:
    from services.shared.errors import validation_error, success_response
    from services.shared.auth import require_role, ADMIN_ROLE
    from services.shared.dynamo_helper import DynamoHelper
    from services.shared.s3_helper import S3Helper
    from services.shared.audit import create_audit_record, write_with_audit
    from services.shared.pagination import PaginationParams, paginate_response
"""
