"""Audit record creation with transactional integrity.

Ensures that every create, update, and delete operation is accompanied by
an audit record. If the audit write fails, the originating operation is
rejected (transactional integrity via DynamoDB TransactWriteItems).

Provides:
- audit_decorator(resource_type): Wraps CUD operations with automatic audit recording
- create_audit_record(): Direct audit record creation
- create_audit_transact_item(): TransactWriteItem builder for atomic audit
- write_with_audit(): Combined operation + audit in single transaction

Audit records are append-only and stored in the dq-audit-trail table.
Records cannot be modified or deleted by any user.

Table: dq-audit-trail
- PK: AUDIT#{year-month}
- SK: {timestamp}#{uuid}
- GSI user-index: PK=user_id, SK=timestamp
- GSI resource-index: PK=resource_type#resource_id, SK=timestamp

Retention: 365 days minimum

Requirements: 18.1, 18.3, 18.5
"""

from __future__ import annotations

import functools
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import boto3
from botocore.exceptions import ClientError

from services.shared.errors import internal_error

logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AUDIT_TABLE_NAME = os.environ.get("AUDIT_TABLE_NAME", "dq-audit-trail")

# Valid action types
VALID_ACTION_TYPES = {"create", "update", "delete"}

# Valid resource types
VALID_RESOURCE_TYPES = {
    "catalog",
    "table",
    "field",
    "template",
    "rule",
    "validation",
    "anomaly_training",
    "anomaly_scoring",
    "cleaning",
    "report",
    "notification",
    "dataset",
}


def create_audit_record(
    user_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create an audit record in the dq-audit-trail table.

    This function creates the audit record directly. For transactional
    integrity (ensuring the audit record is written atomically with the
    originating operation), use create_audit_transact_item() with
    DynamoHelper.transact_write().

    Args:
        user_id: The acting user's identifier.
        action_type: The action type ('create', 'update', 'delete').
        resource_type: The type of resource affected.
        resource_id: The ID of the affected resource.
        details: Optional action-specific details.

    Returns:
        The created audit record item.

    Raises:
        ValueError: If action_type is invalid.
        ClientError: If the DynamoDB write fails.
    """
    if action_type not in VALID_ACTION_TYPES:
        raise ValueError(
            f"Invalid action_type '{action_type}'. "
            f"Must be one of: {', '.join(VALID_ACTION_TYPES)}"
        )

    record = _build_audit_item(
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )

    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(AUDIT_TABLE_NAME)

    try:
        table.put_item(Item=record)
        logger.info(
            f"Audit record created: {action_type} on {resource_type}/{resource_id} "
            f"by {user_id}"
        )
        return record
    except ClientError as e:
        logger.error(f"Failed to create audit record: {e}")
        raise


def create_audit_transact_item(
    user_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a DynamoDB TransactWriteItem for an audit record.

    Use this with DynamoHelper.transact_write() to ensure the audit record
    and the originating operation succeed or fail together. If the audit
    write fails, the entire transaction (including the original operation)
    is rejected.

    Args:
        user_id: The acting user's identifier.
        action_type: The action type ('create', 'update', 'delete').
        resource_type: The type of resource affected.
        resource_id: The ID of the affected resource.
        details: Optional action-specific details.

    Returns:
        A TransactWriteItem dict ready for use in transact_write_items.

    Raises:
        ValueError: If action_type is invalid.
    """
    if action_type not in VALID_ACTION_TYPES:
        raise ValueError(
            f"Invalid action_type '{action_type}'. "
            f"Must be one of: {', '.join(VALID_ACTION_TYPES)}"
        )

    record = _build_audit_item(
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )

    # Convert to DynamoDB JSON format for transact_write_items (client-level API)
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()
    dynamo_item = {k: serializer.serialize(v) for k, v in record.items()}

    return {
        "Put": {
            "TableName": AUDIT_TABLE_NAME,
            "Item": dynamo_item,
        }
    }


def write_with_audit(
    operation_item: dict[str, Any],
    operation_table: str,
    operation_type: str,
    user_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Execute an operation with audit record in a single transaction.

    Ensures transactional integrity: if the audit record fails to write,
    the originating operation is also rejected. This is the recommended
    way to perform write operations that require audit trailing.

    Args:
        operation_item: The item to write for the primary operation.
        operation_table: The table for the primary operation.
        operation_type: 'Put', 'Update', or 'Delete'.
        user_id: Acting user's ID.
        action_type: Audit action type ('create', 'update', 'delete').
        resource_type: Resource type for audit.
        resource_id: Resource ID for audit.
        details: Optional audit details.

    Returns:
        The DynamoDB transact_write_items response.

    Raises:
        ClientError: If the transaction fails (operation or audit rejected).
        ValueError: If operation_type or action_type is invalid.
    """
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()

    # Build the operation transaction item
    dynamo_operation_item = {k: serializer.serialize(v) for k, v in operation_item.items()}

    if operation_type == "Put":
        operation_transact = {
            "Put": {
                "TableName": operation_table,
                "Item": dynamo_operation_item,
            }
        }
    elif operation_type == "Delete":
        # For delete, operation_item should contain just the key
        operation_transact = {
            "Delete": {
                "TableName": operation_table,
                "Key": dynamo_operation_item,
            }
        }
    else:
        raise ValueError(
            f"Unsupported operation_type '{operation_type}'. Use 'Put' or 'Delete'."
        )

    # Build the audit transaction item
    audit_transact = create_audit_transact_item(
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )

    # Execute both in a single transaction
    client = boto3.client("dynamodb", region_name=AWS_REGION)
    transact_items = [operation_transact, audit_transact]

    try:
        response = client.transact_write_items(TransactItems=transact_items)
        logger.info(
            f"Transaction committed: {action_type} {resource_type}/{resource_id} "
            f"with audit record"
        )
        return response
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        logger.error(
            f"Transaction failed ({error_code}): operation {action_type} on "
            f"{resource_type}/{resource_id} rejected. Audit integrity enforced."
        )
        raise


def _build_audit_item(
    user_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build an audit record item for DynamoDB.

    Args:
        user_id: Acting user's identifier.
        action_type: The action type.
        resource_type: Resource type.
        resource_id: Resource ID.
        details: Optional details dict.

    Returns:
        The audit record item dict.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    year_month = now.strftime("%Y-%m")
    audit_id = str(uuid.uuid4())

    record: dict[str, Any] = {
        "PK": f"AUDIT#{year_month}",
        "SK": f"{timestamp}#{audit_id}",
        "id": audit_id,
        "user_id": user_id,
        "action_type": action_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "timestamp": timestamp,
        "details": details or {},
        # GSI: user-index
        "GSI1PK": user_id,
        "GSI1SK": timestamp,
        # GSI: resource-index
        "GSI2PK": f"{resource_type}#{resource_id}",
        "GSI2SK": timestamp,
    }

    return record


# ─── Audit Decorator ─────────────────────────────────────────────────────


def audit_decorator(resource_type: str) -> Callable:
    """Decorator that wraps CUD operations with automatic audit recording.

    Records: user_id, timestamp (ISO 8601 UTC), resource_type, resource_id, action_type.
    Uses TransactWriteItems to ensure atomic audit+operation. If the audit write fails,
    the operation is rejected.

    The decorated handler must return a dict with:
    - 'statusCode' in the response
    - The body should contain 'id' (resource_id) or the handler can set
      'resource_id' and 'action_type' in the response body for explicit control.

    The handler must accept (event, context) or (event, context, user_claims).
    user_claims.user_id is used for the audit user_id field.

    Args:
        resource_type: The type of resource being operated on (e.g., 'catalog', 'rule').

    Returns:
        Decorator function.

    Usage:
        @audit_decorator('catalog')
        def create_catalog_handler(event, context, user_claims):
            # ... create logic ...
            return success_response({'id': catalog_id, ...}, 201)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(event: dict[str, Any], context: Any, *args, **kwargs) -> dict[str, Any]:
            # Execute the original handler
            response = func(event, context, *args, **kwargs)

            # Only audit successful CUD operations (2xx status codes)
            status_code = response.get("statusCode", 500)
            if not (200 <= status_code < 300):
                return response

            # Determine action type from HTTP method
            http_method = (
                event.get("requestContext", {})
                .get("http", {})
                .get("method", "")
                .upper()
            )

            action_type_map = {
                "POST": "create",
                "PUT": "update",
                "PATCH": "update",
                "DELETE": "delete",
            }
            action_type = action_type_map.get(http_method)

            # Only audit CUD operations (not reads)
            if not action_type:
                return response

            # Extract user_id from user_claims if passed as arg
            user_id = "unknown"
            if args and hasattr(args[0], "user_id"):
                user_id = args[0].user_id
            elif "user_claims" in kwargs and hasattr(kwargs["user_claims"], "user_id"):
                user_id = kwargs["user_claims"].user_id
            else:
                # Try to extract from event authorizer context
                claims = (
                    event.get("requestContext", {})
                    .get("authorizer", {})
                    .get("jwt", {})
                    .get("claims", {})
                )
                user_id = claims.get("sub", "unknown")

            # Extract resource_id from response body
            resource_id = "unknown"
            try:
                body = json.loads(response.get("body", "{}"))
                resource_id = body.get("id", body.get("resource_id", "unknown"))
            except (json.JSONDecodeError, TypeError):
                pass

            # Write audit record using transaction for atomicity
            try:
                audit_item = create_audit_transact_item(
                    user_id=user_id,
                    action_type=action_type,
                    resource_type=resource_type,
                    resource_id=str(resource_id),
                )

                # Execute audit write
                client = boto3.client("dynamodb", region_name=AWS_REGION)
                client.transact_write_items(TransactItems=[audit_item])

                logger.info(
                    f"Audit recorded: {action_type} on {resource_type}/{resource_id} "
                    f"by {user_id}"
                )

            except ClientError as e:
                # If audit write fails, reject the operation
                logger.error(
                    f"Audit write failed for {action_type} on "
                    f"{resource_type}/{resource_id}: {e}. Operation rejected."
                )
                return internal_error(
                    message="Operation rejected: audit record could not be written.",
                    details={
                        "resource_type": resource_type,
                        "action_type": action_type,
                    },
                )

            return response

        return wrapper

    return decorator
