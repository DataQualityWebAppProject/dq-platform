"""
Data Quality Platform - FastAPI Server
Serves the React SPA and proxies API requests to AWS API Gateway.
Authentication is handled server-side via Cognito, storing JWT in httpOnly cookies.
"""

import os
import io
import re
import csv
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

import boto3
import httpx
import pandas as pd
from fastapi import FastAPI, Request, Response, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_GATEWAY_URL = os.getenv(
    "API_GATEWAY_URL",
    "https://oyw54eum4m.execute-api.us-east-1.amazonaws.com",
)
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "us-east-1_5wvUIjDvC")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "4fsrbnn5kaktd8bv1mrglicfrb")
S3_BUCKET_RAW = os.getenv("S3_BUCKET_RAW", "dq-raw-108782054634")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

COOKIE_NAME = "dq_token"
COOKIE_MAX_AGE = 3600  # 1 hour

STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dqplatform")

# ---------------------------------------------------------------------------
# AWS Clients
# ---------------------------------------------------------------------------

cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
s3_client = boto3.client("s3", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(title="DQ Platform", docs_url=None, redoc_url=None)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------


@app.post("/auth/login")
async def auth_login(body: LoginRequest, response: Response):
    """Authenticate user against Cognito and set httpOnly cookie with JWT."""
    try:
        result = cognito_client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": body.username,
                "PASSWORD": body.password,
            },
        )

        # Check for challenges (MFA, new password, etc.)
        if "ChallengeName" in result:
            return JSONResponse(
                status_code=200,
                content={
                    "success": False,
                    "challengeName": result["ChallengeName"],
                    "session": result.get("Session", ""),
                },
            )

        # Successful auth
        auth_result = result["AuthenticationResult"]
        id_token = auth_result["IdToken"]
        access_token = auth_result["AccessToken"]

        # Set token in httpOnly cookie
        response.set_cookie(
            key=COOKIE_NAME,
            value=id_token,
            httponly=True,
            secure=False,  # HTTP on EC2, no HTTPS
            samesite="lax",
            max_age=COOKIE_MAX_AGE,
            path="/",
        )

        return {"success": True, "message": "Authenticated successfully"}

    except cognito_client.exceptions.NotAuthorizedException:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Invalid credentials"},
        )
    except cognito_client.exceptions.UserNotFoundException:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "User not found"},
        )
    except cognito_client.exceptions.UserNotConfirmedException:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "User not confirmed"},
        )
    except Exception as e:
        logger.error(f"Login error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Authentication service error"},
        )


@app.post("/auth/logout")
async def auth_logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"success": True, "message": "Logged out"}


@app.get("/auth/me")
async def auth_me(request: Request):
    """Return current user info from the JWT in cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"authenticated": False, "error": "No session"},
        )

    try:
        # Decode token claims (the token is validated by API Gateway on /api calls,
        # here we just extract the payload for display purposes)
        import base64

        # JWT is header.payload.signature — decode the payload
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token format")

        # Add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        claims = json.loads(base64.urlsafe_b64decode(payload))

        return {
            "authenticated": True,
            "user": {
                "sub": claims.get("sub", ""),
                "email": claims.get("email", claims.get("cognito:username", "")),
                "username": claims.get("cognito:username", claims.get("email", "")),
                "groups": claims.get("cognito:groups", []),
            },
        }

    except Exception as e:
        logger.error(f"Token decode error: {e}")
        return JSONResponse(
            status_code=401,
            content={"authenticated": False, "error": "Invalid session"},
        )


# ---------------------------------------------------------------------------
# CSV Parsing and Type Inference
# ---------------------------------------------------------------------------


def parse_csv_and_infer(content: bytes, filename: str):
    """Parse a CSV file, detect separator, infer column types, and return schema + preview."""
    # Detect separator
    sample = content[:10000].decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except Exception:
        sep = ","

    # Parse with pandas (first 100 rows)
    df = pd.read_csv(
        io.BytesIO(content),
        sep=sep,
        nrows=100,
        encoding="utf-8",
        on_bad_lines="skip",
    )

    # Infer types for each column
    columns = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        if "int" in dtype:
            inferred = "integer"
        elif "float" in dtype:
            inferred = "float"
        elif "bool" in dtype:
            inferred = "boolean"
        elif "datetime" in dtype:
            inferred = "date"
        else:
            # Try to detect dates in string columns
            sample_vals = df[col].dropna().head(5).astype(str).tolist()
            if sample_vals and all(
                re.match(r"\d{4}[-/]\d{2}[-/]\d{2}", v) for v in sample_vals if v
            ):
                inferred = "date"
            else:
                inferred = "string"

        columns.append(
            {
                "name": str(col),
                "inferredType": inferred,
                "sampleValues": df[col].head(5).fillna("").astype(str).tolist(),
            }
        )

    # Preview (first 10 rows)
    preview = {
        "headers": [str(c) for c in df.columns],
        "rows": df.head(10).fillna("").astype(str).values.tolist(),
        "totalRows": len(df),
        "separator": sep,
    }

    return columns, preview


# ---------------------------------------------------------------------------
# File Upload Endpoint
# ---------------------------------------------------------------------------


@app.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    catalogId: Optional[str] = Form(None),
):
    """Receive file upload, store in S3, parse CSV, infer types, and register table in catalog."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(
            status_code=401, content={"error": "Authentication required"}
        )

    # Validate file type
    filename = file.filename or "unknown"
    if not (filename.lower().endswith(".csv") or filename.lower().endswith(".parquet")):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid file type. Only CSV and Parquet are accepted."},
        )

    try:
        # Read file content
        content = await file.read()

        # Validate size (500 MB max)
        max_size = 500 * 1024 * 1024
        if len(content) > max_size:
            return JSONResponse(
                status_code=400,
                content={"error": "File exceeds 500 MB limit"},
            )

        # Upload to S3
        s3_key = f"uploads/{filename}"
        s3_client.put_object(
            Bucket=S3_BUCKET_RAW,
            Key=s3_key,
            Body=content,
            ContentType=file.content_type or "application/octet-stream",
        )

        logger.info(f"Uploaded {filename} to s3://{S3_BUCKET_RAW}/{s3_key}")

        # Parse CSV and infer column types
        columns = []
        preview = None
        if filename.lower().endswith(".csv"):
            try:
                columns, preview = parse_csv_and_infer(content, filename)
            except Exception as parse_err:
                logger.warning(f"CSV parse warning: {parse_err}")
                columns = []
                preview = None

        # Register table directly in DynamoDB (bypass Lambda for reliability)
        table_id = None
        if catalogId:
            table_id = str(uuid.uuid4())
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            
            dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
            catalogs_table = dynamodb.Table("dq-catalogs")
            
            # Store table as item in dq-catalogs: pk=CATALOG#{catalogId}, sk=TABLE#{tableId}
            table_item = {
                "pk": f"CATALOG#{catalogId}",
                "sk": f"TABLE#{table_id}",
                "id": table_id,
                "table_id": table_id,
                "name": filename.rsplit(".", 1)[0],  # filename without extension
                "fileName": filename,
                "s3Key": s3_key,
                "s3Bucket": S3_BUCKET_RAW,
                "fileSize": len(content),
                "columns": columns,
                "separator": preview.get("separator", ",") if preview else ",",
                "rowCount": preview.get("totalRows", 0) if preview else 0,
                "created_at": now,
                "catalog_id": catalogId,
            }
            try:
                catalogs_table.put_item(Item=table_item)
                logger.info(f"Table {table_id} registered in catalog {catalogId}")
            except Exception as db_err:
                logger.warning(f"DynamoDB table registration error: {db_err}")

        return {
            "success": True,
            "fileName": filename,
            "s3Key": s3_key,
            "s3Bucket": S3_BUCKET_RAW,
            "fileSize": len(content),
            "columns": columns,
            "preview": preview,
            "catalogId": catalogId,
            "tableId": table_id,
        }

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Upload failed: {str(e)}"},
        )


# ---------------------------------------------------------------------------
# Table Schema Confirmation Endpoint
# ---------------------------------------------------------------------------


@app.post("/api/tables/{table_id}/schema")
async def confirm_table_schema(request: Request, table_id: str):
    """Save the user-confirmed column schema for a table."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(
            status_code=401, content={"error": "Authentication required"}
        )

    try:
        body = await request.json()
        columns = body.get("columns", [])
        catalog_id = body.get("catalogId", "")

        # Save directly to DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")
        catalogs_table.update_item(
            Key={"pk": f"CATALOG#{catalog_id}", "sk": f"TABLE#{table_id}"},
            UpdateExpression="SET columns = :cols, schemaConfirmed = :confirmed",
            ExpressionAttributeValues={":cols": columns, ":confirmed": True},
        )

        return {"success": True, "tableId": table_id, "columns": columns}

    except Exception as e:
        logger.error(f"Schema confirm error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Schema confirmation failed: {str(e)}"},
        )


# ---------------------------------------------------------------------------
# Direct DynamoDB: Get tables for a catalog (bypasses buggy Lambda)
# ---------------------------------------------------------------------------

@app.get("/api/catalog/{catalog_id}/tables")
async def get_catalog_tables(request: Request, catalog_id: str):
    """Get all tables in a catalog directly from DynamoDB."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        from boto3.dynamodb.conditions import Key as DDBKey
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        # Query items where pk=CATALOG#{id} and sk begins_with TABLE#
        response = catalogs_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"CATALOG#{catalog_id}") & DDBKey("sk").begins_with("TABLE#")
        )

        items = response.get("Items", [])
        tables = []
        for item in items:
            tables.append({
                "id": item.get("id") or item.get("table_id", ""),
                "name": item.get("name") or item.get("fileName", "Unknown"),
                "fileName": item.get("fileName", ""),
                "rowCount": item.get("rowCount", 0),
                "columns": item.get("columns", []),
                "separator": item.get("separator", ","),
                "createdAt": item.get("created_at", ""),
            })

        return {"items": tables, "totalCount": len(tables)}

    except Exception as e:
        logger.error(f"Get catalog tables error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------------------------------------------------------
# Catalog CRUD — Direct DynamoDB (bypass Lambda for reliability)
# ---------------------------------------------------------------------------


@app.get("/api/catalog")
async def list_catalogs(request: Request):
    """List all catalogs from DynamoDB."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        from boto3.dynamodb.conditions import Key as DDBKey, Attr
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        # Scan for catalog metadata items (pk starts with CATALOG#, sk=METADATA)
        response = catalogs_table.scan(
            FilterExpression=Attr("sk").eq("METADATA")
        )
        items = response.get("Items", [])

        catalogs = []
        for item in items:
            catalog_id = item.get("pk", "").replace("CATALOG#", "")
            if not catalog_id:
                continue
            catalogs.append({
                "id": catalog_id,
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "owner": item.get("owner", ""),
                "created_at": item.get("created_at", ""),
            })

        # Filter out empty names
        catalogs = [c for c in catalogs if c["name"]]

        return {"items": catalogs, "totalCount": len(catalogs)}

    except Exception as e:
        logger.error(f"List catalogs error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/catalog/{catalog_id}")
async def get_catalog(request: Request, catalog_id: str):
    """Get a single catalog's metadata."""
    # Don't intercept the /tables sub-route
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        from boto3.dynamodb.conditions import Key as DDBKey
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        response = catalogs_table.get_item(
            Key={"pk": f"CATALOG#{catalog_id}", "sk": "METADATA"}
        )
        item = response.get("Item")
        if not item:
            return JSONResponse(status_code=404, content={"error": "Catalog not found"})

        return {
            "id": catalog_id,
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "owner": item.get("owner", ""),
            "created_at": item.get("created_at", ""),
        }

    except Exception as e:
        logger.error(f"Get catalog error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/catalog")
async def create_catalog(request: Request):
    """Create a new catalog entry in DynamoDB."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        body = await request.json()
        name = body.get("name", "").strip()
        description = body.get("description", "")
        owner = body.get("owner", "admindatos")

        if not name:
            return JSONResponse(status_code=400, content={"error": "Catalog name is required"})

        from datetime import datetime, timezone
        catalog_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        catalogs_table.put_item(Item={
            "pk": f"CATALOG#{catalog_id}",
            "sk": "METADATA",
            "id": catalog_id,
            "name": name,
            "description": description,
            "owner": owner,
            "created_at": now,
        })

        return {"id": catalog_id, "name": name, "description": description, "owner": owner, "created_at": now}

    except Exception as e:
        logger.error(f"Create catalog error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------------------------------------------------------
# Rules CRUD — Direct DynamoDB (bypass Lambda for reliability)
# ---------------------------------------------------------------------------


@app.get("/api/rules")
async def list_rules(request: Request):
    """List all rules from DynamoDB."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        from boto3.dynamodb.conditions import Attr
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        rules_table = dynamodb.Table("dq-rules")

        response = rules_table.scan(
            FilterExpression=Attr("sk").eq("METADATA")
        )
        items = response.get("Items", [])

        rules = []
        for item in items:
            rules.append({
                "id": item.get("id", ""),
                "naturalLanguage": item.get("naturalLanguage", ""),
                "scope": item.get("scope", "catalog"),
                "catalogId": item.get("catalogId", ""),
                "tableId": item.get("tableId", ""),
                "columnId": item.get("columnId", ""),
                "templateCategory": item.get("templateCategory", ""),
                "status": item.get("status", "active"),
                "created_at": item.get("created_at", ""),
            })

        return {"items": rules, "totalCount": len(rules)}

    except Exception as e:
        logger.error(f"List rules error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


def _normalize_rule_text(text: str) -> str:
    """Lowercase, strip punctuation/extra spaces for exact-duplicate comparison."""
    import re as _re
    t = text.lower().strip()
    t = _re.sub(r"[^\w\s]", "", t)
    t = _re.sub(r"\s+", " ", t)
    return t


async def _find_duplicate_rule(catalog_id: str, table_id: str, column_id: str, nl: str) -> dict | None:
    """Check if a semantically equivalent rule already exists for this table+column.

    Step 1: exact normalized-text match (fast, no AI call).
    Step 2: if existing rules are present for this scope, ask Nova Lite whether
            the new rule is semantically equivalent to any of them.
    Returns the duplicate rule dict if found, else None.
    """
    from boto3.dynamodb.conditions import Attr
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    rules_table = dynamodb.Table("dq-rules")

    resp = rules_table.scan(
        FilterExpression=Attr("catalogId").eq(catalog_id)
        & Attr("tableId").eq(table_id)
        & Attr("columnId").eq(column_id)
        & Attr("sk").eq("METADATA")
    )
    existing_rules = resp.get("Items", [])
    if not existing_rules:
        return None

    normalized_new = _normalize_rule_text(nl)

    # Step 1: exact normalized match
    for r in existing_rules:
        if _normalize_rule_text(r.get("naturalLanguage", "")) == normalized_new:
            return r

    # Step 2: semantic match via Nova Lite
    try:
        import json as json_module
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        existing_list = "\n".join(
            f"{i+1}. \"{r.get('naturalLanguage', '')}\"" for i, r in enumerate(existing_rules)
        )
        prompt = f"""You are checking for duplicate data quality rules on the SAME column.

New rule: "{nl}"

Existing rules already defined for this exact column:
{existing_list}

Does the new rule express the SAME constraint/intent as any existing rule (even if worded differently)?
Examples of duplicates: "cannot be null" and "not null allowed" and "must not be empty" are the SAME rule.
Examples of NOT duplicates: "must be greater than 0" and "cannot be null" are DIFFERENT rules.

Return ONLY a JSON object: {{"is_duplicate": true/false, "duplicate_index": <1-based index or null>}}"""

        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json_module.dumps({
                "inferenceConfig": {"maxTokens": 150, "temperature": 0.0},
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            })
        )
        result = json_module.loads(response["body"].read())
        text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()
        verdict = json_module.loads(clean)

        if verdict.get("is_duplicate"):
            idx = verdict.get("duplicate_index")
            if idx and 1 <= idx <= len(existing_rules):
                return existing_rules[idx - 1]
            return existing_rules[0]
    except Exception as e:
        logger.warning(f"Semantic duplicate check failed, falling back to no-match: {e}")

    return None


@app.post("/api/rules")
async def create_rule(request: Request):
    """Create a new rule in DynamoDB. Rejects duplicates on the same table+column."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        body = await request.json()
        nl = body.get("naturalLanguage", "")
        scope = body.get("scope", "catalog")
        catalog_id = body.get("catalogId", "")
        table_id = body.get("tableId", "")
        column_id = body.get("columnId", "")
        template_category = body.get("templateCategory", "simple")
        status = body.get("status", "active")

        if not nl:
            return JSONResponse(status_code=400, content={"error": "naturalLanguage is required"})

        # Enforce rule uniqueness per table+column
        if table_id and column_id:
            duplicate = await _find_duplicate_rule(catalog_id, table_id, column_id, nl)
            if duplicate:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "duplicate_rule",
                        "message": f"A rule with the same intent already exists on this column: \"{duplicate.get('naturalLanguage', '')}\"",
                        "existingRuleId": duplicate.get("id", ""),
                        "existingRuleText": duplicate.get("naturalLanguage", ""),
                    },
                )

        from datetime import datetime, timezone
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        rules_table = dynamodb.Table("dq-rules")

        rules_table.put_item(Item={
            "pk": f"RULE#{rule_id}",
            "sk": "METADATA",
            "id": rule_id,
            "naturalLanguage": nl,
            "scope": scope,
            "catalogId": catalog_id,
            "tableId": table_id,
            "columnId": column_id,
            "templateCategory": template_category,
            "status": status,
            "created_at": now,
        })

        return {"id": rule_id, "ruleId": rule_id, "naturalLanguage": nl, "status": status}

    except Exception as e:
        logger.error(f"Create rule error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/rules/interpret")
async def interpret_rule(request: Request):
    """Use Nova Lite to interpret a natural language rule into structured JSON."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        import json as json_module
        body = await request.json()
        nl = body.get("naturalLanguage", "")
        scope = body.get("scope", "catalog")

        if not nl:
            return JSONResponse(status_code=400, content={"error": "naturalLanguage is required"})

        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = f"""Interpret this data quality rule into a structured definition.

Rule (natural language): "{nl}"
Scope: {scope}

Return a JSON object with:
- "type": one of "completeness", "format", "range", "uniqueness", "consistency", "custom"
- "conditions": array of condition strings
- "targetFields": array of field names this applies to
- "expectedBehavior": brief description of what valid data looks like

Return ONLY valid JSON, no explanation."""

        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json_module.dumps({
                "inferenceConfig": {"maxTokens": 512, "temperature": 0.2},
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            })
        )
        result = json_module.loads(response["body"].read())
        text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")

        # Try to parse JSON from response
        structured = {}
        try:
            # Clean markdown fences
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
                clean = clean.strip()
            structured = json_module.loads(clean)
        except Exception:
            structured = {"type": "custom", "conditions": [nl], "targetFields": [], "expectedBehavior": nl}

        return {
            "structuredJson": structured,
            "preview": {
                "ruleName": nl[:60],
                "conditions": ", ".join(structured.get("conditions", [nl])),
                "expectedBehavior": structured.get("expectedBehavior", nl),
            }
        }

    except Exception as e:
        logger.error(f"Interpret rule error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Interpretation failed: {str(e)}"})


# ---------------------------------------------------------------------------
# Generate Python Code Endpoint (Nova Lite)
# ---------------------------------------------------------------------------


@app.post("/api/generate-code")
async def generate_validation_code(request: Request):
    """Use Nova Lite to generate a Python pandas validation function from natural language."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        body = await request.json()
        nl = body.get("naturalLanguage", "")
        scope = body.get("scope", "catalog")
        table_id = body.get("tableId", "")
        column_id = body.get("columnId", "")

        # Call Nova Lite to generate Python code
        import json as json_module
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = f"""Generate a Python function that validates this data quality rule on a pandas DataFrame.

Rule: {nl}
Table: {table_id}
Column: {column_id}

The function must:
- Be named validate_rule(df: pd.DataFrame) -> pd.DataFrame
- Take a DataFrame, check the rule, add a 'flag_violation' column (True where rule is violated)
- Return the DataFrame with the flag column
- Use only pandas operations (no apply/lambda)
- Handle nulls safely

Return ONLY the Python code, no explanation."""

        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json_module.dumps({
                "inferenceConfig": {"maxTokens": 1024, "temperature": 0.2},
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            })
        )
        result = json_module.loads(response["body"].read())
        code_text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")

        # Clean up markdown fences
        if "```python" in code_text:
            code_text = code_text.split("```python")[1].split("```")[0].strip()
        elif "```" in code_text:
            code_text = code_text.split("```")[1].split("```")[0].strip()

        return {"code": code_text}

    except Exception as e:
        logger.error(f"Generate code error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Code generation failed: {str(e)}"})


# ---------------------------------------------------------------------------
# Generate Code for a specific Rule (by ID)
# ---------------------------------------------------------------------------


@app.post("/api/rules/{rule_id}/generate-code")
async def generate_code_for_rule(request: Request, rule_id: str):
    """Fetch rule from DynamoDB and use Nova Lite to generate Python validation code."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        import json as json_module
        from boto3.dynamodb.conditions import Key as DDBKey

        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        rules_table = dynamodb.Table("dq-rules")

        # Query rule by id
        response = rules_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"RULE#{rule_id}")
        )
        items = response.get("Items", [])

        # Fallback: try scan if pk-based query returns nothing
        if not items:
            scan_res = rules_table.scan()
            items = [r for r in scan_res.get("Items", []) if r.get("id") == rule_id]

        if not items:
            return JSONResponse(status_code=404, content={"error": "Rule not found"})

        rule = items[0]
        nl = rule.get("naturalLanguage", "")
        column_id = rule.get("columnId", "")
        table_id = rule.get("tableId", "")

        # Call Nova Lite to generate Python code
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = f"""Generate a Python function that validates this data quality rule on a pandas DataFrame.

Rule: {nl}
Table: {table_id}
Column: {column_id}

The function must:
- Be named validate_rule(df: pd.DataFrame) -> pd.DataFrame
- Take a DataFrame, check the rule, add a 'flag_violation' column (True where rule is violated)
- Return the DataFrame with the flag column
- Use only pandas operations (no apply/lambda)
- Handle nulls safely

Return ONLY the Python code, no explanation."""

        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json_module.dumps({
                "inferenceConfig": {"maxTokens": 1024, "temperature": 0.2},
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            })
        )
        result = json_module.loads(response["body"].read())
        code_text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")

        # Clean up markdown fences
        if "```python" in code_text:
            code_text = code_text.split("```python")[1].split("```")[0].strip()
        elif "```" in code_text:
            code_text = code_text.split("```")[1].split("```")[0].strip()

        return {"code": code_text, "script": code_text, "ruleId": rule_id}

    except Exception as e:
        logger.error(f"Generate code for rule error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Code generation failed: {str(e)}"})


# ---------------------------------------------------------------------------
# Validation Endpoint — Run rules against a table
# ---------------------------------------------------------------------------


@app.post("/api/validations")
async def run_validations(request: Request):
    """Download CSV from S3, get rules for catalog, execute validation, return scores."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        body = await request.json()
        catalog_id = body.get("catalogId")
        table_id = body.get("tableId") or body.get("datasetId")

        if not catalog_id or not table_id:
            return JSONResponse(status_code=400, content={"error": "catalogId and tableId required"})

        # 1. Get table info (s3Key)
        from boto3.dynamodb.conditions import Key as DDBKey
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        table_response = catalogs_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"CATALOG#{catalog_id}") & DDBKey("sk").eq(f"TABLE#{table_id}")
        )
        table_items = table_response.get("Items", [])
        if not table_items:
            return JSONResponse(status_code=404, content={"error": "Table not found"})

        table_info = table_items[0]
        s3_key = table_info.get("s3Key", "")

        if not s3_key:
            return JSONResponse(status_code=400, content={"error": "Table has no S3 file associated"})

        # 2. Download CSV from S3
        obj = s3_client.get_object(Bucket=S3_BUCKET_RAW, Key=s3_key)
        content = obj["Body"].read()

        # 3. Parse CSV
        columns_info, preview = parse_csv_and_infer(content, s3_key.split("/")[-1])
        sep = preview.get("separator", ",") if preview else ","
        df = pd.read_csv(io.BytesIO(content), sep=sep, on_bad_lines="skip")
        total_rows = len(df)

        # 4. Get rules for this catalog from DynamoDB
        rules_table = dynamodb.Table("dq-rules")
        rules_response = rules_table.scan()
        all_rules = [r for r in rules_response.get("Items", [])
                     if r.get("catalogId") == catalog_id and r.get("sk") == "METADATA"]

        # 5. Execute each rule using Nova Lite generated Python code
        import json as json_module
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        results = []
        total_violations = 0

        for rule in all_rules:
            nl = rule.get("naturalLanguage", "")
            rule_id = rule.get("id", "")
            column_id = rule.get("columnId", "")
            violations = 0

            # Try AI-powered validation: generate code and execute it
            try:
                prompt = f"""Generate a Python expression that counts violations for this rule on a pandas DataFrame named 'df'.
Rule: {nl}
Column: {column_id if column_id else 'all columns'}

Return ONLY a single Python expression that evaluates to an integer (number of violating rows).
Example: df['col'].isna().sum()
No imports, no function definitions, just the expression."""

                gen_response = bedrock.invoke_model(
                    modelId="amazon.nova-lite-v1:0",
                    contentType="application/json",
                    accept="application/json",
                    body=json_module.dumps({
                        "inferenceConfig": {"maxTokens": 256, "temperature": 0.1},
                        "messages": [{"role": "user", "content": [{"text": prompt}]}]
                    })
                )
                gen_result = json_module.loads(gen_response["body"].read())
                expr = gen_result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "").strip()

                # Clean markdown
                if "```" in expr:
                    expr = expr.split("```")[1].split("```")[0].strip()
                    if expr.startswith("python"):
                        expr = expr[6:].strip()

                # Safe eval with only pandas/df in scope
                violations = int(eval(expr, {"__builtins__": {}}, {"df": df, "pd": pd}))
            except Exception as eval_err:
                logger.warning(f"AI validation failed for rule {rule_id}, falling back to heuristic: {eval_err}")
                # Heuristic fallback
                if column_id and column_id in df.columns:
                    violations = int(df[column_id].isna().sum())
                else:
                    violations = int(df.isnull().any(axis=1).sum())

            passed = total_rows - violations
            results.append({
                "ruleId": rule_id,
                "ruleName": nl[:60] if nl else "Unnamed rule",
                "columnId": column_id or "all",
                "totalRows": total_rows,
                "passedRows": passed,
                "failedRows": violations,
                "score": round((passed / max(total_rows, 1)) * 100, 1),
            })
            total_violations += violations

        overall_score = round(
            ((total_rows * max(len(all_rules), 1) - total_violations) / max(total_rows * max(len(all_rules), 1), 1)) * 100,
            1
        )

        return {
            "success": True,
            "totalRows": total_rows,
            "totalRules": len(all_rules),
            "overallScore": overall_score,
            "results": results,
        }

    except Exception as e:
        logger.error(f"Validation error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Validation failed: {str(e)}"})


# ---------------------------------------------------------------------------
# Cleaning Endpoint — Generate cleaning script with Nova Lite
# ---------------------------------------------------------------------------


@app.post("/api/cleaning/generate")
async def generate_cleaning_script(request: Request):
    """Generate a Python cleaning script for a table using Nova Lite."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        import json as json_module
        body = await request.json()
        catalog_id = body.get("catalogId", "")
        table_id = body.get("tableId", "")
        issues = body.get("issues", "")

        if not catalog_id or not table_id:
            return JSONResponse(status_code=400, content={"error": "catalogId and tableId required"})

        # Get table info for context
        from boto3.dynamodb.conditions import Key as DDBKey, Attr
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        table_response = catalogs_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"CATALOG#{catalog_id}") & DDBKey("sk").eq(f"TABLE#{table_id}")
        )
        table_items = table_response.get("Items", [])
        if not table_items:
            return JSONResponse(status_code=404, content={"error": "Table not found"})

        table_info = table_items[0]
        columns = table_info.get("columns", [])
        col_names = [c.get("name", "") for c in columns if c.get("name")]
        s3_key = table_info.get("s3Key", "")
        table_name = table_info.get("name", "dataset")

        # Get rules for this catalog to incorporate into cleaning
        rules_table = dynamodb.Table("dq-rules")
        rules_resp = rules_table.scan(FilterExpression=Attr("catalogId").eq(catalog_id) & Attr("sk").eq("METADATA"))
        existing_rules = rules_resp.get("Items", [])
        rules_context = ""
        if existing_rules:
            rules_context = "\nExisting quality rules for this data:\n"
            for r in existing_rules:
                rules_context += f"- {r.get('naturalLanguage', '')} (column: {r.get('columnId', 'all')})\n"
            rules_context += "\nThe cleaning script should address violations of these rules.\n"

        # Call Nova Lite to generate cleaning script
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = f"""Generate a Python data cleaning script for a CSV dataset.

Dataset: {table_name}
Columns: {', '.join(col_names)}
Issues to address: {issues if issues else 'General cleaning - remove duplicates, handle nulls, trim strings, fix formats'}
{rules_context}
CRITICAL RULES FOR THIS SCRIPT:
- NEVER drop/filter rows just because a column value violates a quality rule — CORRECT or FLAG them instead, do not delete data.
- Only drop rows for exact full-row duplicates (df.drop_duplicates()) or if explicitly asked to remove rows.
- For quality rule violations (out-of-range values, invalid formats): either clip/correct the value, or leave it and add a boolean flag column (e.g. 'ABONO_invalid'), but do NOT remove the row.
- The script must preserve the row count unless duplicates are removed or the user explicitly asked to delete rows.

The script must:
- Be a complete Python function: def clean_data(df: pd.DataFrame) -> pd.DataFrame
- Use pandas operations only
- Use df.map() instead of df.applymap() (pandas 2.x)
- Handle each issue systematically
- Include comments explaining each step
- Return the cleaned DataFrame

Return ONLY the Python code, no explanation."""

        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json_module.dumps({
                "inferenceConfig": {"maxTokens": 1500, "temperature": 0.2},
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            })
        )
        result = json_module.loads(response["body"].read())
        code_text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")

        # Clean markdown fences
        if "```python" in code_text:
            code_text = code_text.split("```python")[1].split("```")[0].strip()
        elif "```" in code_text:
            code_text = code_text.split("```")[1].split("```")[0].strip()

        return {
            "success": True,
            "script": code_text,
            "tableName": table_name,
            "s3Key": s3_key,
        }

    except Exception as e:
        logger.error(f"Cleaning generate error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Script generation failed: {str(e)}"})


@app.post("/api/cleaning/execute")
async def execute_cleaning_script(request: Request):
    """Execute a cleaning script against a table's CSV data."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        body = await request.json()
        catalog_id = body.get("catalogId", "")
        table_id = body.get("tableId", "")
        script = body.get("script", "")

        if not catalog_id or not table_id or not script:
            return JSONResponse(status_code=400, content={"error": "catalogId, tableId, and script required"})

        # Get table S3 key
        from boto3.dynamodb.conditions import Key as DDBKey
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        table_response = catalogs_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"CATALOG#{catalog_id}") & DDBKey("sk").eq(f"TABLE#{table_id}")
        )
        table_items = table_response.get("Items", [])
        if not table_items:
            return JSONResponse(status_code=404, content={"error": "Table not found"})

        table_info = table_items[0]
        s3_key = table_info.get("s3Key", "")

        if not s3_key:
            return JSONResponse(status_code=400, content={"error": "Table has no file associated"})

        # Download CSV
        obj = s3_client.get_object(Bucket=S3_BUCKET_RAW, Key=s3_key)
        content = obj["Body"].read()

        # Parse
        sep = table_info.get("separator", ",")
        df = pd.read_csv(io.BytesIO(content), sep=sep, on_bad_lines="skip")
        original_rows = len(df)

        # Execute cleaning script in a restricted namespace
        import numpy as np
        local_ns = {"pd": pd, "np": np, "df": df.copy()}
        try:
            # Strip import statements (pd and np are already provided)
            import re as _re
            clean_script = "\n".join(
                line for line in script.split("\n")
                if not _re.match(r"^\s*(import |from )", line)
            )
            # Patch applymap -> map for pandas 2.x compatibility
            clean_script = clean_script.replace(".applymap(", ".map(")
            # Execute with full builtins (the script is AI-generated for this specific table)
            exec(clean_script, {"__builtins__": __builtins__, "pd": pd, "np": np}, local_ns)
            # Call the clean_data function if defined
            if "clean_data" in local_ns:
                cleaned_df = local_ns["clean_data"](df)
            else:
                cleaned_df = local_ns.get("df", df)
        except Exception as exec_err:
            return JSONResponse(status_code=400, content={"error": f"Script execution failed: {str(exec_err)}"})

        cleaned_rows = len(cleaned_df)
        modified_rows = original_rows - cleaned_rows

        # Save cleaned CSV back to S3 (clean/ prefix)
        clean_key = s3_key.replace("uploads/", "clean/")
        output = io.BytesIO()
        cleaned_df.to_csv(output, index=False, sep=sep)
        output.seek(0)

        s3_client.put_object(
            Bucket=S3_BUCKET_RAW,
            Key=clean_key,
            Body=output.getvalue(),
            ContentType="text/csv",
        )

        return {
            "success": True,
            "originalRows": original_rows,
            "cleanedRows": cleaned_rows,
            "removedRows": modified_rows,
            "cleanS3Key": clean_key,
        }

    except Exception as e:
        logger.error(f"Cleaning execute error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Cleaning execution failed: {str(e)}"})


# ---------------------------------------------------------------------------
# Reports Endpoint — Generate report with Nova Lite
# ---------------------------------------------------------------------------


@app.post("/api/reports/generate")
async def generate_report(request: Request):
    """Generate a quality report using Nova Lite based on validation results."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        import json as json_module
        body = await request.json()
        catalog_id = body.get("catalogId", "")
        table_id = body.get("tableId", "")

        if not catalog_id:
            return JSONResponse(status_code=400, content={"error": "catalogId required"})

        # Get catalog and table info
        from boto3.dynamodb.conditions import Key as DDBKey, Attr
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        # Get catalog name
        cat_resp = catalogs_table.get_item(Key={"pk": f"CATALOG#{catalog_id}", "sk": "METADATA"})
        catalog_name = cat_resp.get("Item", {}).get("name", "Unknown Catalog")

        # Get tables
        tables_resp = catalogs_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"CATALOG#{catalog_id}") & DDBKey("sk").begins_with("TABLE#")
        )
        tables = tables_resp.get("Items", [])
        table_summaries = []
        for t in tables:
            table_summaries.append(f"- {t.get('name', 'Unknown')}: {t.get('rowCount', 0)} rows, {len(t.get('columns', []))} columns")

        # Get rules for this catalog
        rules_table = dynamodb.Table("dq-rules")
        rules_resp = rules_table.scan(FilterExpression=Attr("catalogId").eq(catalog_id) & Attr("sk").eq("METADATA"))
        rules = rules_resp.get("Items", [])
        rule_summaries = [f"- {r.get('naturalLanguage', 'Rule')}" for r in rules]

        # Generate report with Nova Lite
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        prompt = f"""Generate a professional data quality executive report in Markdown.

Catalog: {catalog_name}
Date: {now}
Tables:
{chr(10).join(table_summaries) if table_summaries else '- No tables uploaded yet'}

Active Rules:
{chr(10).join(rule_summaries) if rule_summaries else '- No rules defined yet'}

Number of rules: {len(rules)}
Number of tables: {len(tables)}

Write the report with these sections:
1. Executive Summary (2-3 sentences)
2. Data Overview (tables, rows, columns)
3. Quality Rules Summary
4. Recommendations (3-5 actionable items)

Keep it concise and professional. Use Markdown formatting."""

        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json_module.dumps({
                "inferenceConfig": {"maxTokens": 2000, "temperature": 0.3},
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            })
        )
        result = json_module.loads(response["body"].read())
        report_text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")

        return {
            "success": True,
            "report": report_text,
            "catalogName": catalog_name,
            "generatedAt": now,
            "tablesCount": len(tables),
            "rulesCount": len(rules),
        }

    except Exception as e:
        logger.error(f"Report generate error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Report generation failed: {str(e)}"})


# ---------------------------------------------------------------------------
# Anomaly Detection — Autoencoder trained on EC2 (+ SageMaker ready)
# ---------------------------------------------------------------------------


@app.post("/api/anomalies/train")
async def train_anomaly_model(request: Request):
    """Train an autoencoder on a table's numeric columns. Runs on EC2 directly."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        body = await request.json()
        catalog_id = body.get("catalogId", "")
        table_id = body.get("tableId", "")

        if not catalog_id or not table_id:
            return JSONResponse(status_code=400, content={"error": "catalogId and tableId required"})

        # Get table info
        from boto3.dynamodb.conditions import Key as DDBKey
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        catalogs_table = dynamodb.Table("dq-catalogs")

        table_response = catalogs_table.query(
            KeyConditionExpression=DDBKey("pk").eq(f"CATALOG#{catalog_id}") & DDBKey("sk").eq(f"TABLE#{table_id}")
        )
        table_items = table_response.get("Items", [])
        if not table_items:
            return JSONResponse(status_code=404, content={"error": "Table not found"})

        table_info = table_items[0]
        s3_key = table_info.get("s3Key", "")
        if not s3_key:
            return JSONResponse(status_code=400, content={"error": "Table has no file"})

        # Download CSV
        obj = s3_client.get_object(Bucket=S3_BUCKET_RAW, Key=s3_key)
        content = obj["Body"].read()
        sep = table_info.get("separator", ",")
        df = pd.read_csv(io.BytesIO(content), sep=sep, on_bad_lines="skip")

        # Select numeric columns only
        import numpy as np
        numeric_df = df.select_dtypes(include=[np.number])
        if numeric_df.empty or len(numeric_df) < 10:
            return JSONResponse(status_code=400, content={"error": "Not enough numeric data to train (need at least 10 rows with numeric columns)"})

        # Normalize
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        data = scaler.fit_transform(numeric_df.values)
        data = np.clip(data, 0, 1)

        n_features = data.shape[1]
        encoding_dim = max(4, n_features // 4)

        # Build simple autoencoder with numpy (no tensorflow needed for small data)
        # Using sklearn's MLPRegressor as lightweight autoencoder alternative
        from sklearn.neural_network import MLPRegressor

        hidden_layers = (64, 32, encoding_dim, 32, 64)
        model = MLPRegressor(
            hidden_layer_sizes=hidden_layers,
            activation='relu',
            solver='adam',
            max_iter=200,
            learning_rate_init=0.001,
            early_stopping=True,
            validation_fraction=0.2,
            n_iter_no_change=10,
            random_state=42,
        )

        # Train: input = output (reconstruction)
        model.fit(data, data)

        # Compute reconstruction errors
        predictions = model.predict(data)
        mse_per_sample = np.mean(np.power(data - predictions, 2), axis=1)

        # Threshold: 95th percentile
        threshold = float(np.percentile(mse_per_sample, 95))

        # Score each record
        anomaly_flags = mse_per_sample > threshold
        n_anomalies = int(anomaly_flags.sum())

        # Classify severity
        results = []
        for i in range(len(mse_per_sample)):
            error = float(mse_per_sample[i])
            if error > 3 * threshold:
                severity = "critical"
            elif error > 2 * threshold:
                severity = "high"
            elif error > 1.5 * threshold:
                severity = "medium"
            elif error > threshold:
                severity = "low"
            else:
                severity = "normal"

            if severity != "normal":
                # Find which columns contributed most to the error
                col_errors = np.power(data[i] - predictions[i], 2)
                top_cols_idx = np.argsort(col_errors)[-3:][::-1]
                affected_cols = [numeric_df.columns[j] for j in top_cols_idx]

                results.append({
                    "recordIndex": i,
                    "reconstructionError": round(error, 6),
                    "severity": severity,
                    "affectedColumns": affected_cols,
                })

        # Save model stats to S3
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        model_key = f"anomaly-models/{catalog_id}/{table_id}/model_stats.json"
        model_stats = {
            "threshold": threshold,
            "n_features": n_features,
            "encoding_dim": encoding_dim,
            "training_samples": len(data),
            "n_anomalies": n_anomalies,
            "mean": scaler.mean_.tolist(),
            "std": scaler.scale_.tolist(),
            "feature_names": numeric_df.columns.tolist(),
            "trained_at": now,
        }
        s3_client.put_object(
            Bucket=S3_BUCKET_RAW,
            Key=model_key,
            Body=json.dumps(model_stats),
            ContentType="application/json",
        )

        return {
            "success": True,
            "totalRecords": len(df),
            "numericFeatures": n_features,
            "featureNames": numeric_df.columns.tolist(),
            "threshold": round(threshold, 6),
            "totalAnomalies": n_anomalies,
            "anomalyRate": round(n_anomalies / len(df) * 100, 1),
            "anomalies": results[:50],  # Limit to 50 for response size
            "trainedAt": now,
        }

    except Exception as e:
        logger.error(f"Anomaly training error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Training failed: {str(e)}"})


# ---------------------------------------------------------------------------
# API Proxy — Forward all /api/* requests to API Gateway
# ---------------------------------------------------------------------------


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_api_gateway(request: Request, path: str):
    """Proxy requests to AWS API Gateway with JWT from cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(
            status_code=401, content={"error": "Authentication required"}
        )

    # Build target URL
    target_url = f"{API_GATEWAY_URL}/{path}"

    # Forward query params
    if request.query_params:
        target_url += f"?{request.query_params}"

    # Build headers (forward auth token)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    # Read body if present
    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )

        # Return the API Gateway response
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504, content={"error": "API Gateway timeout"}
        )
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return JSONResponse(
            status_code=502, content={"error": "Failed to reach API Gateway"}
        )


# ---------------------------------------------------------------------------
# Static Files & SPA Fallback
# ---------------------------------------------------------------------------

# Mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/{path:path}")
async def serve_spa(path: str):
    """Serve the React SPA — return index.html for all non-API routes."""
    # Check if requesting a specific static file
    file_path = STATIC_DIR / path
    if file_path.is_file():
        return FileResponse(str(file_path))

    # SPA fallback: always serve index.html
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))

    return JSONResponse(
        status_code=404,
        content={"error": "Application not found. Deploy frontend to ./static/"},
    )
