"""Generic pagination utilities for the Data Quality Platform.

Provides:
- validate_page_size(requested, default=20, max_size=100): validates page size
- encode_token(last_evaluated_key): base64 encode for pagination cursor
- decode_token(token): decode pagination cursor
- PaginationParams: dataclass for parsed pagination
- paginate_response(): standardized paginated response builder

Default page size: 20 items, maximum: 100 items.

Requirements: 3.3, 18.3, 19.2
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Platform-wide pagination defaults
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ─── Simple Module-Level Functions ────────────────────────────────────────


def validate_page_size(
    requested: Any,
    default: int = DEFAULT_PAGE_SIZE,
    max_size: int = MAX_PAGE_SIZE,
) -> int:
    """Validate and return a page size within allowed bounds.

    Args:
        requested: The requested page size (can be string, int, or None).
        default: Default page size if requested is invalid (default 20).
        max_size: Maximum allowed page size (default 100).

    Returns:
        Validated page size as an integer (clamped between 1 and max_size).
    """
    try:
        size = int(requested) if requested is not None else default
    except (ValueError, TypeError):
        size = default

    return max(1, min(size, max_size))


def encode_token(last_evaluated_key: dict[str, Any]) -> str:
    """Base64 encode a DynamoDB LastEvaluatedKey into a pagination cursor.

    Args:
        last_evaluated_key: The LastEvaluatedKey from a DynamoDB query/scan.

    Returns:
        Base64-encoded JSON string to use as a pagination token.
    """
    json_bytes = json.dumps(last_evaluated_key, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("utf-8")


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Decode a pagination cursor token back into a DynamoDB ExclusiveStartKey.

    Args:
        token: The base64-encoded pagination token string.

    Returns:
        The decoded dictionary for use as ExclusiveStartKey, or None if invalid.
    """
    try:
        json_bytes = base64.urlsafe_b64decode(token.encode("utf-8"))
        return json.loads(json_bytes)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Invalid pagination token: {e}")
        return None


@dataclass
class PaginationParams:
    """Parsed pagination parameters from a request."""

    page_size: int
    next_token: Optional[str]  # Opaque token for the next page

    @classmethod
    def from_event(
        cls,
        event: dict[str, Any],
        default_page_size: int = DEFAULT_PAGE_SIZE,
        max_page_size: int = MAX_PAGE_SIZE,
    ) -> "PaginationParams":
        """Extract and validate pagination parameters from API Gateway event.

        Query string parameters:
        - pageSize: Number of items per page (default 20, max 100)
        - nextToken: Opaque pagination token for the next page

        Args:
            event: API Gateway Lambda proxy event.
            default_page_size: Default page size if not specified.
            max_page_size: Maximum allowed page size.

        Returns:
            Validated PaginationParams instance.
        """
        params = event.get("queryStringParameters") or {}

        # Parse page size
        try:
            page_size = int(params.get("pageSize", default_page_size))
        except (ValueError, TypeError):
            page_size = default_page_size

        # Clamp page size to valid range
        page_size = max(1, min(page_size, max_page_size))

        # Extract next token
        next_token = params.get("nextToken") or None

        return cls(page_size=page_size, next_token=next_token)


def encode_next_token(last_evaluated_key: dict[str, Any]) -> str:
    """Encode DynamoDB LastEvaluatedKey into an opaque nextToken string.

    Args:
        last_evaluated_key: The LastEvaluatedKey from a DynamoDB query/scan.

    Returns:
        Base64-encoded JSON string to use as nextToken.
    """
    json_bytes = json.dumps(last_evaluated_key, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("utf-8")


def decode_next_token(token: str) -> Optional[dict[str, Any]]:
    """Decode a nextToken string into DynamoDB ExclusiveStartKey.

    Args:
        token: The base64-encoded nextToken string.

    Returns:
        The decoded dictionary for use as ExclusiveStartKey, or None if invalid.
    """
    try:
        json_bytes = base64.urlsafe_b64decode(token.encode("utf-8"))
        return json.loads(json_bytes)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Invalid nextToken: {e}")
        return None


def paginate_response(
    items: list[dict[str, Any]],
    total_count: int,
    page_size: int,
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """Build a standardized paginated response.

    Response format:
    {
        "items": [...],
        "totalCount": 100,
        "pageSize": 20,
        "nextToken": "..."  // Only present if more pages exist
    }

    Args:
        items: The items for the current page.
        total_count: Total number of items across all pages.
        page_size: The page size used for this request.
        next_token: The token for the next page (None if no more pages).

    Returns:
        Standardized paginated response dictionary.
    """
    response: dict[str, Any] = {
        "items": items,
        "totalCount": total_count,
        "pageSize": page_size,
    }

    if next_token:
        response["nextToken"] = next_token

    return response
