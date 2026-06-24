"""Standardized error response format for the Data Quality Platform.

Provides a consistent error response structure across all services:
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Human-readable message",
        "details": {...},
        "requestId": "request-id",
        "timestamp": "ISO 8601 UTC"
    }
}

Requirements: 19.2 (standardized error responses)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ErrorCode(str, Enum):
    """Standardized error codes for the platform."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    UNAUTHORIZED = "UNAUTHORIZED"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    AUDIT_FAILURE = "AUDIT_FAILURE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    BAD_REQUEST = "BAD_REQUEST"


# Map error codes to HTTP status codes
_ERROR_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.AUDIT_FAILURE: 500,
}


@dataclass
class ErrorResponse:
    """Structured error response."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to the standardized error response format."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "requestId": self.request_id,
                "timestamp": self.timestamp,
            }
        }


def build_error_response(
    code: ErrorCode,
    message: str,
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Build a standardized API Gateway Lambda proxy response with error payload.

    Args:
        code: The error code enum value.
        message: Human-readable error message.
        details: Optional additional details about the error.
        request_id: The request ID from API Gateway context.

    Returns:
        A dict formatted as an API Gateway Lambda proxy response.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    error_response = ErrorResponse(
        code=code.value,
        message=message,
        details=details or {},
        request_id=request_id,
        timestamp=timestamp,
    )

    status_code = _ERROR_STATUS_MAP.get(code, 500)

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(error_response.to_dict()),
    }


def validation_error(
    message: str,
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a 400 validation error response."""
    return build_error_response(ErrorCode.VALIDATION_ERROR, message, details, request_id)


def not_found_error(
    message: str,
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a 404 not found error response."""
    return build_error_response(ErrorCode.NOT_FOUND, message, details, request_id)


def forbidden_error(
    message: str = "You do not have permission to perform this action",
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a 403 forbidden error response."""
    return build_error_response(ErrorCode.FORBIDDEN, message, details, request_id)


def unauthorized_error(
    message: str = "Authentication required",
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a 401 unauthorized error response."""
    return build_error_response(ErrorCode.UNAUTHORIZED, message, details, request_id)


def internal_error(
    message: str = "An internal error occurred",
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a 500 internal error response."""
    return build_error_response(ErrorCode.INTERNAL_ERROR, message, details, request_id)


def conflict_error(
    message: str,
    details: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a 409 conflict error response."""
    return build_error_response(ErrorCode.CONFLICT, message, details, request_id)


def success_response(
    body: Any,
    status_code: int = 200,
) -> dict[str, Any]:
    """Create a successful API Gateway Lambda proxy response.

    Args:
        body: The response body (will be JSON-serialized).
        status_code: HTTP status code (default 200).

    Returns:
        A dict formatted as an API Gateway Lambda proxy response.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, default=str),
    }


def error_response(
    status_code: int,
    message: str,
    error_code: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create a standardized error response (API Gateway-compatible dict).

    This is the simple function-based API for generating error responses.

    Args:
        status_code: HTTP status code (e.g., 400, 401, 403, 404, 500).
        message: Human-readable error message.
        error_code: Machine-readable error code string (e.g., 'VALIDATION_ERROR').
        details: Optional dict with additional error context.

    Returns:
        A dict formatted as an API Gateway Lambda proxy response with error body.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    error_body = {
        "error": {
            "code": error_code,
            "message": message,
            "details": details or {},
            "timestamp": timestamp,
        }
    }

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(error_body),
    }
