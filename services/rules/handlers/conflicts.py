"""Conflict Detection Lambda handler for the Rules Engine Service.

Handles conflict detection and resolution between rules at different hierarchy levels:
- GET  /rules/conflicts          → detect_conflicts (any authenticated user)
- POST /rules/conflicts/{id}/resolve → resolve_conflict (AdminDatos only)

Conflict detection logic:
- Find rules where different scope levels (catalog vs table vs column) target
  the same column/table with potentially contradictory constraints.

DynamoDB Table: dq-rule-conflicts
- PK: CONFLICT#{conflict_id}
- SK: METADATA
- Store resolution: resolvedBy, resolvedAt, priorityRuleId

Requirements: 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import json
import logging
import os
import ulid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from services.shared.auth import (
    ADMIN_ROLE,
    ANALYST_ROLE,
    extract_user_claims,
    get_request_id,
    require_role_check,
)
from services.shared.audit import write_with_audit
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    forbidden_error,
    internal_error,
    not_found_error,
    success_response,
    validation_error,
)
from services.shared.pagination import (
    PaginationParams,
    paginate_response,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
RULES_TABLE_NAME = os.environ.get("RULES_TABLE_NAME", "dq-rules")
CONFLICTS_TABLE_NAME = os.environ.get("CONFLICTS_TABLE_NAME", "dq-rule-conflicts")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for conflict detection and resolution.

    Routes requests based on HTTP method and path:
    - GET  /rules/conflicts → detect conflicts
    - POST /rules/conflicts/{id}/resolve → resolve a conflict

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)

    try:
        http_method = (
            event.get("requestContext", {}).get("http", {}).get("method", "")
        )
        path = event.get("rawPath", "") or event.get("path", "")

        # Determine route
        conflict_id = _extract_conflict_id_for_resolve(path)

        if http_method == "GET" and not conflict_id:
            return _detect_conflicts(event, request_id)
        elif http_method == "POST" and conflict_id:
            return _resolve_conflict(event, conflict_id, request_id)
        else:
            return validation_error(
                message=f"Unsupported method or path: {http_method} {path}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in conflicts handler: {e}")
        return internal_error(
            message="An unexpected error occurred while processing conflict request.",
            request_id=request_id,
        )


def _extract_conflict_id_for_resolve(path: str) -> Optional[str]:
    """Extract conflict ID from resolve path.

    Expected paths:
    - /rules/conflicts → None
    - /rules/conflicts/{id}/resolve → id

    Args:
        path: The raw request path.

    Returns:
        The conflict ID if it's a resolve path, None otherwise.
    """
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /rules/conflicts/{id}/resolve
    if (
        len(parts) >= 4
        and parts[0] == "rules"
        and parts[1] == "conflicts"
        and parts[3] == "resolve"
    ):
        return parts[2]

    return None


# ─── Detect Conflicts ─────────────────────────────────────────────────────────


def _detect_conflicts(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Detect conflicts between rules at different hierarchy levels.

    Finds rules where different scope levels (catalog vs table vs column)
    target the same entity with potentially contradictory constraints.

    AnalistaDatos sees conflicts in read-only mode (no resolution controls).

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with detected conflicts.
    """
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    pagination = PaginationParams.from_event(event)

    # Fetch all active rules for conflict analysis
    rules_db = DynamoHelper(RULES_TABLE_NAME)
    from boto3.dynamodb.conditions import Attr

    filter_expr = Attr("SK").eq("METADATA") & Attr("status").eq("active")
    all_rules = _fetch_all_active_rules(rules_db, filter_expr)

    # Detect conflicts
    conflicts = _find_conflicts(all_rules)

    # Load existing resolutions from conflicts table
    conflicts_db = DynamoHelper(CONFLICTS_TABLE_NAME)
    enriched_conflicts = _enrich_with_resolutions(conflicts, conflicts_db)

    # Paginate the response
    start_idx = 0  # Simple offset pagination for computed results
    page_items = enriched_conflicts[start_idx : start_idx + pagination.page_size]

    # Determine if user can resolve (AdminDatos only)
    can_resolve = claims.role == ADMIN_ROLE

    response_body = {
        "conflicts": page_items,
        "totalCount": len(enriched_conflicts),
        "pageSize": pagination.page_size,
        "canResolve": can_resolve,
    }

    return success_response(response_body)


def _fetch_all_active_rules(
    db: DynamoHelper, filter_expr: Any
) -> list[dict[str, Any]]:
    """Fetch all active rules from the table.

    Args:
        db: DynamoHelper instance for the rules table.
        filter_expr: Filter expression for active rules.

    Returns:
        List of active rule items.
    """
    all_items: list[dict[str, Any]] = []
    next_token: Optional[str] = None

    while True:
        pagination = PaginationParams(page_size=100, next_token=next_token)
        result = db.scan(filter_expression=filter_expr, pagination=pagination)
        all_items.extend(result["items"])
        next_token = result.get("next_token")
        if not next_token:
            break

    return all_items


def _find_conflicts(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect conflicts between rules at different hierarchy levels.

    A conflict exists when rules at different scope levels target the same
    entity with potentially contradictory constraints (e.g., a catalog-level
    rule and a column-level rule both targeting the same column with different
    conditions).

    Args:
        rules: List of active rule items.

    Returns:
        List of conflict dicts.
    """
    conflicts: list[dict[str, Any]] = []

    # Group rules by target entity (tableId or columnId)
    # A conflict arises when rules at different scopes target overlapping entities
    by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_column: dict[str, list[dict[str, Any]]] = defaultdict(list)
    catalog_rules: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rule in rules:
        scope = rule.get("scope", "")
        catalog_id = rule.get("catalogId", "")
        table_id = rule.get("tableId", "")
        column_id = rule.get("columnId", "")

        if scope == "catalog":
            catalog_rules[catalog_id].append(rule)
        elif scope == "table":
            by_table[table_id].append(rule)
        elif scope == "column":
            by_column[column_id].append(rule)

    # Detect conflicts: catalog rules vs table rules for same catalog
    seen_conflict_pairs: set[str] = set()

    for catalog_id, cat_rules in catalog_rules.items():
        # Find table rules in the same catalog
        table_rules_in_catalog = [
            r for r in rules
            if r.get("scope") == "table" and r.get("catalogId") == catalog_id
        ]

        for cat_rule in cat_rules:
            for table_rule in table_rules_in_catalog:
                pair_key = _make_pair_key(cat_rule["id"], table_rule["id"])
                if pair_key in seen_conflict_pairs:
                    continue

                # Check for contradiction (same target fields with different conditions)
                if _rules_may_conflict(cat_rule, table_rule):
                    seen_conflict_pairs.add(pair_key)
                    conflict = _build_conflict(cat_rule, table_rule)
                    conflicts.append(conflict)

    # Detect conflicts: table rules vs column rules for same table
    for table_id, tbl_rules in by_table.items():
        column_rules_for_table = [
            r for r in rules
            if r.get("scope") == "column" and r.get("tableId") == table_id
        ]

        for tbl_rule in tbl_rules:
            for col_rule in column_rules_for_table:
                pair_key = _make_pair_key(tbl_rule["id"], col_rule["id"])
                if pair_key in seen_conflict_pairs:
                    continue

                if _rules_may_conflict(tbl_rule, col_rule):
                    seen_conflict_pairs.add(pair_key)
                    conflict = _build_conflict(tbl_rule, col_rule)
                    conflicts.append(conflict)

    # Detect conflicts: catalog rules vs column rules (transitive)
    for catalog_id, cat_rules in catalog_rules.items():
        column_rules_in_catalog = [
            r for r in rules
            if r.get("scope") == "column" and r.get("catalogId") == catalog_id
        ]

        for cat_rule in cat_rules:
            for col_rule in column_rules_in_catalog:
                pair_key = _make_pair_key(cat_rule["id"], col_rule["id"])
                if pair_key in seen_conflict_pairs:
                    continue

                if _rules_may_conflict(cat_rule, col_rule):
                    seen_conflict_pairs.add(pair_key)
                    conflict = _build_conflict(cat_rule, col_rule)
                    conflicts.append(conflict)

    return conflicts


def _make_pair_key(id1: str, id2: str) -> str:
    """Create a consistent key for a pair of rule IDs."""
    return "|".join(sorted([id1, id2]))


def _rules_may_conflict(rule_a: dict[str, Any], rule_b: dict[str, Any]) -> bool:
    """Determine if two rules at different scope levels may conflict.

    Rules conflict when they target overlapping fields with potentially
    contradictory conditions.

    Args:
        rule_a: First rule item.
        rule_b: Second rule item.

    Returns:
        True if the rules may conflict, False otherwise.
    """
    # Get target fields from structured JSON
    fields_a = set(_get_target_fields(rule_a))
    fields_b = set(_get_target_fields(rule_b))

    # If no structured JSON, assume potential conflict based on scope overlap
    if not fields_a or not fields_b:
        return True

    # Conflicts occur when rules target overlapping fields
    overlap = fields_a & fields_b
    return len(overlap) > 0


def _get_target_fields(rule: dict[str, Any]) -> list[str]:
    """Extract target fields from a rule's structured JSON.

    Args:
        rule: Rule item dict.

    Returns:
        List of target field names.
    """
    structured = rule.get("structuredJson", {})
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (json.JSONDecodeError, ValueError):
            return []

    if not isinstance(structured, dict):
        return []

    return structured.get("targetFields", [])


def _build_conflict(rule_a: dict[str, Any], rule_b: dict[str, Any]) -> dict[str, Any]:
    """Build a conflict record from two conflicting rules.

    Args:
        rule_a: First conflicting rule.
        rule_b: Second conflicting rule.

    Returns:
        Conflict dict.
    """
    conflict_id = str(ulid.new())

    return {
        "conflictId": conflict_id,
        "rules": [
            {
                "ruleId": rule_a.get("id", ""),
                "scope": rule_a.get("scope", ""),
                "summary": rule_a.get("naturalLanguage", "")[:200],
            },
            {
                "ruleId": rule_b.get("id", ""),
                "scope": rule_b.get("scope", ""),
                "summary": rule_b.get("naturalLanguage", "")[:200],
            },
        ],
        "contradictionSummary": (
            f"Rules at '{rule_a.get('scope')}' and '{rule_b.get('scope')}' "
            f"scope levels target overlapping fields with potentially "
            f"contradictory constraints."
        ),
        "resolved": False,
    }


def _enrich_with_resolutions(
    conflicts: list[dict[str, Any]], conflicts_db: DynamoHelper
) -> list[dict[str, Any]]:
    """Enrich detected conflicts with any existing resolution data.

    Checks the dq-rule-conflicts table for previously resolved conflicts.

    Args:
        conflicts: List of detected conflict dicts.
        conflicts_db: DynamoHelper for the conflicts table.

    Returns:
        Enriched conflict list with resolution data where applicable.
    """
    enriched = []

    for conflict in conflicts:
        # Check if this conflict (based on rule pair) has been resolved
        rule_ids = sorted([r["ruleId"] for r in conflict["rules"]])
        pair_key = "|".join(rule_ids)

        # Query by pair key in conflicts table
        try:
            from boto3.dynamodb.conditions import Attr
            result = conflicts_db.scan(
                filter_expression=Attr("rulePairKey").eq(pair_key),
                pagination=PaginationParams(page_size=1, next_token=None),
            )

            if result["items"]:
                resolution = result["items"][0]
                conflict["resolved"] = True
                conflict["resolution"] = {
                    "priorityRuleId": resolution.get("priorityRuleId", ""),
                    "resolvedBy": resolution.get("resolvedBy", ""),
                    "resolvedAt": resolution.get("resolvedAt", ""),
                }
        except Exception as e:
            logger.warning(f"Failed to check resolution for conflict: {e}")

        enriched.append(conflict)

    return enriched


# ─── Resolve Conflict ─────────────────────────────────────────────────────────


def _resolve_conflict(
    event: dict[str, Any], conflict_id: str, request_id: str
) -> dict[str, Any]:
    """Resolve a conflict by selecting a priority rule (AdminDatos only).

    The selected rule remains active; other conflicting rules become "overridden".

    Request body:
    {
        "priorityRuleId": "the_rule_to_keep_active",
        "ruleIds": ["all", "rule", "ids", "in", "conflict"]
    }

    Args:
        event: API Gateway event.
        conflict_id: The conflict ID to resolve.
        request_id: The request ID.

    Returns:
        API Gateway response confirming resolution or error.
    """
    # AdminDatos only
    claims, error_response = require_role_check(event, [ADMIN_ROLE], request_id)
    if error_response:
        return error_response

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    # Validate
    priority_rule_id = body.get("priorityRuleId")
    rule_ids = body.get("ruleIds", [])

    if not priority_rule_id:
        return validation_error(
            message="priorityRuleId is required.",
            details={"field": "priorityRuleId"},
            request_id=request_id,
        )

    if not rule_ids or not isinstance(rule_ids, list) or len(rule_ids) < 2:
        return validation_error(
            message="ruleIds must be a list with at least 2 conflicting rule IDs.",
            details={"field": "ruleIds"},
            request_id=request_id,
        )

    if priority_rule_id not in rule_ids:
        return validation_error(
            message="priorityRuleId must be one of the rule IDs in the conflict.",
            details={"priorityRuleId": priority_rule_id, "ruleIds": rule_ids},
            request_id=request_id,
        )

    # Mark non-priority rules as "overridden"
    rules_db = DynamoHelper(RULES_TABLE_NAME)
    now = datetime.now(timezone.utc).isoformat()

    overridden_rule_ids = [rid for rid in rule_ids if rid != priority_rule_id]

    for rule_id in overridden_rule_ids:
        try:
            existing = rules_db.get_item(pk=f"RULE#{rule_id}", sk="METADATA")
            if existing:
                existing["status"] = "overridden"
                existing["updatedAt"] = now
                existing["GSI2PK"] = "overridden"
                rules_db.put_item(existing)
                logger.info(f"Rule '{rule_id}' marked as overridden")
        except Exception as e:
            logger.error(f"Failed to override rule '{rule_id}': {e}")
            return internal_error(
                message=f"Failed to override rule '{rule_id}'.",
                request_id=request_id,
            )

    # Store resolution record in dq-rule-conflicts table
    conflicts_db = DynamoHelper(CONFLICTS_TABLE_NAME)
    rule_pair_key = "|".join(sorted(rule_ids))

    resolution_item = {
        "PK": f"CONFLICT#{conflict_id}",
        "SK": "METADATA",
        "id": conflict_id,
        "rulePairKey": rule_pair_key,
        "ruleIds": rule_ids,
        "priorityRuleId": priority_rule_id,
        "overriddenRuleIds": overridden_rule_ids,
        "resolvedBy": claims.user_id,
        "resolvedAt": now,
        "createdAt": now,
    }

    try:
        write_with_audit(
            operation_item=resolution_item,
            operation_table=CONFLICTS_TABLE_NAME,
            operation_type="Put",
            user_id=claims.user_id,
            action_type="create",
            resource_type="rule",
            resource_id=conflict_id,
            details={
                "action": "resolve_conflict",
                "priorityRuleId": priority_rule_id,
                "overriddenRuleIds": overridden_rule_ids,
            },
        )
    except Exception as e:
        logger.error(f"Failed to store resolution record: {e}")
        return internal_error(
            message="Failed to store conflict resolution.",
            request_id=request_id,
        )

    response_body = {
        "message": "Conflict resolved successfully.",
        "conflictId": conflict_id,
        "priorityRuleId": priority_rule_id,
        "overriddenRuleIds": overridden_rule_ids,
        "resolvedBy": claims.user_id,
        "resolvedAt": now,
    }

    return success_response(response_body)


# ─── Utility Functions ────────────────────────────────────────────────────────


def _parse_body(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse the JSON body from the API Gateway event.

    Args:
        event: API Gateway event.

    Returns:
        Parsed body dict, or None if body is missing/invalid.
    """
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
