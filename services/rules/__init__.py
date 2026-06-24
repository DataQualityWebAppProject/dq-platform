"""Rules Engine Service for the Data Quality Platform.

Provides:
- Rule CRUD operations (create, read, update, delete) across scope levels
- Natural language interpretation via Bedrock Claude 3 Haiku
- AI code generation pipeline (SageMaker → Bedrock Haiku → Bedrock Sonnet)
- Conflict detection and resolution between hierarchy levels

DynamoDB Tables:
- dq-rules: Rule storage with scope metadata
- dq-rule-conflicts: Conflict detection and resolution records

S3 Bucket: dq-scripts-108782054634 (generated validation scripts)

Requirements: 5, 6, 7, 8, 9
"""
