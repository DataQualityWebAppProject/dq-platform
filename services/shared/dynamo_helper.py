"""DynamoDB CRUD wrapper with pagination support for the Data Quality Platform.

Provides high-level operations for DynamoDB tables with:
- Single-item CRUD operations
- Query and scan with automatic pagination
- Batch write operations (batches of 25)
- Transactional write support (for audit integrity)
- Cursor-based pagination (default 20, max 100)

Table name prefix: dq-*

Requirements: 3.3, 18.1, 19.2
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from services.shared.pagination import (
    PaginationParams,
    encode_next_token,
    decode_next_token,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
)

logger = logging.getLogger(__name__)

# AWS region from environment or default
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ─── Standalone Module-Level Functions ────────────────────────────────────


def batch_write_items(table_name: str, items: list[dict[str, Any]]) -> None:
    """Write items to a DynamoDB table in batches of 25.

    DynamoDB limits batch writes to 25 items per request. This function
    automatically chunks the items and handles retries for unprocessed items.

    Args:
        table_name: The DynamoDB table name.
        items: List of items to write.

    Raises:
        ClientError: If a batch write fails after retries.
    """
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(table_name)
    batch_size = 25

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        with table.batch_writer() as writer:
            for item in batch:
                writer.put_item(Item=item)

    logger.info(f"batch_write_items: wrote {len(items)} items to {table_name}")


def paginated_query(
    table_name: str,
    key_condition: Any,
    page_size: int = 20,
    next_token: Optional[str] = None,
    index_name: Optional[str] = None,
    filter_expression: Optional[Any] = None,
    scan_forward: bool = True,
) -> dict[str, Any]:
    """Execute a paginated query on a DynamoDB table with cursor-based pagination.

    Args:
        table_name: The DynamoDB table name.
        key_condition: A boto3 Key condition expression.
        page_size: Number of items per page (default 20, max 100).
        next_token: Base64-encoded pagination cursor from a previous query.
        index_name: Optional GSI name to query.
        filter_expression: Optional filter expression.
        scan_forward: Sort order (True=ascending, False=descending).

    Returns:
        Dict with 'items', 'count', and optional 'next_token'.
    """
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(table_name)

    kwargs: dict[str, Any] = {
        "KeyConditionExpression": key_condition,
        "Limit": page_size,
        "ScanIndexForward": scan_forward,
    }

    if index_name:
        kwargs["IndexName"] = index_name

    if filter_expression is not None:
        kwargs["FilterExpression"] = filter_expression

    if next_token:
        start_key = decode_next_token(next_token)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key

    try:
        response = table.query(**kwargs)

        result: dict[str, Any] = {
            "items": response.get("Items", []),
            "count": response.get("Count", 0),
        }

        last_key = response.get("LastEvaluatedKey")
        if last_key:
            result["next_token"] = encode_next_token(last_key)

        return result

    except ClientError as e:
        logger.error(f"paginated_query failed on {table_name}: {e}")
        raise


def transact_write(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a DynamoDB TransactWriteItems operation.

    Wraps the low-level client transact_write_items call. Used for ensuring
    atomic writes across multiple items/tables (e.g., operation + audit record).

    Args:
        items: List of TransactWriteItem dicts (Put, Update, Delete, ConditionCheck).

    Returns:
        The DynamoDB transact_write_items response.

    Raises:
        ClientError: If any item in the transaction fails.
    """
    client = boto3.client("dynamodb", region_name=AWS_REGION)

    try:
        response = client.transact_write_items(TransactItems=items)
        logger.debug(f"transact_write: committed {len(items)} operations")
        return response
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        logger.error(f"transact_write failed ({error_code}): {e}")
        raise


class DynamoHelper:
    """High-level DynamoDB operations wrapper.

    Provides CRUD, query, scan, batch, and transactional operations
    for DynamoDB tables used by the Data Quality Platform.
    """

    def __init__(self, table_name: str, region: str = AWS_REGION):
        """Initialize DynamoHelper for a specific table.

        Args:
            table_name: The DynamoDB table name (e.g., 'dq-catalogs').
            region: AWS region (defaults to us-east-1).
        """
        self._table_name = table_name
        self._region = region
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._client = boto3.client("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)

    @property
    def table_name(self) -> str:
        """Get the table name."""
        return self._table_name

    @property
    def table(self):
        """Get the underlying boto3 Table resource."""
        return self._table

    # ─── Single Item Operations ───────────────────────────────────────────

    def put_item(
        self,
        item: dict[str, Any],
        condition_expression: Optional[str] = None,
    ) -> dict[str, Any]:
        """Put an item into the table.

        Args:
            item: The item to store.
            condition_expression: Optional condition for conditional put.

        Returns:
            The DynamoDB response.

        Raises:
            ClientError: If the put fails (e.g., condition check failure).
        """
        kwargs: dict[str, Any] = {"Item": item}
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression

        try:
            response = self._table.put_item(**kwargs)
            logger.debug(f"Put item to {self._table_name}: PK={item.get('PK')}")
            return response
        except ClientError as e:
            logger.error(f"Failed to put item to {self._table_name}: {e}")
            raise

    def get_item(
        self,
        pk: str,
        sk: str,
        consistent_read: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Get a single item by primary key.

        Args:
            pk: Partition key value.
            sk: Sort key value.
            consistent_read: Whether to use strongly consistent read.

        Returns:
            The item dict if found, None otherwise.
        """
        try:
            response = self._table.get_item(
                Key={"PK": pk, "SK": sk},
                ConsistentRead=consistent_read,
            )
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Failed to get item from {self._table_name}: {e}")
            raise

    def update_item(
        self,
        pk: str,
        sk: str,
        update_expression: str,
        expression_values: dict[str, Any],
        expression_names: Optional[dict[str, str]] = None,
        condition_expression: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update an item's attributes.

        Args:
            pk: Partition key value.
            sk: Sort key value.
            update_expression: DynamoDB update expression.
            expression_values: Expression attribute values.
            expression_names: Optional expression attribute names.
            condition_expression: Optional condition expression.

        Returns:
            The DynamoDB response with updated attributes.

        Raises:
            ClientError: If the update fails.
        """
        kwargs: dict[str, Any] = {
            "Key": {"PK": pk, "SK": sk},
            "UpdateExpression": update_expression,
            "ExpressionAttributeValues": expression_values,
            "ReturnValues": "ALL_NEW",
        }
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression

        try:
            response = self._table.update_item(**kwargs)
            logger.debug(f"Updated item in {self._table_name}: PK={pk}, SK={sk}")
            return response
        except ClientError as e:
            logger.error(f"Failed to update item in {self._table_name}: {e}")
            raise

    def delete_item(
        self,
        pk: str,
        sk: str,
        condition_expression: Optional[str] = None,
    ) -> dict[str, Any]:
        """Delete a single item.

        Args:
            pk: Partition key value.
            sk: Sort key value.
            condition_expression: Optional condition expression.

        Returns:
            The DynamoDB response.

        Raises:
            ClientError: If the delete fails.
        """
        kwargs: dict[str, Any] = {
            "Key": {"PK": pk, "SK": sk},
            "ReturnValues": "ALL_OLD",
        }
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression

        try:
            response = self._table.delete_item(**kwargs)
            logger.debug(f"Deleted item from {self._table_name}: PK={pk}, SK={sk}")
            return response
        except ClientError as e:
            logger.error(f"Failed to delete item from {self._table_name}: {e}")
            raise

    # ─── Query Operations ─────────────────────────────────────────────────

    def query(
        self,
        pk_value: str,
        sk_condition: Optional[Any] = None,
        index_name: Optional[str] = None,
        filter_expression: Optional[Any] = None,
        pagination: Optional[PaginationParams] = None,
        scan_forward: bool = True,
        projection_expression: Optional[str] = None,
        expression_names: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Query items with pagination support.

        Args:
            pk_value: Partition key value to query.
            sk_condition: Optional sort key condition (boto3 Key condition).
            index_name: Optional GSI name.
            filter_expression: Optional filter expression.
            pagination: Pagination parameters (page_size, next_token).
            scan_forward: Sort order (True=ascending, False=descending).
            projection_expression: Optional projection.
            expression_names: Optional expression attribute names.

        Returns:
            Dict with 'items', 'count', and optional 'next_token'.
        """
        if pagination is None:
            pagination = PaginationParams(page_size=DEFAULT_PAGE_SIZE, next_token=None)

        # Build key condition
        key_condition = Key("PK").eq(pk_value)
        if sk_condition is not None:
            key_condition = key_condition & sk_condition

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "Limit": pagination.page_size,
            "ScanIndexForward": scan_forward,
        }

        if index_name:
            kwargs["IndexName"] = index_name

        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression

        if projection_expression:
            kwargs["ProjectionExpression"] = projection_expression

        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names

        # Apply pagination token
        if pagination.next_token:
            start_key = decode_next_token(pagination.next_token)
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key

        try:
            response = self._table.query(**kwargs)

            result: dict[str, Any] = {
                "items": response.get("Items", []),
                "count": response.get("Count", 0),
            }

            # Encode next token if more items exist
            last_key = response.get("LastEvaluatedKey")
            if last_key:
                result["next_token"] = encode_next_token(last_key)

            return result

        except ClientError as e:
            logger.error(f"Query failed on {self._table_name}: {e}")
            raise

    def query_gsi(
        self,
        index_name: str,
        pk_name: str,
        pk_value: str,
        sk_condition: Optional[Any] = None,
        filter_expression: Optional[Any] = None,
        pagination: Optional[PaginationParams] = None,
        scan_forward: bool = True,
    ) -> dict[str, Any]:
        """Query a Global Secondary Index with pagination.

        Args:
            index_name: The GSI name.
            pk_name: The GSI partition key attribute name.
            pk_value: The GSI partition key value.
            sk_condition: Optional sort key condition.
            filter_expression: Optional filter.
            pagination: Pagination parameters.
            scan_forward: Sort order.

        Returns:
            Dict with 'items', 'count', and optional 'next_token'.
        """
        if pagination is None:
            pagination = PaginationParams(page_size=DEFAULT_PAGE_SIZE, next_token=None)

        key_condition = Key(pk_name).eq(pk_value)
        if sk_condition is not None:
            key_condition = key_condition & sk_condition

        kwargs: dict[str, Any] = {
            "IndexName": index_name,
            "KeyConditionExpression": key_condition,
            "Limit": pagination.page_size,
            "ScanIndexForward": scan_forward,
        }

        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression

        if pagination.next_token:
            start_key = decode_next_token(pagination.next_token)
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key

        try:
            response = self._table.query(**kwargs)

            result: dict[str, Any] = {
                "items": response.get("Items", []),
                "count": response.get("Count", 0),
            }

            last_key = response.get("LastEvaluatedKey")
            if last_key:
                result["next_token"] = encode_next_token(last_key)

            return result

        except ClientError as e:
            logger.error(f"GSI query failed on {self._table_name}/{index_name}: {e}")
            raise

    def query_all(
        self,
        pk_value: str,
        sk_condition: Optional[Any] = None,
        index_name: Optional[str] = None,
        filter_expression: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        """Query all items matching a key condition (auto-paginate through all pages).

        Use with caution on large datasets. Prefer paginated query for API responses.

        Args:
            pk_value: Partition key value.
            sk_condition: Optional sort key condition.
            index_name: Optional GSI name.
            filter_expression: Optional filter.

        Returns:
            List of all matching items.
        """
        all_items: list[dict[str, Any]] = []
        next_token: Optional[str] = None

        while True:
            pagination = PaginationParams(page_size=MAX_PAGE_SIZE, next_token=next_token)
            result = self.query(
                pk_value=pk_value,
                sk_condition=sk_condition,
                index_name=index_name,
                filter_expression=filter_expression,
                pagination=pagination,
            )
            all_items.extend(result["items"])

            next_token = result.get("next_token")
            if not next_token:
                break

        return all_items

    # ─── Scan Operations ──────────────────────────────────────────────────

    def scan(
        self,
        filter_expression: Optional[Any] = None,
        pagination: Optional[PaginationParams] = None,
        index_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Scan the table with optional filter and pagination.

        Args:
            filter_expression: Optional filter expression.
            pagination: Pagination parameters.
            index_name: Optional index to scan.

        Returns:
            Dict with 'items', 'count', and optional 'next_token'.
        """
        if pagination is None:
            pagination = PaginationParams(page_size=DEFAULT_PAGE_SIZE, next_token=None)

        kwargs: dict[str, Any] = {
            "Limit": pagination.page_size,
        }

        if index_name:
            kwargs["IndexName"] = index_name

        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression

        if pagination.next_token:
            start_key = decode_next_token(pagination.next_token)
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key

        try:
            response = self._table.scan(**kwargs)

            result: dict[str, Any] = {
                "items": response.get("Items", []),
                "count": response.get("Count", 0),
            }

            last_key = response.get("LastEvaluatedKey")
            if last_key:
                result["next_token"] = encode_next_token(last_key)

            return result

        except ClientError as e:
            logger.error(f"Scan failed on {self._table_name}: {e}")
            raise

    # ─── Batch Operations ─────────────────────────────────────────────────

    def batch_write(self, items: list[dict[str, Any]], batch_size: int = 25) -> None:
        """Write items in batches (max 25 per batch as per DynamoDB limits).

        Args:
            items: List of items to write.
            batch_size: Number of items per batch (max 25).

        Raises:
            ClientError: If batch write fails.
        """
        batch_size = min(batch_size, 25)  # DynamoDB limit

        with self._table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)

        logger.debug(f"Batch wrote {len(items)} items to {self._table_name}")

    def batch_delete(self, keys: list[dict[str, str]]) -> None:
        """Delete items in batches.

        Args:
            keys: List of key dicts, each with 'PK' and 'SK'.

        Raises:
            ClientError: If batch delete fails.
        """
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)

        logger.debug(f"Batch deleted {len(keys)} items from {self._table_name}")

    # ─── Transactional Operations ─────────────────────────────────────────

    def transact_write(self, transact_items: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute a transactional write across one or more items/tables.

        Used for audit integrity: ensures the operation and its audit record
        are written atomically. If the audit write fails, the entire
        transaction (including the original operation) is rejected.

        Args:
            transact_items: List of transact items (Put, Update, Delete, ConditionCheck).

        Returns:
            The DynamoDB transact_write_items response.

        Raises:
            ClientError: If any item in the transaction fails.
        """
        try:
            response = self._client.transact_write_items(
                TransactItems=transact_items
            )
            logger.debug(
                f"Transaction committed with {len(transact_items)} operations"
            )
            return response
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            logger.error(
                f"Transaction failed ({error_code}): {e}"
            )
            raise

    # ─── Count Operations ─────────────────────────────────────────────────

    def get_item_count(
        self,
        pk_value: str,
        sk_condition: Optional[Any] = None,
        index_name: Optional[str] = None,
        filter_expression: Optional[Any] = None,
    ) -> int:
        """Get total count of items matching query conditions.

        Args:
            pk_value: Partition key value.
            sk_condition: Optional sort key condition.
            index_name: Optional GSI name.
            filter_expression: Optional filter.

        Returns:
            Total count of matching items.
        """
        key_condition = Key("PK").eq(pk_value)
        if sk_condition is not None:
            key_condition = key_condition & sk_condition

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "Select": "COUNT",
        }

        if index_name:
            kwargs["IndexName"] = index_name

        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression

        total = 0
        try:
            while True:
                response = self._table.query(**kwargs)
                total += response.get("Count", 0)

                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                kwargs["ExclusiveStartKey"] = last_key

            return total

        except ClientError as e:
            logger.error(f"Count query failed on {self._table_name}: {e}")
            raise
