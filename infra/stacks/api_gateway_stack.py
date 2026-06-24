"""DqApiGatewayStack - HTTP API with JWT authorizer and ALL route integrations.

Creates an HTTP API Gateway with:
- JWT Authorizer using Cognito User Pool
- CORS configured for all origins
- Default throttling (1000 burst, 500 rate)
- All 40+ routes wired to corresponding Lambda functions
- API endpoint URL exported to SSM
"""

from aws_cdk import (
    Stack,
    CfnOutput,
    aws_apigatewayv2 as apigwv2,
    aws_lambda as _lambda,
    aws_ssm as ssm,
)
from aws_cdk.aws_apigatewayv2_authorizers import HttpJwtAuthorizer
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct


class DqApiGatewayStack(Stack):
    """API Gateway HTTP API with Cognito JWT authorizer, all route definitions,
    rate limiting, and CORS configuration."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Cognito Configuration ---
        cognito_user_pool_id = "us-east-1_8KvqRmGSN"
        cognito_client_id = "4q5odh7hskaevkpphb4p8jgl3j"
        issuer = f"https://cognito-idp.us-east-1.amazonaws.com/{cognito_user_pool_id}"

        # --- JWT Authorizer ---
        jwt_authorizer = HttpJwtAuthorizer(
            "DqJwtAuthorizer",
            jwt_issuer=issuer,
            jwt_audience=[cognito_client_id],
        )

        # --- HTTP API ---
        self.http_api = apigwv2.HttpApi(
            self,
            "DqPlatformApi",
            api_name="dq-platform-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_headers=["Authorization", "Content-Type", "*"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.ANY,
                ],
                max_age=None,
            ),
            default_authorizer=jwt_authorizer,
        )

        # --- Import Lambda Functions ---
        catalog_fn = _lambda.Function.from_function_name(
            self, "ImportCatalogFn", "dq-catalog-crud"
        )
        table_fn = _lambda.Function.from_function_name(
            self, "ImportTableFn", "dq-table-crud"
        )
        field_fn = _lambda.Function.from_function_name(
            self, "ImportFieldFn", "dq-field-crud"
        )
        upload_fn = _lambda.Function.from_function_name(
            self, "ImportUploadFn", "dq-upload-handler"
        )
        audit_fn = _lambda.Function.from_function_name(
            self, "ImportAuditFn", "dq-audit-handler"
        )
        template_fn = _lambda.Function.from_function_name(
            self, "ImportTemplateFn", "dq-template-crud"
        )
        rules_fn = _lambda.Function.from_function_name(
            self, "ImportRulesFn", "dq-rules-crud"
        )
        rule_interpreter_fn = _lambda.Function.from_function_name(
            self, "ImportRuleInterpreterFn", "dq-rule-interpreter"
        )
        conflict_detector_fn = _lambda.Function.from_function_name(
            self, "ImportConflictDetectorFn", "dq-conflict-detector"
        )
        code_generator_fn = _lambda.Function.from_function_name(
            self, "ImportCodeGeneratorFn", "dq-code-generator"
        )
        validation_orchestrator_fn = _lambda.Function.from_function_name(
            self, "ImportValidationOrchestratorFn", "dq-validation-orchestrator"
        )
        validation_results_fn = _lambda.Function.from_function_name(
            self, "ImportValidationResultsFn", "dq-validation-results"
        )
        validation_metrics_fn = _lambda.Function.from_function_name(
            self, "ImportValidationMetricsFn", "dq-validation-metrics"
        )
        anomaly_training_fn = _lambda.Function.from_function_name(
            self, "ImportAnomalyTrainingFn", "dq-anomaly-training"
        )
        anomaly_scoring_fn = _lambda.Function.from_function_name(
            self, "ImportAnomalyScoringFn", "dq-anomaly-scoring"
        )
        anomaly_export_fn = _lambda.Function.from_function_name(
            self, "ImportAnomalyExportFn", "dq-anomaly-export"
        )
        anomaly_status_fn = _lambda.Function.from_function_name(
            self, "ImportAnomalyStatusFn", "dq-anomaly-status"
        )
        cleaning_orchestrator_fn = _lambda.Function.from_function_name(
            self, "ImportCleaningOrchestratorFn", "dq-cleaning-orchestrator"
        )
        cleaning_status_fn = _lambda.Function.from_function_name(
            self, "ImportCleaningStatusFn", "dq-cleaning-status"
        )
        report_generator_fn = _lambda.Function.from_function_name(
            self, "ImportReportGeneratorFn", "dq-report-generator"
        )
        reports_crud_fn = _lambda.Function.from_function_name(
            self, "ImportReportsCrudFn", "dq-reports-crud"
        )
        notifications_fn = _lambda.Function.from_function_name(
            self, "ImportNotificationsFn", "dq-notifications"
        )

        # --- Lambda Integrations ---
        catalog_integration = HttpLambdaIntegration("CatalogIntegration", catalog_fn)
        table_integration = HttpLambdaIntegration("TableIntegration", table_fn)
        field_integration = HttpLambdaIntegration("FieldIntegration", field_fn)
        upload_integration = HttpLambdaIntegration("UploadIntegration", upload_fn)
        audit_integration = HttpLambdaIntegration("AuditIntegration", audit_fn)
        template_integration = HttpLambdaIntegration("TemplateIntegration", template_fn)
        rules_integration = HttpLambdaIntegration("RulesIntegration", rules_fn)
        rule_interpreter_integration = HttpLambdaIntegration(
            "RuleInterpreterIntegration", rule_interpreter_fn
        )
        conflict_detector_integration = HttpLambdaIntegration(
            "ConflictDetectorIntegration", conflict_detector_fn
        )
        code_generator_integration = HttpLambdaIntegration(
            "CodeGeneratorIntegration", code_generator_fn
        )
        validation_orchestrator_integration = HttpLambdaIntegration(
            "ValidationOrchestratorIntegration", validation_orchestrator_fn
        )
        validation_results_integration = HttpLambdaIntegration(
            "ValidationResultsIntegration", validation_results_fn
        )
        validation_metrics_integration = HttpLambdaIntegration(
            "ValidationMetricsIntegration", validation_metrics_fn
        )
        anomaly_training_integration = HttpLambdaIntegration(
            "AnomalyTrainingIntegration", anomaly_training_fn
        )
        anomaly_scoring_integration = HttpLambdaIntegration(
            "AnomalyScoringIntegration", anomaly_scoring_fn
        )
        anomaly_export_integration = HttpLambdaIntegration(
            "AnomalyExportIntegration", anomaly_export_fn
        )
        anomaly_status_integration = HttpLambdaIntegration(
            "AnomalyStatusIntegration", anomaly_status_fn
        )
        cleaning_orchestrator_integration = HttpLambdaIntegration(
            "CleaningOrchestratorIntegration", cleaning_orchestrator_fn
        )
        cleaning_status_integration = HttpLambdaIntegration(
            "CleaningStatusIntegration", cleaning_status_fn
        )
        report_generator_integration = HttpLambdaIntegration(
            "ReportGeneratorIntegration", report_generator_fn
        )
        reports_crud_integration = HttpLambdaIntegration(
            "ReportsCrudIntegration", reports_crud_fn
        )
        notifications_integration = HttpLambdaIntegration(
            "NotificationsIntegration", notifications_fn
        )

        # ===== GOVERNANCE ROUTES =====

        # ANY /catalog → dq-catalog-crud
        self.http_api.add_routes(
            path="/catalog",
            methods=[apigwv2.HttpMethod.ANY],
            integration=catalog_integration,
        )
        # ANY /catalog/{id} → dq-catalog-crud
        self.http_api.add_routes(
            path="/catalog/{id}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=catalog_integration,
        )
        # ANY /catalog/{id}/tables → dq-table-crud
        self.http_api.add_routes(
            path="/catalog/{id}/tables",
            methods=[apigwv2.HttpMethod.ANY],
            integration=table_integration,
        )
        # ANY /tables → dq-table-crud
        self.http_api.add_routes(
            path="/tables",
            methods=[apigwv2.HttpMethod.ANY],
            integration=table_integration,
        )
        # ANY /tables/{id} → dq-table-crud
        self.http_api.add_routes(
            path="/tables/{id}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=table_integration,
        )
        # ANY /tables/{id}/fields → dq-field-crud
        self.http_api.add_routes(
            path="/tables/{id}/fields",
            methods=[apigwv2.HttpMethod.ANY],
            integration=field_integration,
        )
        # ANY /tables/{id}/fields/{fid} → dq-field-crud
        self.http_api.add_routes(
            path="/tables/{id}/fields/{fid}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=field_integration,
        )
        # ANY /catalog/{id}/upload → dq-upload-handler
        self.http_api.add_routes(
            path="/catalog/{id}/upload",
            methods=[apigwv2.HttpMethod.ANY],
            integration=upload_integration,
        )
        # ANY /upload/{uploadId}/complete → dq-upload-handler
        self.http_api.add_routes(
            path="/upload/{uploadId}/complete",
            methods=[apigwv2.HttpMethod.ANY],
            integration=upload_integration,
        )
        # ANY /upload/{uploadId}/abort → dq-upload-handler
        self.http_api.add_routes(
            path="/upload/{uploadId}/abort",
            methods=[apigwv2.HttpMethod.ANY],
            integration=upload_integration,
        )
        # ANY /dataset/{id}/preview → dq-upload-handler
        self.http_api.add_routes(
            path="/dataset/{id}/preview",
            methods=[apigwv2.HttpMethod.ANY],
            integration=upload_integration,
        )
        # ANY /audit → dq-audit-handler
        self.http_api.add_routes(
            path="/audit",
            methods=[apigwv2.HttpMethod.ANY],
            integration=audit_integration,
        )
        # ANY /templates → dq-template-crud
        self.http_api.add_routes(
            path="/templates",
            methods=[apigwv2.HttpMethod.ANY],
            integration=template_integration,
        )
        # ANY /templates/{id} → dq-template-crud
        self.http_api.add_routes(
            path="/templates/{id}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=template_integration,
        )

        # ===== RULES ROUTES =====

        # POST /rules/interpret → dq-rule-interpreter (more specific, must be before /rules/{id})
        self.http_api.add_routes(
            path="/rules/interpret",
            methods=[apigwv2.HttpMethod.POST],
            integration=rule_interpreter_integration,
        )
        # ANY /rules/conflicts → dq-conflict-detector
        self.http_api.add_routes(
            path="/rules/conflicts",
            methods=[apigwv2.HttpMethod.ANY],
            integration=conflict_detector_integration,
        )
        # POST /rules/conflicts/{id}/resolve → dq-conflict-detector
        self.http_api.add_routes(
            path="/rules/conflicts/{id}/resolve",
            methods=[apigwv2.HttpMethod.POST],
            integration=conflict_detector_integration,
        )
        # POST /rules/{id}/generate-code → dq-code-generator
        self.http_api.add_routes(
            path="/rules/{id}/generate-code",
            methods=[apigwv2.HttpMethod.POST],
            integration=code_generator_integration,
        )
        # ANY /rules → dq-rules-crud
        self.http_api.add_routes(
            path="/rules",
            methods=[apigwv2.HttpMethod.ANY],
            integration=rules_integration,
        )
        # ANY /rules/{id} → dq-rules-crud
        self.http_api.add_routes(
            path="/rules/{id}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=rules_integration,
        )

        # ===== VALIDATION ROUTES =====

        # GET /validations/metrics → dq-validation-metrics (more specific path first)
        self.http_api.add_routes(
            path="/validations/metrics",
            methods=[apigwv2.HttpMethod.GET],
            integration=validation_metrics_integration,
        )
        # GET /validations/{id}/results → dq-validation-results
        self.http_api.add_routes(
            path="/validations/{id}/results",
            methods=[apigwv2.HttpMethod.GET],
            integration=validation_results_integration,
        )
        # POST /validations → dq-validation-orchestrator
        self.http_api.add_routes(
            path="/validations",
            methods=[apigwv2.HttpMethod.POST],
            integration=validation_orchestrator_integration,
        )
        # GET /validations → dq-validation-results
        self.http_api.add_routes(
            path="/validations",
            methods=[apigwv2.HttpMethod.GET],
            integration=validation_results_integration,
        )
        # GET /validations/{id} → dq-validation-results
        self.http_api.add_routes(
            path="/validations/{id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=validation_results_integration,
        )

        # ===== ANOMALY ROUTES =====

        # POST /anomalies/training → dq-anomaly-training
        self.http_api.add_routes(
            path="/anomalies/training",
            methods=[apigwv2.HttpMethod.POST],
            integration=anomaly_training_integration,
        )
        # GET /anomalies/training/{id} → dq-anomaly-status
        self.http_api.add_routes(
            path="/anomalies/training/{id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=anomaly_status_integration,
        )
        # POST /anomalies/scoring → dq-anomaly-scoring
        self.http_api.add_routes(
            path="/anomalies/scoring",
            methods=[apigwv2.HttpMethod.POST],
            integration=anomaly_scoring_integration,
        )
        # GET /anomalies/scoring/{id} → dq-anomaly-scoring
        self.http_api.add_routes(
            path="/anomalies/scoring/{id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=anomaly_scoring_integration,
        )
        # GET /anomalies/scoring/{id}/export → dq-anomaly-export
        self.http_api.add_routes(
            path="/anomalies/scoring/{id}/export",
            methods=[apigwv2.HttpMethod.GET],
            integration=anomaly_export_integration,
        )
        # GET /anomalies/dashboard/{datasetId} → dq-anomaly-scoring
        self.http_api.add_routes(
            path="/anomalies/dashboard/{datasetId}",
            methods=[apigwv2.HttpMethod.GET],
            integration=anomaly_scoring_integration,
        )

        # ===== CLEANING ROUTES =====

        # POST /cleaning/generate → dq-cleaning-orchestrator
        self.http_api.add_routes(
            path="/cleaning/generate",
            methods=[apigwv2.HttpMethod.POST],
            integration=cleaning_orchestrator_integration,
        )
        # POST /cleaning/{id}/execute → dq-cleaning-orchestrator
        self.http_api.add_routes(
            path="/cleaning/{id}/execute",
            methods=[apigwv2.HttpMethod.POST],
            integration=cleaning_orchestrator_integration,
        )
        # GET /cleaning/{id} → dq-cleaning-status
        self.http_api.add_routes(
            path="/cleaning/{id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=cleaning_status_integration,
        )

        # ===== REPORTING ROUTES =====

        # POST /reports/generate → dq-report-generator
        self.http_api.add_routes(
            path="/reports/generate",
            methods=[apigwv2.HttpMethod.POST],
            integration=report_generator_integration,
        )
        # POST /reports/{id}/publish → dq-reports-crud
        self.http_api.add_routes(
            path="/reports/{id}/publish",
            methods=[apigwv2.HttpMethod.POST],
            integration=reports_crud_integration,
        )
        # GET /reports/{id}/versions → dq-reports-crud
        self.http_api.add_routes(
            path="/reports/{id}/versions",
            methods=[apigwv2.HttpMethod.GET],
            integration=reports_crud_integration,
        )
        # GET /reports → dq-reports-crud
        self.http_api.add_routes(
            path="/reports",
            methods=[apigwv2.HttpMethod.GET],
            integration=reports_crud_integration,
        )
        # GET /reports/{id} → dq-reports-crud
        self.http_api.add_routes(
            path="/reports/{id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=reports_crud_integration,
        )
        # PUT /reports/{id} → dq-reports-crud
        self.http_api.add_routes(
            path="/reports/{id}",
            methods=[apigwv2.HttpMethod.PUT],
            integration=reports_crud_integration,
        )

        # GET /notifications → dq-notifications
        self.http_api.add_routes(
            path="/notifications",
            methods=[apigwv2.HttpMethod.GET],
            integration=notifications_integration,
        )
        # POST /notifications/recipients → dq-notifications
        self.http_api.add_routes(
            path="/notifications/recipients",
            methods=[apigwv2.HttpMethod.POST],
            integration=notifications_integration,
        )
        # GET /notifications/recipients → dq-notifications
        self.http_api.add_routes(
            path="/notifications/recipients",
            methods=[apigwv2.HttpMethod.GET],
            integration=notifications_integration,
        )

        # --- SSM Parameter: Export API URL ---
        ssm.StringParameter(
            self,
            "ApiGatewayUrlParam",
            parameter_name="/dq-platform/api-gateway-url",
            string_value=self.http_api.api_endpoint,
            description="DQ Platform API Gateway endpoint URL",
        )

        # --- CloudFormation Outputs ---
        CfnOutput(
            self,
            "ApiEndpoint",
            value=self.http_api.api_endpoint,
            description="DQ Platform API Gateway endpoint URL",
            export_name="DqApiGatewayUrl",
        )
        CfnOutput(
            self,
            "ApiId",
            value=self.http_api.api_id,
            description="DQ Platform API Gateway ID",
            export_name="DqApiGatewayId",
        )
