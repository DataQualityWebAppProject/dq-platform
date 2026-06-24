"""DqLambdaStack - Lambda functions for ALL backend services.

Deploys all Lambda functions with the correct packaging structure so that
handler imports (services.shared.*, services.governance.handlers.*,
services.rules.handlers.*, services.validation.handlers.*,
services.anomalies.handlers.*, services.cleaning.handlers.*,
services.reporting.handlers.*) resolve correctly at runtime.

Lambda functions:
  Governance Service:
  - dq-catalog-crud
  - dq-table-crud
  - dq-field-crud
  - dq-upload-handler
  - dq-audit-handler
  - dq-template-crud

  Rules Service:
  - dq-rules-crud
  - dq-rule-interpreter
  - dq-conflict-detector
  - dq-code-generator

  Validation Service:
  - dq-validation-orchestrator
  - dq-validation-results
  - dq-validation-metrics

  Anomaly Service:
  - dq-anomaly-training
  - dq-anomaly-scoring
  - dq-anomaly-export
  - dq-anomaly-status

  Cleaning Service:
  - dq-cleaning-orchestrator
  - dq-cleaning-status

  Reporting Service:
  - dq-report-generator
  - dq-reports-crud
  - dq-notifications

All functions use DqLambdaExecutionRole (imported from SSM).
"""

from pathlib import Path

from aws_cdk import (
    Duration,
    Stack,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_ssm as ssm,
)
from constructs import Construct


class DqLambdaStack(Stack):
    """Lambda functions for all backend services. Python 3.11 runtime."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Import the Lambda execution role from SSM
        lambda_role_arn = ssm.StringParameter.value_for_string_parameter(
            self, "/dq-platform/iam-lambda-role-arn"
        )
        lambda_role = iam.Role.from_role_arn(
            self, "ImportedLambdaRole", role_arn=lambda_role_arn
        )

        # Workspace root (parent of infra/)
        workspace_root = str(Path(__file__).resolve().parent.parent.parent)

        # Common environment variables for all Lambda functions
        common_env = {
            "CATALOG_TABLE_NAME": "dq-catalogs",
            "TEMPLATES_TABLE_NAME": "dq-templates",
            "AUDIT_TABLE_NAME": "dq-audit-trail",
            "S3_RAW_BUCKET": "dq-raw-108782054634",
            "COGNITO_USER_POOL_ID": "us-east-1_8KvqRmGSN",
            "COGNITO_CLIENT_ID": "4q5odh7hskaevkpphb4p8jgl3j",
            "AWS_REGION_NAME": "us-east-1",
            # Rules service tables
            "RULES_TABLE_NAME": "dq-rules",
            "CONFLICTS_TABLE_NAME": "dq-rule-conflicts",
            # Validation service tables
            "VALIDATION_RUNS_TABLE_NAME": "dq-validation-runs",
            "VALIDATION_RESULTS_TABLE_NAME": "dq-validation-results",
            # Anomaly service tables
            "ANOMALY_TRAINING_TABLE_NAME": "dq-anomaly-training",
            "ANOMALY_MODELS_TABLE_NAME": "dq-anomaly-models",
            "ANOMALY_SCORES_TABLE_NAME": "dq-anomaly-scores",
            # Cleaning service tables
            "CLEANING_JOBS_TABLE_NAME": "dq-cleaning-jobs",
            # Reporting service tables
            "REPORTS_TABLE_NAME": "dq-reports",
            "NOTIFICATIONS_TABLE_NAME": "dq-notifications",
            "NOTIFICATION_RECIPIENTS_TABLE_NAME": "dq-notification-recipients",
            # S3 buckets
            "SCRIPTS_BUCKET": "dq-scripts-108782054634",
            "EXPORTS_BUCKET": "dq-exports-108782054634",
            "CLEAN_BUCKET": "dq-clean-108782054634",
            "BACKUPS_BUCKET": "dq-backups-108782054634",
            "REPORTS_BUCKET": "dq-reports-108782054634",
            "MLFLOW_BUCKET": "dq-mlflow-108782054634",
            # Glue job names
            "GLUE_VALIDATION_JOB_NAME": "dq-validation-job",
            "GLUE_CLEANING_JOB_NAME": "dq-cleaning-job",
        }

        # Asset code: bundle the workspace root with exclusions
        # This keeps services/ (with shared/ and governance/) accessible
        # so handler imports like `from services.shared.auth import ...` work.
        code_asset = _lambda.Code.from_asset(
            path=workspace_root,
            exclude=[
                "infra",
                "dq-platform-infra",
                "frontend",
                ".git",
                ".kiro",
                ".venv",
                "node_modules",
                "*.pyc",
                "__pycache__",
                "cdk.out",
                ".pytest_cache",
                "*.egg-info",
            ],
        )

        # --- Lambda Function Definitions ---

        # dq-catalog-crud
        self.catalog_fn = _lambda.Function(
            self,
            "DqCatalogCrud",
            function_name="dq-catalog-crud",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.governance.handlers.catalog.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-table-crud
        self.table_fn = _lambda.Function(
            self,
            "DqTableCrud",
            function_name="dq-table-crud",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.governance.handlers.tables.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-field-crud
        self.field_fn = _lambda.Function(
            self,
            "DqFieldCrud",
            function_name="dq-field-crud",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.governance.handlers.fields.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-upload-handler
        self.upload_fn = _lambda.Function(
            self,
            "DqUploadHandler",
            function_name="dq-upload-handler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.governance.handlers.upload.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-audit-handler
        self.audit_fn = _lambda.Function(
            self,
            "DqAuditHandler",
            function_name="dq-audit-handler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.governance.handlers.audit.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-template-crud
        self.template_fn = _lambda.Function(
            self,
            "DqTemplateCrud",
            function_name="dq-template-crud",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.governance.handlers.templates.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # ===== Rules Service =====

        # dq-rules-crud
        self.rules_fn = _lambda.Function(
            self,
            "DqRulesCrud",
            function_name="dq-rules-crud",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.rules.handlers.rules.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-rule-interpreter
        self.rule_interpreter_fn = _lambda.Function(
            self,
            "DqRuleInterpreter",
            function_name="dq-rule-interpreter",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.rules.handlers.interpreter.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-conflict-detector
        self.conflict_detector_fn = _lambda.Function(
            self,
            "DqConflictDetector",
            function_name="dq-conflict-detector",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.rules.handlers.conflicts.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-code-generator
        self.code_generator_fn = _lambda.Function(
            self,
            "DqCodeGenerator",
            function_name="dq-code-generator",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.rules.handlers.codegen.handler",
            code=code_asset,
            timeout=Duration.seconds(120),
            memory_size=1024,
            role=lambda_role,
            environment=common_env,
        )

        # ===== Validation Service =====

        # dq-validation-orchestrator
        self.validation_orchestrator_fn = _lambda.Function(
            self,
            "DqValidationOrchestrator",
            function_name="dq-validation-orchestrator",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.validation.handlers.orchestrator.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-validation-results
        self.validation_results_fn = _lambda.Function(
            self,
            "DqValidationResults",
            function_name="dq-validation-results",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.validation.handlers.results.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-validation-metrics
        self.validation_metrics_fn = _lambda.Function(
            self,
            "DqValidationMetrics",
            function_name="dq-validation-metrics",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.validation.handlers.metrics.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # ===== Anomaly Service =====

        # dq-anomaly-training
        self.anomaly_training_fn = _lambda.Function(
            self,
            "DqAnomalyTraining",
            function_name="dq-anomaly-training",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.anomalies.handlers.training.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-anomaly-scoring
        self.anomaly_scoring_fn = _lambda.Function(
            self,
            "DqAnomalyScoring",
            function_name="dq-anomaly-scoring",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.anomalies.handlers.scoring.handler",
            code=code_asset,
            timeout=Duration.seconds(300),
            memory_size=1024,
            role=lambda_role,
            environment=common_env,
        )

        # dq-anomaly-export
        self.anomaly_export_fn = _lambda.Function(
            self,
            "DqAnomalyExport",
            function_name="dq-anomaly-export",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.anomalies.handlers.export.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-anomaly-status
        self.anomaly_status_fn = _lambda.Function(
            self,
            "DqAnomalyStatus",
            function_name="dq-anomaly-status",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.anomalies.handlers.status.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # ===== Cleaning Service =====

        # dq-cleaning-orchestrator
        self.cleaning_orchestrator_fn = _lambda.Function(
            self,
            "DqCleaningOrchestrator",
            function_name="dq-cleaning-orchestrator",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.cleaning.handlers.orchestrator.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-cleaning-status
        self.cleaning_status_fn = _lambda.Function(
            self,
            "DqCleaningStatus",
            function_name="dq-cleaning-status",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.cleaning.handlers.status.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # ===== Reporting Service =====

        # dq-report-generator
        self.report_generator_fn = _lambda.Function(
            self,
            "DqReportGenerator",
            function_name="dq-report-generator",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.reporting.handlers.generator.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # dq-reports-crud
        self.reports_crud_fn = _lambda.Function(
            self,
            "DqReportsCrud",
            function_name="dq-reports-crud",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.reporting.handlers.reports.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )

        # dq-notifications
        self.notifications_fn = _lambda.Function(
            self,
            "DqNotifications",
            function_name="dq-notifications",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="services.reporting.handlers.notifications.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
            environment=common_env,
        )
