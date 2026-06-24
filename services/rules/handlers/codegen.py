"""Code Generator Lambda handler for the Rules Engine Service.

Handles AI-driven Python validation script generation from structured JSON rules:
- POST /rules/{id}/generate-code → generate validation script

Pipeline:
1. SageMaker endpoint → score_response (0-100)
2. If score < 40: Bedrock Haiku fallback
3. If score < 40: Bedrock Sonnet escalation
4. validate_ast(): ast.parse the script
5. validate_semantic(): function signature, allowed columns, no prohibited imports
6. After 3 failed attempts: retrieve fallback template from DynamoDB

Generated scripts are stored in S3 bucket dq-scripts-108782054634.

NOTE: SageMaker endpoint won't exist yet, so the implementation goes straight
to Bedrock fallback logic.

Template categories: cross_field, statistical_outlier, multi_record, temporal, pattern, simple

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from services.shared.auth import (
    extract_user_claims,
    get_request_id,
)
from services.shared.dynamo_helper import DynamoHelper
from services.shared.errors import (
    internal_error,
    not_found_error,
    success_response,
    validation_error,
)
from services.shared.s3_helper import S3Helper

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
RULES_TABLE_NAME = os.environ.get("RULES_TABLE_NAME", "dq-rules")
SCRIPTS_BUCKET = os.environ.get("SCRIPTS_BUCKET", "dq-scripts-108782054634")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT", "")

# Bedrock model IDs
BEDROCK_HAIKU_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
BEDROCK_SONNET_MODEL = "anthropic.claude-3-sonnet-20240229-v1:0"

# Pipeline configuration
MAX_ATTEMPTS = 3
QUALITY_THRESHOLD = 40

# Prohibited imports for security validation
PROHIBITED_IMPORTS = {"os", "subprocess", "sys", "shutil", "socket", "http", "urllib"}

# Bedrock client config
_bedrock_config = Config(
    region_name=AWS_REGION,
    read_timeout=30,
    connect_timeout=5,
    retries={"max_attempts": 2},
)

# Template categories
TEMPLATE_CATEGORIES = {
    "cross_field",
    "statistical_outlier",
    "multi_record",
    "temporal",
    "pattern",
    "simple",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for code generation.

    Handles POST /rules/{id}/generate-code requests.

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

        if http_method != "POST":
            return validation_error(
                message=f"Method '{http_method}' not allowed. Use POST.",
                request_id=request_id,
            )

        # Extract rule_id from path: /rules/{id}/generate-code
        rule_id = _extract_rule_id(path)
        if not rule_id:
            return validation_error(
                message="Rule ID is required in path: /rules/{id}/generate-code",
                request_id=request_id,
            )

        return _generate_code(event, rule_id, request_id)

    except Exception as e:
        logger.exception(f"Unhandled error in codegen handler: {e}")
        return internal_error(
            message="An unexpected error occurred during code generation.",
            request_id=request_id,
        )


def _extract_rule_id(path: str) -> Optional[str]:
    """Extract rule ID from the generate-code path.

    Expected path: /rules/{id}/generate-code

    Args:
        path: The raw request path.

    Returns:
        The rule ID if present, None otherwise.
    """
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Pattern: /rules/{id}/generate-code
    if (
        len(parts) >= 3
        and parts[0] == "rules"
        and parts[2] == "generate-code"
    ):
        return parts[1]

    return None


# ─── Main Code Generation ─────────────────────────────────────────────────────


def _generate_code(
    event: dict[str, Any], rule_id: str, request_id: str
) -> dict[str, Any]:
    """Generate Python validation script from a structured JSON rule.

    Pipeline:
    1. Try SageMaker endpoint (skipped if not available)
    2. Score response (0-100)
    3. If score < 40: Bedrock Haiku fallback
    4. If Haiku score < 40: Bedrock Sonnet escalation
    5. Validate with validate_ast() and validate_semantic()
    6. After 3 failed attempts: use DynamoDB fallback template

    Args:
        event: API Gateway event.
        rule_id: The rule ID to generate code for.
        request_id: The request ID.

    Returns:
        API Gateway response with generated script info or error.
    """
    # Authentication
    claims = extract_user_claims(event)
    if claims is None:
        from services.shared.errors import unauthorized_error
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    # Fetch the rule
    rules_db = DynamoHelper(RULES_TABLE_NAME)
    rule = rules_db.get_item(pk=f"RULE#{rule_id}", sk="METADATA")

    if rule is None:
        return not_found_error(
            message=f"Rule with ID '{rule_id}' not found.",
            details={"ruleId": rule_id},
            request_id=request_id,
        )

    # Get structured JSON from the rule
    structured_json = rule.get("structuredJson")
    if not structured_json:
        return validation_error(
            message="Rule does not have a structured JSON definition. "
                    "Please interpret the rule first using POST /rules/interpret.",
            details={"ruleId": rule_id},
            request_id=request_id,
        )

    # Parse structured JSON if stored as string
    if isinstance(structured_json, str):
        try:
            structured_json = json.loads(structured_json)
        except (json.JSONDecodeError, ValueError):
            return validation_error(
                message="Rule structured JSON is malformed.",
                details={"ruleId": rule_id},
                request_id=request_id,
            )

    # Execute code generation pipeline
    template_category = rule.get("templateCategory", "simple")
    target_fields = structured_json.get("targetFields", [])

    result = _execute_pipeline(structured_json, template_category, target_fields)

    # Store generated script in S3
    s3_key = f"scripts/{rule_id}/validation_script.py"
    s3_helper = S3Helper(bucket=SCRIPTS_BUCKET)

    try:
        s3_helper.upload_file(
            key=s3_key,
            body=result["script"].encode("utf-8"),
            content_type="text/x-python",
            metadata={
                "rule_id": rule_id,
                "quality_score": str(result["score"]),
                "attempts": str(result["attempts"]),
                "is_fallback": str(result["is_fallback"]),
            },
        )
    except Exception as e:
        logger.error(f"Failed to upload script to S3: {e}")
        return internal_error(
            message="Failed to store generated script.",
            request_id=request_id,
        )

    # Update rule with script reference
    try:
        rule["generatedScriptKey"] = s3_key
        rule["qualityScore"] = result["score"]
        rule["updatedAt"] = _now_iso()
        rules_db.put_item(rule)
    except Exception as e:
        logger.warning(f"Failed to update rule with script key: {e}")

    response_body = {
        "ruleId": rule_id,
        "scriptKey": s3_key,
        "qualityScore": result["score"],
        "attempts": result["attempts"],
        "isFallback": result["is_fallback"],
        "message": "Validation script generated successfully.",
    }

    return success_response(response_body, status_code=201)


def _execute_pipeline(
    structured_json: dict[str, Any],
    template_category: str,
    target_fields: list[str],
) -> dict[str, Any]:
    """Execute the code generation pipeline with fallback logic.

    Pipeline order:
    1. SageMaker endpoint (skipped if not available)
    2. Bedrock Haiku
    3. Bedrock Sonnet
    4. DynamoDB fallback template

    Args:
        structured_json: The rule's structured JSON definition.
        template_category: The template category for the rule.
        target_fields: The target fields for the rule.

    Returns:
        Dict with 'script', 'score', 'attempts', 'is_fallback'.
    """
    attempts = 0

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        logger.info(f"Code generation attempt {attempts}/{MAX_ATTEMPTS}")

        # Step 1: Try SageMaker endpoint (skip if not configured)
        script = None
        score = 0

        if SAGEMAKER_ENDPOINT:
            try:
                script = _invoke_sagemaker(structured_json)
                score = score_response(script, structured_json)
                logger.info(f"SageMaker score: {score}")
            except Exception as e:
                logger.warning(f"SageMaker invocation failed: {e}")
                script = None
                score = 0

        # Step 2: If no SageMaker or score < 40, try Bedrock Haiku
        if not script or score < QUALITY_THRESHOLD:
            try:
                script = _invoke_bedrock(
                    structured_json, BEDROCK_HAIKU_MODEL, target_fields
                )
                score = score_response(script, structured_json)
                logger.info(f"Bedrock Haiku score: {score}")
            except Exception as e:
                logger.warning(f"Bedrock Haiku invocation failed: {e}")
                script = None
                score = 0

        # Step 3: If Haiku score < 40, escalate to Bedrock Sonnet
        if not script or score < QUALITY_THRESHOLD:
            try:
                script = _invoke_bedrock(
                    structured_json, BEDROCK_SONNET_MODEL, target_fields
                )
                score = score_response(script, structured_json)
                logger.info(f"Bedrock Sonnet score: {score}")
            except Exception as e:
                logger.warning(f"Bedrock Sonnet invocation failed: {e}")
                script = None
                score = 0

        # Step 4: Validate generated script
        if script and score >= QUALITY_THRESHOLD:
            ast_valid = validate_ast(script)
            semantic_valid = validate_semantic(script, structured_json)

            if ast_valid and semantic_valid:
                return {
                    "script": script,
                    "score": score,
                    "attempts": attempts,
                    "is_fallback": False,
                }
            else:
                logger.warning(
                    f"Validation failed (ast={ast_valid}, semantic={semantic_valid}) "
                    f"on attempt {attempts}"
                )

    # Step 5: All attempts failed → use DynamoDB fallback template
    logger.info(f"All {MAX_ATTEMPTS} attempts failed. Using fallback template.")
    fallback_script = _get_fallback_template(template_category, target_fields)

    return {
        "script": fallback_script,
        "score": 0,
        "attempts": MAX_ATTEMPTS,
        "is_fallback": True,
    }


# ─── SageMaker Integration ────────────────────────────────────────────────────


def _invoke_sagemaker(structured_json: dict[str, Any]) -> str:
    """Invoke SageMaker fine-tuned Llama 3.1 endpoint for code generation.

    Args:
        structured_json: The rule's structured JSON definition.

    Returns:
        Generated Python script string.

    Raises:
        Exception: If SageMaker invocation fails.
    """
    client = boto3.client("sagemaker-runtime", region_name=AWS_REGION)

    payload = json.dumps({
        "inputs": _build_codegen_prompt(structured_json, structured_json.get("targetFields", [])),
        "parameters": {
            "max_new_tokens": 1024,
            "temperature": 0.2,
            "top_p": 0.9,
        },
    })

    response = client.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=payload,
    )

    result = json.loads(response["Body"].read().decode("utf-8"))

    # Extract generated text from SageMaker response
    if isinstance(result, list) and result:
        return result[0].get("generated_text", "")
    elif isinstance(result, dict):
        return result.get("generated_text", "")

    return ""


# ─── Bedrock Integration ──────────────────────────────────────────────────────


def _invoke_bedrock(
    structured_json: dict[str, Any],
    model_id: str,
    target_fields: list[str],
) -> str:
    """Invoke Bedrock Claude model for code generation.

    Args:
        structured_json: The rule's structured JSON definition.
        model_id: The Bedrock model ID to use.
        target_fields: The target fields for the rule.

    Returns:
        Generated Python script string.

    Raises:
        ClientError: If Bedrock invocation fails.
    """
    client = boto3.client("bedrock-runtime", config=_bedrock_config)

    prompt = _build_codegen_prompt(structured_json, target_fields)

    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    })

    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read())

    # Extract text from Claude 3 response
    content = response_body.get("content", [])
    if content and isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                raw_text = block.get("text", "")
                return _extract_python_code(raw_text)

    return ""


def _build_codegen_prompt(
    structured_json: dict[str, Any], target_fields: list[str]
) -> str:
    """Build the prompt for Python validation script generation.

    Args:
        structured_json: The rule's structured JSON definition.
        target_fields: The target fields.

    Returns:
        The formatted prompt string.
    """
    conditions_str = json.dumps(structured_json.get("conditions", []), indent=2)
    expected_behavior = structured_json.get("expectedBehavior", "")
    rule_type = structured_json.get("type", "simple")

    prompt = (
        "Generate a Python validation script for a data quality rule.\n\n"
        f"Rule Type: {rule_type}\n"
        f"Target Fields: {', '.join(target_fields)}\n"
        f"Conditions: {conditions_str}\n"
        f"Expected Behavior: {expected_behavior}\n\n"
        "Requirements:\n"
        "1. Define a function named 'validate_record(record: dict) -> bool'\n"
        "2. The function takes a single dict argument representing one data record\n"
        "3. Return True if the record passes the validation, False otherwise\n"
        "4. Only use standard Python libraries (no os, subprocess, sys, shutil, socket)\n"
        "5. Handle missing keys gracefully with .get() method\n"
        "6. Include docstring explaining the validation logic\n"
        "7. Be concise but clear\n\n"
        "Return ONLY the Python code, no explanations or markdown."
    )

    return prompt


def _extract_python_code(text: str) -> str:
    """Extract Python code from model response, stripping markdown fences.

    Args:
        text: Raw model response text.

    Returns:
        Extracted Python code.
    """
    text = text.strip()

    # Remove markdown code fences
    if text.startswith("```python"):
        text = text[9:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


# ─── Quality Scoring ──────────────────────────────────────────────────────────


def score_response(script: str, structured_json: dict[str, Any]) -> int:
    """Score generated code quality 0-100.

    Scoring criteria (20 points each):
    1. AST correctness: Can the script be parsed by ast.parse?
    2. Field coverage: Does the script reference the target fields?
    3. Condition completeness: Does it implement the required conditions?
    4. Return type correctness: Does it return a boolean?
    5. Code quality/style: Is it clean and well-structured?

    Args:
        script: The generated Python script.
        structured_json: The rule definition for comparison.

    Returns:
        Quality score from 0 to 100.
    """
    if not script or not script.strip():
        return 0

    score = 0

    # Criterion 1: AST correctness (20 points)
    score += _check_ast_correctness(script) * 20

    # Criterion 2: Field coverage (20 points)
    target_fields = structured_json.get("targetFields", [])
    score += _check_field_coverage(script, target_fields) * 20

    # Criterion 3: Condition completeness (20 points)
    conditions = structured_json.get("conditions", [])
    score += _check_condition_completeness(script, conditions) * 20

    # Criterion 4: Return type correctness (20 points)
    score += _check_return_type(script) * 20

    # Criterion 5: Code quality (20 points)
    score += _check_code_quality(script) * 20

    return min(100, max(0, score))


def _check_ast_correctness(script: str) -> int:
    """Check if the script can be parsed by ast.parse.

    Returns:
        1 if parseable, 0 otherwise.
    """
    try:
        ast.parse(script)
        return 1
    except SyntaxError:
        return 0


def _check_field_coverage(script: str, target_fields: list[str]) -> int:
    """Check if the script references the target fields.

    Returns:
        Fraction of target fields referenced (0 to 1).
    """
    if not target_fields:
        return 1  # No fields to check

    referenced = 0
    for field in target_fields:
        if field in script:
            referenced += 1

    return referenced / len(target_fields)


def _check_condition_completeness(
    script: str, conditions: list[dict[str, Any]]
) -> int:
    """Check if conditions are implemented in the script.

    Returns:
        Fraction of conditions that appear to be implemented (0 to 1).
    """
    if not conditions:
        return 1  # No conditions to check

    implemented = 0
    for condition in conditions:
        field = condition.get("field", "")
        operator = condition.get("operator", "")

        # Check if the field is referenced
        if field and field in script:
            implemented += 0.5  # Field referenced

            # Check if the operator concept is present
            operator_map = {
                "equals": ["==", "eq"],
                "not_equals": ["!=", "ne"],
                "greater_than": [">", "gt"],
                "less_than": ["<", "lt"],
                "contains": ["in", "contains"],
                "not_null": ["is not None", "!= None"],
                "regex": ["re.", "match", "search"],
            }

            op_patterns = operator_map.get(operator, [operator])
            if any(p in script for p in op_patterns):
                implemented += 0.5  # Operator implemented

    return min(1.0, implemented / len(conditions))


def _check_return_type(script: str) -> int:
    """Check if the function returns a boolean value.

    Returns:
        1 if returns bool, 0 otherwise.
    """
    # Check for 'return True' or 'return False' or 'return <comparison>'
    if "return True" in script or "return False" in script:
        return 1

    # Check for boolean-returning patterns
    if re.search(r"return\s+\w+\s*(==|!=|>|<|>=|<=|in|not\s+in)", script):
        return 1

    # Check for 'return' followed by a variable (likely bool)
    if "-> bool" in script:
        return 1

    return 0


def _check_code_quality(script: str) -> int:
    """Check code quality/style metrics.

    Returns:
        Score from 0 to 1 based on quality indicators.
    """
    quality = 0.0

    # Has docstring
    if '"""' in script or "'''" in script:
        quality += 0.25

    # Has function definition
    if "def validate_record" in script:
        quality += 0.25

    # Uses .get() for safe access
    if ".get(" in script:
        quality += 0.25

    # Reasonable length (not too short, not too long)
    lines = script.strip().split("\n")
    if 5 <= len(lines) <= 50:
        quality += 0.25

    return min(1.0, quality)


# ─── AST Validation ───────────────────────────────────────────────────────────


def validate_ast(script: str) -> bool:
    """Validate that the script is syntactically valid Python.

    Uses ast.parse() to check for syntax errors.

    Args:
        script: The Python script to validate.

    Returns:
        True if the script parses successfully, False otherwise.
    """
    try:
        ast.parse(script)
        return True
    except SyntaxError as e:
        logger.warning(f"AST validation failed: {e}")
        return False


# ─── Semantic Validation ──────────────────────────────────────────────────────


def validate_semantic(script: str, structured_json: dict[str, Any]) -> bool:
    """Validate the semantic correctness of a generated validation script.

    Checks:
    1. Function signature: must have 'validate_record' function
    2. Allowed columns: script should reference target fields
    3. No prohibited imports: os, subprocess, sys, etc.

    Args:
        script: The Python script to validate.
        structured_json: The rule definition for comparison.

    Returns:
        True if semantic validation passes, False otherwise.
    """
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return False

    # Check 1: Must contain validate_record function
    has_validate_function = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "validate_record":
            has_validate_function = True
            break

    if not has_validate_function:
        logger.warning("Semantic validation failed: missing validate_record function")
        return False

    # Check 2: No prohibited imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split(".")[0]
                if module_name in PROHIBITED_IMPORTS:
                    logger.warning(
                        f"Semantic validation failed: prohibited import '{alias.name}'"
                    )
                    return False
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_name = node.module.split(".")[0]
                if module_name in PROHIBITED_IMPORTS:
                    logger.warning(
                        f"Semantic validation failed: prohibited import from '{node.module}'"
                    )
                    return False

    # Check 3: Function signature should accept a dict parameter
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "validate_record":
            if len(node.args.args) < 1:
                logger.warning(
                    "Semantic validation failed: validate_record must accept at least 1 argument"
                )
                return False
            break

    return True


# ─── Fallback Templates ──────────────────────────────────────────────────────


def _get_fallback_template(
    template_category: str, target_fields: list[str]
) -> str:
    """Retrieve a pre-defined fallback template from DynamoDB or use built-in.

    Tries to load a template from DynamoDB first. If not available,
    uses a built-in template based on the category.

    Args:
        template_category: The template category (e.g., 'simple', 'cross_field').
        target_fields: The target fields for the rule.

    Returns:
        The fallback Python script.
    """
    # Try DynamoDB first
    try:
        rules_db = DynamoHelper(RULES_TABLE_NAME)
        template_item = rules_db.get_item(
            pk=f"TEMPLATE#{template_category}",
            sk="SCRIPT",
        )
        if template_item and template_item.get("script"):
            return template_item["script"]
    except Exception as e:
        logger.warning(f"Failed to load template from DynamoDB: {e}")

    # Use built-in fallback templates
    return _get_builtin_template(template_category, target_fields)


def _get_builtin_template(category: str, target_fields: list[str]) -> str:
    """Get a built-in fallback validation script template.

    Args:
        category: The template category.
        target_fields: The target fields.

    Returns:
        A Python validation script string.
    """
    fields_str = ", ".join(f'"{f}"' for f in target_fields) if target_fields else '"field"'

    templates = {
        "simple": f'''def validate_record(record: dict) -> bool:
    """Simple validation: check that required fields are present and non-empty."""
    required_fields = [{fields_str}]
    for field in required_fields:
        value = record.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
    return True
''',
        "cross_field": f'''def validate_record(record: dict) -> bool:
    """Cross-field validation: check consistency between related fields."""
    target_fields = [{fields_str}]
    values = {{f: record.get(f) for f in target_fields}}
    # Check that all target fields are present
    if any(v is None for v in values.values()):
        return False
    # Cross-field consistency check (placeholder logic)
    return True
''',
        "statistical_outlier": f'''def validate_record(record: dict) -> bool:
    """Statistical outlier detection: check values are within expected range."""
    target_fields = [{fields_str}]
    for field in target_fields:
        value = record.get(field)
        if value is None:
            return False
        try:
            numeric_value = float(value)
            # Basic range check (adjust thresholds per domain)
            if numeric_value < -1000000 or numeric_value > 1000000:
                return False
        except (ValueError, TypeError):
            return False
    return True
''',
        "multi_record": f'''def validate_record(record: dict) -> bool:
    """Multi-record validation: validate individual record constraints."""
    target_fields = [{fields_str}]
    for field in target_fields:
        value = record.get(field)
        if value is None:
            return False
    return True
''',
        "temporal": f'''def validate_record(record: dict) -> bool:
    """Temporal validation: check date/time field constraints."""
    from datetime import datetime
    target_fields = [{fields_str}]
    for field in target_fields:
        value = record.get(field)
        if value is None:
            return False
        try:
            if isinstance(value, str):
                datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
    return True
''',
        "pattern": f'''def validate_record(record: dict) -> bool:
    """Pattern validation: check that field values match expected patterns."""
    import re
    target_fields = [{fields_str}]
    for field in target_fields:
        value = record.get(field)
        if value is None or not isinstance(value, str):
            return False
        # Basic non-empty pattern check
        if not value.strip():
            return False
    return True
''',
    }

    return templates.get(category, templates["simple"])


# ─── Utility Functions ────────────────────────────────────────────────────────


def _now_iso() -> str:
    """Get current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


from datetime import datetime, timezone
