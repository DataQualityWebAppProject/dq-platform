"""Report Generator Lambda handler.

Handles HTTP API routes for AI-powered report generation:
- POST /reports/generate → invoke Bedrock Sonnet to generate a report

Generates executive reports with:
- Quality scores summary
- Trend analysis
- Detected anomalies
- Recommendations

Stores draft report in DynamoDB.

DynamoDB Table: dq-reports
- PK: REPORT#{report_id}
- SK: METADATA
- Version entries: SK: VERSION#{version_number}

Requirements: 16.1, 16.5, 20.5
"""

from __future__ import annotations

import json
import logging
import os
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
    internal_error,
    success_response,
    unauthorized_error,
    validation_error,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "dq-reports")
VALIDATION_RUNS_TABLE = os.environ.get("VALIDATION_RUNS_TABLE", "dq-validation-runs")
SCORING_TABLE = os.environ.get("SCORING_TABLE", "dq-anomaly-scores")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Bedrock model for report generation
BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
BEDROCK_MAX_TOKENS = 8192
BEDROCK_TIMEOUT = 30  # 30 seconds max


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for report generation.

    Routes:
    - POST /reports/generate → generate a new report

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response.
    """
    request_id = get_request_id(event)

    try:
        http_method = event.get("requestContext", {}).get("http", {}).get("method", "")

        if http_method == "POST":
            return _generate_report(event, request_id)
        else:
            return validation_error(
                message=f"Unsupported method: {http_method}",
                request_id=request_id,
            )

    except Exception as e:
        logger.exception(f"Unhandled error in report generator handler: {e}")
        return internal_error(
            message="An unexpected error occurred while generating the report.",
            request_id=request_id,
        )


def _generate_report(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Generate a new executive report using Bedrock Sonnet.

    Expected body:
    {
        "datasetId": "..." (optional, for dataset-specific report),
        "title": "...",
        "reportType": "executive" | "detailed" (default: "executive")
    }

    Args:
        event: API Gateway event.
        request_id: The request ID.

    Returns:
        Generated report draft.
    """
    # Authentication check
    claims = extract_user_claims(event)
    if claims is None:
        return unauthorized_error(
            message="Authentication required.",
            request_id=request_id,
        )

    if claims.role not in [ADMIN_ROLE, ANALYST_ROLE]:
        from services.shared.errors import forbidden_error
        return forbidden_error(
            message="You do not have permission to generate reports.",
            request_id=request_id,
        )

    # Parse body
    body = _parse_body(event)
    if body is None:
        return validation_error(
            message="Request body is required and must be valid JSON.",
            request_id=request_id,
        )

    dataset_id = body.get("datasetId")
    title = body.get("title", "Data Quality Report")
    report_type = body.get("reportType", "executive")

    # Gather context data for report generation
    context_data = _gather_report_context(dataset_id)

    # Generate report via Bedrock
    try:
        report_content = _invoke_bedrock_for_report(
            title=title,
            report_type=report_type,
            context_data=context_data,
        )
    except Exception as e:
        logger.error(f"Bedrock report generation failed: {e}")
        return internal_error(
            message="Failed to generate report. Please try again.",
            request_id=request_id,
        )

    # Create report record (status: draft)
    report_id = str(ulid.new())
    now = datetime.now(timezone.utc).isoformat()

    report_item = {
        "PK": f"REPORT#{report_id}",
        "SK": "METADATA",
        "id": report_id,
        "title": title,
        "reportType": report_type,
        "datasetId": dataset_id,
        "content": report_content,
        "status": "draft",
        "version": 1,
        "createdAt": now,
        "updatedAt": now,
        "createdBy": claims.user_id,
        "publishedAt": None,
        "publishedBy": None,
    }

    # Also store version 1
    version_item = {
        "PK": f"REPORT#{report_id}",
        "SK": "VERSION#1",
        "version": 1,
        "content": report_content,
        "editedAt": now,
        "editedBy": claims.user_id,
    }

    db = DynamoHelper(REPORTS_TABLE)

    try:
        db.batch_write([report_item, version_item])
    except ClientError as e:
        logger.error(f"Failed to create report record: {e}")
        return internal_error(
            message="Failed to save report.",
            request_id=request_id,
        )

    return success_response(
        {
            "reportId": report_id,
            "title": title,
            "status": "draft",
            "content": report_content,
            "version": 1,
            "createdAt": now,
        },
        status_code=201,
    )


def _gather_report_context(dataset_id: Optional[str]) -> dict[str, Any]:
    """Gather context data for report generation.

    Fetches recent validation runs, anomaly scores, and other
    relevant data to feed into the report generation prompt.

    Args:
        dataset_id: Optional dataset ID to scope the report.

    Returns:
        Context data dictionary.
    """
    from boto3.dynamodb.conditions import Attr
    from services.shared.pagination import PaginationParams

    context_data: dict[str, Any] = {
        "validationRuns": [],
        "anomalyScores": [],
        "datasetId": dataset_id,
    }

    # Fetch recent validation runs
    try:
        validation_db = DynamoHelper(VALIDATION_RUNS_TABLE)
        filter_expr = Attr("SK").eq("METADATA") & Attr("status").eq("completed")
        if dataset_id:
            filter_expr = filter_expr & Attr("datasetId").eq(dataset_id)

        pagination = PaginationParams(page_size=20, next_token=None)
        result = validation_db.scan(filter_expression=filter_expr, pagination=pagination)

        context_data["validationRuns"] = [
            {
                "datasetId": r.get("datasetId"),
                "score": r.get("score"),
                "startedAt": r.get("startedAt"),
                "rulesCount": r.get("rulesCount"),
            }
            for r in result.get("items", [])
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch validation runs for report: {e}")

    # Fetch recent anomaly scores
    try:
        scoring_db = DynamoHelper(SCORING_TABLE)
        filter_expr = Attr("SK").eq("METADATA") & Attr("status").eq("completed")
        pagination = PaginationParams(page_size=10, next_token=None)
        result = scoring_db.scan(filter_expression=filter_expr, pagination=pagination)

        context_data["anomalyScores"] = [
            {
                "datasetId": r.get("datasetId"),
                "summary": r.get("summary", {}),
                "startedAt": r.get("startedAt"),
            }
            for r in result.get("items", [])
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch anomaly scores for report: {e}")

    return context_data


def _invoke_bedrock_for_report(
    title: str, report_type: str, context_data: dict[str, Any]
) -> str:
    """Invoke Bedrock Claude 3 Sonnet to generate a report.

    Args:
        title: Report title.
        report_type: Type of report (executive/detailed).
        context_data: Context data gathered for the report.

    Returns:
        Generated report content (Markdown format).
    """
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    # Format context data
    validation_summary = ""
    if context_data.get("validationRuns"):
        runs = context_data["validationRuns"]
        scores = [r["score"] for r in runs if r.get("score") is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        validation_summary = f"""
Validation Summary:
- Total runs: {len(runs)}
- Average quality score: {avg_score:.1f}%
- Score range: {min(scores) if scores else 0:.1f}% - {max(scores) if scores else 0:.1f}%
"""

    anomaly_summary = ""
    if context_data.get("anomalyScores"):
        scoring_runs = context_data["anomalyScores"]
        anomaly_summary = f"\nAnomaly Detection Summary:\n- Scoring runs: {len(scoring_runs)}\n"
        for run in scoring_runs[:5]:
            summary = run.get("summary", {})
            anomaly_summary += f"- Dataset {run.get('datasetId', 'unknown')}: {summary.get('anomalyCount', 0)} anomalies ({summary.get('anomalyPercentage', 0):.1f}%)\n"

    prompt = f"""Generate a professional {report_type} data quality report with the title: "{title}"

Context data:
{validation_summary}
{anomaly_summary}

Generate a comprehensive report in Markdown format with the following sections:
1. **Executive Summary** - High-level overview of data quality status
2. **Quality Scores Summary** - Breakdown of validation scores and trends
3. **Trend Analysis** - How data quality has changed over time
4. **Detected Anomalies** - Summary of anomalies found
5. **Recommendations** - Actionable recommendations for improving data quality

Make the report professional, data-driven, and actionable. Use specific numbers from the context data where available. If no data is available for a section, note that data collection is in progress."""

    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": BEDROCK_MAX_TOKENS,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
    })

    response = bedrock_client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read().decode("utf-8"))
    content = response_body.get("content", [{}])[0].get("text", "")

    return content


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
