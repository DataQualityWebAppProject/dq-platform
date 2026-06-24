"""Rule Interpreter Lambda handler for the Rules Engine Service.

Handles natural language rule interpretation via Amazon Bedrock Claude 3 Haiku:
- POST /rules/interpret → interpret natural language into structured JSON

Uses Bedrock Claude 3 Haiku (anthropic.claude-3-haiku-20240307-v1:0) to:
1. Accept natural language text (1-500 chars) + scope + target IDs
2. Build prompt for interpretation
3. Parse response into RuleDefinition structure
4. Generate human-readable preview

Requirements: 5.1, 5.2, 5.5, 5.6, 6.1, 6.2, 6.5, 6.6, 7.1, 7.2, 7.5, 7.6
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError, ReadTimeoutError
from botocore.config import Config

from services.shared.auth import (
    extract_user_claims,
    get_request_id,
)
from services.shared.errors import (
    internal_error,
    success_response,
    validation_error,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
BEDROCK_TIMEOUT = 5  # seconds

# Validation limits
MAX_NL_LENGTH = 500
MIN_NL_LENGTH = 1

# Valid scopes
VALID_SCOPES = {"catalog", "table", "column"}

# Bedrock client configuration with timeout
_bedrock_config = Config(
    region_name=AWS_REGION,
    read_timeout=BEDROCK_TIMEOUT,
    connect_timeout=3,
    retries={"max_attempts": 1},
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for rule interpretation.

    Accepts POST /rules/interpret with natural language text and scope,
    invokes Bedrock Claude 3 Haiku, and returns structured JSON + preview.

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

        if http_method != "POST":
            return validation_error(
                message=f"Method '{http_method}' not allowed. Use POST.",
                request_id=request_id,
            )

        return _interpret_rule(event, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in interpreter handler: {e}")
        return internal_error(
            message="An unexpected error occurred while interpreting the rule.",
            request_id=request_id,
        )


def _interpret_rule(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Interpret natural language rule into structured JSON.

    Request body:
    {
        "naturalLanguage": "Text describing the rule (1-500 chars)",
        "scope": "catalog" | "table" | "column",
        "catalogId": "required",
        "tableId": "required if scope is table/column",
        "columnId": "required if scope is column"
    }

    Response:
    {
        "structuredJson": { RuleDefinition },
        "preview": {
            "ruleName": "...",
            "conditions": "...",
            "targetScope": "...",
            "expectedBehavior": "..."
        }
    }

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        API Gateway response with structured JSON and preview, or error.
    """
    # Authentication
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    # Validate request
    errors = _validate_interpret_request(body)
    if errors:
        return validation_error(
            message="Validation failed. Required fields are missing or invalid.",
            details={"fields": errors},
            request_id=request_id,
        )

    natural_language = body["naturalLanguage"].strip()
    scope = body["scope"]
    catalog_id = body["catalogId"]
    table_id = body.get("tableId", "")
    column_id = body.get("columnId", "")

    # Build the interpretation prompt
    prompt = _build_interpretation_prompt(
        text=natural_language,
        scope=scope,
        catalog_id=catalog_id,
        table_id=table_id,
        column_id=column_id,
    )

    # Invoke Bedrock Claude 3 Haiku
    try:
        bedrock_response = _invoke_bedrock(prompt)
    except ReadTimeoutError:
        logger.warning("Bedrock interpretation timed out")
        return internal_error(
            message=(
                "Rule interpretation timed out. Please try again with a simpler "
                "rule description or try again later."
            ),
            details={"timeout": BEDROCK_TIMEOUT, "naturalLanguage": natural_language},
            request_id=request_id,
        )
    except (ClientError, Exception) as e:
        logger.error(f"Bedrock invocation failed: {e}")
        return internal_error(
            message=(
                "Failed to interpret the rule. The AI service is unavailable. "
                "Please revise and resubmit the rule description."
            ),
            details={"naturalLanguage": natural_language},
            request_id=request_id,
        )

    # Parse the Bedrock response into structured JSON
    structured_json = _parse_bedrock_response(bedrock_response)
    if structured_json is None:
        return internal_error(
            message=(
                "Failed to produce a structured interpretation from the submitted text. "
                "Please revise and resubmit the rule description."
            ),
            details={"naturalLanguage": natural_language},
            request_id=request_id,
        )

    # Generate human-readable preview
    preview = _generate_preview(structured_json, scope, catalog_id, table_id, column_id)

    response_body = {
        "structuredJson": structured_json,
        "preview": preview,
    }

    return success_response(response_body)


def _validate_interpret_request(body: dict[str, Any]) -> dict[str, str]:
    """Validate the interpret rule request body.

    Args:
        body: The parsed request body.

    Returns:
        Dict of field name → error message for invalid fields.
    """
    errors: dict[str, str] = {}

    # naturalLanguage: required, 1-500 chars
    nl = body.get("naturalLanguage")
    if not nl or not str(nl).strip():
        errors["naturalLanguage"] = "Natural language rule description is required."
    elif len(str(nl).strip()) < MIN_NL_LENGTH:
        errors["naturalLanguage"] = (
            f"Natural language text must be at least {MIN_NL_LENGTH} character(s)."
        )
    elif len(str(nl).strip()) > MAX_NL_LENGTH:
        errors["naturalLanguage"] = (
            f"Natural language text must not exceed {MAX_NL_LENGTH} characters."
        )

    # scope: required, must be valid
    scope = body.get("scope")
    if not scope:
        errors["scope"] = "Scope is required (catalog, table, or column)."
    elif scope not in VALID_SCOPES:
        errors["scope"] = (
            f"Invalid scope '{scope}'. Must be one of: {', '.join(VALID_SCOPES)}."
        )

    # catalogId: always required
    catalog_id = body.get("catalogId")
    if not catalog_id or not str(catalog_id).strip():
        errors["catalogId"] = "Catalog ID is required."

    # tableId: required if scope is table or column
    if scope in ("table", "column"):
        table_id = body.get("tableId")
        if not table_id or not str(table_id).strip():
            errors["tableId"] = f"Table ID is required for scope '{scope}'."

    # columnId: required if scope is column
    if scope == "column":
        column_id = body.get("columnId")
        if not column_id or not str(column_id).strip():
            errors["columnId"] = "Column ID is required for scope 'column'."

    return errors


def _build_interpretation_prompt(
    text: str,
    scope: str,
    catalog_id: str,
    table_id: str = "",
    column_id: str = "",
) -> str:
    """Build the prompt for Bedrock Claude 3 Haiku to interpret a rule.

    Args:
        text: The natural language rule description.
        scope: The rule scope (catalog, table, column).
        catalog_id: The catalog ID.
        table_id: The table ID (if applicable).
        column_id: The column ID (if applicable).

    Returns:
        The formatted prompt string.
    """
    scope_context = f"Scope: {scope}"
    if scope == "catalog":
        scope_context += f" (applies to all tables in catalog '{catalog_id}')"
    elif scope == "table":
        scope_context += f" (applies to table '{table_id}' in catalog '{catalog_id}')"
    elif scope == "column":
        scope_context += (
            f" (applies to column '{column_id}' in table '{table_id}' "
            f"in catalog '{catalog_id}')"
        )

    prompt = (
        "Interpret this data quality rule into structured JSON: "
        f"{text}. {scope_context}. "
        "Return JSON with: type (one of: cross_field, statistical_outlier, "
        "multi_record, temporal, pattern, simple), conditions (array of objects "
        "with field, operator, value, and optional logicalOperator), "
        "targetFields (array of field names), expectedBehavior (string describing "
        "what should happen when rule is applied). "
        "Respond ONLY with valid JSON, no additional text."
    )

    return prompt


def _invoke_bedrock(prompt: str) -> str:
    """Invoke Bedrock Claude 3 Haiku with the interpretation prompt.

    Args:
        prompt: The prompt to send to the model.

    Returns:
        The model response text.

    Raises:
        ClientError: If the Bedrock invocation fails.
        ReadTimeoutError: If the request times out.
    """
    client = boto3.client("bedrock-runtime", config=_bedrock_config)

    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    })

    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read())

    # Extract text from Claude 3 response format
    content = response_body.get("content", [])
    if content and isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                return block.get("text", "")

    return ""


def _parse_bedrock_response(response_text: str) -> Optional[dict[str, Any]]:
    """Parse the Bedrock response text into a RuleDefinition structure.

    Attempts to extract valid JSON from the response. Handles cases where
    the model wraps the JSON in markdown code blocks.

    Args:
        response_text: The raw text response from Bedrock.

    Returns:
        Parsed RuleDefinition dict, or None if parsing fails.
    """
    if not response_text:
        return None

    # Try direct JSON parse first
    try:
        parsed = json.loads(response_text)
        return _normalize_rule_definition(parsed)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting JSON from markdown code block
    text = response_text.strip()
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        json_str = text[start:end].strip()
        try:
            parsed = json.loads(json_str)
            return _normalize_rule_definition(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        json_str = text[start:end].strip()
        try:
            parsed = json.loads(json_str)
            return _normalize_rule_definition(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

    # Try finding JSON object in the response
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        json_str = text[brace_start : brace_end + 1]
        try:
            parsed = json.loads(json_str)
            return _normalize_rule_definition(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning(f"Failed to parse Bedrock response: {response_text[:200]}")
    return None


def _normalize_rule_definition(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parsed response into the RuleDefinition structure.

    Ensures the response has the expected fields with correct types.

    Args:
        parsed: The raw parsed JSON from Bedrock.

    Returns:
        Normalized RuleDefinition dict.
    """
    valid_types = {
        "cross_field",
        "statistical_outlier",
        "multi_record",
        "temporal",
        "pattern",
        "simple",
    }

    rule_type = parsed.get("type", "simple")
    if rule_type not in valid_types:
        rule_type = "simple"

    conditions = parsed.get("conditions", [])
    if not isinstance(conditions, list):
        conditions = []

    # Normalize each condition
    normalized_conditions = []
    for condition in conditions:
        if isinstance(condition, dict):
            normalized_conditions.append({
                "field": str(condition.get("field", "")),
                "operator": str(condition.get("operator", "")),
                "value": condition.get("value"),
                "logicalOperator": condition.get("logicalOperator"),
            })

    target_fields = parsed.get("targetFields", [])
    if not isinstance(target_fields, list):
        target_fields = [str(target_fields)] if target_fields else []

    expected_behavior = str(parsed.get("expectedBehavior", ""))

    parameters = parsed.get("parameters", {})
    if not isinstance(parameters, dict):
        parameters = {}

    return {
        "type": rule_type,
        "conditions": normalized_conditions,
        "targetFields": target_fields,
        "expectedBehavior": expected_behavior,
        "parameters": parameters,
    }


def _generate_preview(
    structured_json: dict[str, Any],
    scope: str,
    catalog_id: str,
    table_id: str = "",
    column_id: str = "",
) -> dict[str, Any]:
    """Generate a human-readable preview of the interpreted rule.

    Args:
        structured_json: The RuleDefinition structure.
        scope: The rule scope.
        catalog_id: The catalog ID.
        table_id: The table ID (if applicable).
        column_id: The column ID (if applicable).

    Returns:
        Preview dict with ruleName, conditions, targetScope, expectedBehavior.
    """
    # Build rule name from type and target fields
    rule_type = structured_json.get("type", "simple")
    target_fields = structured_json.get("targetFields", [])

    rule_name = f"{rule_type.replace('_', ' ').title()} Rule"
    if target_fields:
        rule_name += f" on {', '.join(target_fields[:3])}"
        if len(target_fields) > 3:
            rule_name += f" (+{len(target_fields) - 3} more)"

    # Build conditions summary
    conditions = structured_json.get("conditions", [])
    conditions_summary_parts = []
    for cond in conditions[:5]:  # Limit to 5 conditions in summary
        field = cond.get("field", "?")
        operator = cond.get("operator", "?")
        value = cond.get("value", "?")
        conditions_summary_parts.append(f"{field} {operator} {value}")

    conditions_summary = "; ".join(conditions_summary_parts) if conditions_summary_parts else "No specific conditions defined"
    if len(conditions) > 5:
        conditions_summary += f" (+{len(conditions) - 5} more conditions)"

    # Build target scope description
    if scope == "catalog":
        target_scope = f"All tables in catalog '{catalog_id}'"
    elif scope == "table":
        target_scope = f"Table '{table_id}' in catalog '{catalog_id}'"
    elif scope == "column":
        target_scope = f"Column '{column_id}' in table '{table_id}'"
    else:
        target_scope = f"Scope: {scope}"

    # Expected behavior
    expected_behavior = structured_json.get("expectedBehavior", "Not specified")

    return {
        "ruleName": rule_name,
        "conditions": conditions_summary,
        "targetScope": target_scope,
        "expectedBehavior": expected_behavior,
    }


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
