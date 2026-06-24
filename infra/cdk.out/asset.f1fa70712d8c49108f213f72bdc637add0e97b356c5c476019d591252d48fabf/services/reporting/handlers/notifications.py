"""Notifications Lambda handler.

Handles HTTP API routes for email notifications:
- POST /notifications/recipients → configure recipients (max 20 per event type)
- GET  /notifications            → list notification history
- GET  /notifications/recipients → get configured recipients

Sends email via SES with:
- Retry logic: exponential backoff (1s, 2s, 4s), max 3 retries
- Delivery status tracking: sent/failed/retrying
- Recipient configuration: max 20 emails per event type

DynamoDB Tables: dq-notifications, dq-notification-recipients

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

import json
import logging
import os
import time
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
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
NOTIFICATIONS_TABLE = os.environ.get("NOTIFICATIONS_TABLE", "dq-notifications")
RECIPIENTS_TABLE = os.environ.get("RECIPIENTS_TABLE", "dq-notification-recipients")
SES_SENDER_EMAIL = os.environ.get("SES_SENDER_EMAIL", "noreply@dataquality.platform")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Constraints
MAX_RECIPIENTS_PER_EVENT = 20
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1  # seconds

# Valid notification event types
VALID_EVENT_TYPES = {
    "validation_completion",
    "anomaly_scoring_completion",
    "report_publication",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for notification management.

    Routes:
    - POST /notifications/recipients → configure recipients
    - GET  /notifications            → list notification history
    - GET  /notifications/recipients → get configured recipients

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

        # Determine route
        is_recipients_path = "recipients" in path

        if http_method == "POST" and is_recipients_path:
            return _configure_recipients(event, request_id)
        elif http_method == "GET" and is_recipients_path:
            return _get_recipients(event, request_id)
        elif http_method == "GET" and not is_recipients_path:
            return _list_notifications(event, request_id)
        else:
            return validation_error(
                message=f"Unsupported method or path: {http_method} {path}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in notifications handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing the notification request.",
            request_id=request_id,
        )


def _configure_recipients(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Configure notification recipients for an event type.

    Expected body:
    {
        "eventType": "validation_completion" | "anomaly_scoring_completion" | "report_publication",
        "recipients": ["email1@example.com", "email2@example.com", ...]
    }

    Max 20 recipients per event type. AdminDatos only.

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Confirmation of recipient configuration.
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
            message="Only AdminDatos can configure notification recipients.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    event_type = body.get("eventType")
    recipients = body.get("recipients", [])

    # Validate event type
    if not event_type or event_type not in VALID_EVENT_TYPES:
        return validation_error(
            message=f"Invalid eventType. Must be one of: {', '.join(sorted(VALID_EVENT_TYPES))}",
            details={"field": "eventType", "validValues": sorted(VALID_EVENT_TYPES)},
            request_id=request_id,
        )

    # Validate recipients
    if not isinstance(recipients, list):
        return validation_error(
            message="recipients must be a list of email addresses.",
            details={"field": "recipients"},
            request_id=request_id,
        )

    if len(recipients) > MAX_RECIPIENTS_PER_EVENT:
        return validation_error(
            message=f"Maximum {MAX_RECIPIENTS_PER_EVENT} recipients allowed per event type.",
            details={"field": "recipients", "max": MAX_RECIPIENTS_PER_EVENT, "provided": len(recipients)},
            request_id=request_id,
        )

    # Validate email format (basic check)
    invalid_emails = [e for e in recipients if not _is_valid_email(e)]
    if invalid_emails:
        return validation_error(
            message="One or more email addresses are invalid.",
            details={"invalidEmails": invalid_emails},
            request_id=request_id,
        )

    # Store recipient configuration
    now = datetime.now(timezone.utc).isoformat()
    recipient_item = {
        "PK": f"RECIPIENTS#{event_type}",
        "SK": "CONFIG",
        "eventType": event_type,
        "recipients": recipients,
        "updatedAt": now,
        "updatedBy": claims.user_id,
    }

    db = DynamoHelper(RECIPIENTS_TABLE)

    try:
        db.put_item(recipient_item)
    except ClientError as e:
        logger.error(f"Failed to save recipient config: {e}")
        return internal_error(
            message="Failed to save recipient configuration.",
            request_id=request_id,
        )

    return success_response({
        "eventType": event_type,
        "recipients": recipients,
        "count": len(recipients),
        "updatedAt": now,
    })


def _get_recipients(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Get configured recipients.

    Query params:
    - eventType: optional filter by event type

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Recipient configurations.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    params = event.get("queryStringParameters") or {}
    filter_event_type = params.get("eventType")

    db = DynamoHelper(RECIPIENTS_TABLE)

    if filter_event_type:
        item = db.get_item(pk=f"RECIPIENTS#{filter_event_type}", sk="CONFIG")
        if item:
            return success_response({
                "recipients": [{
                    "eventType": item.get("eventType"),
                    "emails": item.get("recipients", []),
                    "updatedAt": item.get("updatedAt"),
                    "updatedBy": item.get("updatedBy"),
                }]
            })
        return success_response({"recipients": []})

    # Get all event type configurations
    from boto3.dynamodb.conditions import Attr
    result = db.scan(
        filter_expression=Attr("SK").eq("CONFIG"),
    )

    configs = [
        {
            "eventType": item.get("eventType"),
            "emails": item.get("recipients", []),
            "updatedAt": item.get("updatedAt"),
            "updatedBy": item.get("updatedBy"),
        }
        for item in result.get("items", [])
    ]

    return success_response({"recipients": configs})


def _list_notifications(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List notification history (paginated).

    Query params:
    - pageSize: items per page
    - nextToken: pagination cursor
    - eventType: filter by event type

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Paginated notification history.
    """
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    pagination = PaginationParams.from_event(event)
    params = event.get("queryStringParameters") or {}
    filter_event_type = params.get("eventType")

    db = DynamoHelper(NOTIFICATIONS_TABLE)

    from boto3.dynamodb.conditions import Attr
    filter_expr = Attr("SK").eq("METADATA")
    if filter_event_type:
        filter_expr = filter_expr & Attr("eventType").eq(filter_event_type)

    result = db.scan(filter_expression=filter_expr, pagination=pagination)

    # Sort by sentAt descending
    items = sorted(
        result.get("items", []),
        key=lambda x: x.get("sentAt", ""),
        reverse=True,
    )

    formatted_items = [
        {
            "id": item.get("id"),
            "eventType": item.get("eventType"),
            "recipient": item.get("recipient"),
            "subject": item.get("subject"),
            "status": item.get("status"),
            "sentAt": item.get("sentAt"),
            "deliveredAt": item.get("deliveredAt"),
            "retryCount": item.get("retryCount", 0),
            "errorMessage": item.get("errorMessage"),
        }
        for item in items
    ]

    response_body = paginate_response(
        items=formatted_items,
        total_count=result.get("count", len(formatted_items)),
        page_size=pagination.page_size,
        next_token=result.get("next_token"),
    )

    return success_response(response_body)


def send_notification(
    event_type: str,
    subject: str,
    body_html: str,
    body_text: str,
) -> list[dict[str, Any]]:
    """Send email notifications for an event type.

    Fetches configured recipients and sends emails via SES
    with exponential backoff retry logic.

    This function is called internally by other services when events occur.

    Args:
        event_type: The notification event type.
        subject: Email subject.
        body_html: HTML email body.
        body_text: Plain text email body.

    Returns:
        List of notification records with delivery status.
    """
    # Fetch recipients
    recipients_db = DynamoHelper(RECIPIENTS_TABLE)
    config = recipients_db.get_item(pk=f"RECIPIENTS#{event_type}", sk="CONFIG")

    if not config or not config.get("recipients"):
        logger.info(f"No recipients configured for event type: {event_type}")
        return []

    recipients = config["recipients"]
    notifications_db = DynamoHelper(NOTIFICATIONS_TABLE)
    ses_client = boto3.client("ses", region_name=AWS_REGION)
    results = []

    for recipient in recipients:
        notification_id = str(ulid.new())
        now = datetime.now(timezone.utc).isoformat()

        notification_record = {
            "PK": f"NOTIFICATION#{notification_id}",
            "SK": "METADATA",
            "id": notification_id,
            "eventType": event_type,
            "recipient": recipient,
            "subject": subject,
            "status": "sending",
            "sentAt": now,
            "deliveredAt": None,
            "retryCount": 0,
            "errorMessage": None,
        }

        # Attempt to send with retry logic
        delivery_status = _send_with_retry(
            ses_client=ses_client,
            recipient=recipient,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )

        # Update record with delivery status
        notification_record["status"] = delivery_status["status"]
        notification_record["retryCount"] = delivery_status["retryCount"]
        notification_record["errorMessage"] = delivery_status.get("errorMessage")

        if delivery_status["status"] == "sent":
            notification_record["deliveredAt"] = datetime.now(timezone.utc).isoformat()

        # Store notification record
        try:
            notifications_db.put_item(notification_record)
        except ClientError as e:
            logger.error(f"Failed to store notification record: {e}")

        results.append(notification_record)

    return results


def _send_with_retry(
    ses_client: Any,
    recipient: str,
    subject: str,
    body_html: str,
    body_text: str,
) -> dict[str, Any]:
    """Send email via SES with exponential backoff retry.

    Retry schedule: 1s, 2s, 4s (max 3 retries).
    After 3 failures: mark as 'failed', no further attempts.

    Args:
        ses_client: boto3 SES client.
        recipient: Email recipient.
        subject: Email subject.
        body_html: HTML body.
        body_text: Plain text body.

    Returns:
        Dict with status, retryCount, and optional errorMessage.
    """
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            ses_client.send_email(
                Source=SES_SENDER_EMAIL,
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                        "Text": {"Data": body_text, "Charset": "UTF-8"},
                    },
                },
            )

            logger.info(f"Email sent successfully to {recipient}")
            return {
                "status": "sent",
                "retryCount": attempt,
                "errorMessage": None,
            }

        except ClientError as e:
            last_error = str(e)
            logger.warning(
                f"Email send attempt {attempt + 1}/{MAX_RETRIES} failed for {recipient}: {e}"
            )

            if attempt < MAX_RETRIES - 1:
                # Exponential backoff: 1s, 2s, 4s
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)

    # All retries exhausted
    logger.error(f"Email delivery failed after {MAX_RETRIES} attempts for {recipient}")
    return {
        "status": "failed",
        "retryCount": MAX_RETRIES,
        "errorMessage": last_error,
    }


def _is_valid_email(email: str) -> bool:
    """Basic email validation.

    Args:
        email: Email address to validate.

    Returns:
        True if email appears valid.
    """
    if not email or not isinstance(email, str):
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    return True


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
