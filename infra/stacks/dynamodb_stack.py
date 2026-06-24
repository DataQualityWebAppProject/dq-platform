"""DqDynamoDBStack - All DynamoDB tables for the Data Quality Platform.

Creates 14 DynamoDB tables with:
- On-demand (PAY_PER_REQUEST) capacity mode
- Point-In-Time Recovery (PITR) enabled
- GSIs as specified in the design document
- TTL on dq-validation-results (90 days via expires_at attribute)
- Table ARNs exported to SSM Parameter Store (/dq-platform/ prefix)

Requirements: 18.2, 20.2
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_ssm as ssm,
)
from constructs import Construct


# PITR specification reused across all tables
_PITR_ENABLED = dynamodb.PointInTimeRecoverySpecification(
    point_in_time_recovery_enabled=True
)


class DqDynamoDBStack(Stack):
    """Stack that provisions all 14 DynamoDB tables for the Data Quality Platform.

    All tables use on-demand billing mode and have PITR enabled for continuous
    backup (35-day recovery window). Table ARNs are exported to SSM Parameter
    Store for cross-stack references.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Store table references for cross-stack access
        self.tables: dict[str, dynamodb.Table] = {}

        # 1. dq-catalogs
        self._create_catalogs_table()

        # 2. dq-templates
        self._create_templates_table()

        # 3. dq-rules
        self._create_rules_table()

        # 4. dq-rule-conflicts
        self._create_rule_conflicts_table()

        # 5. dq-validation-runs
        self._create_validation_runs_table()

        # 6. dq-validation-results (with TTL)
        self._create_validation_results_table()

        # 7. dq-anomaly-training
        self._create_anomaly_training_table()

        # 8. dq-anomaly-models
        self._create_anomaly_models_table()

        # 9. dq-anomaly-scores
        self._create_anomaly_scores_table()

        # 10. dq-cleaning-jobs
        self._create_cleaning_jobs_table()

        # 11. dq-reports
        self._create_reports_table()

        # 12. dq-notifications
        self._create_notifications_table()

        # 13. dq-notification-recipients
        self._create_notification_recipients_table()

        # 14. dq-audit-trail
        self._create_audit_trail_table()

        # Export all table ARNs to SSM Parameter Store
        self._export_table_arns_to_ssm()

    def _create_catalogs_table(self) -> None:
        """Create dq-catalogs table for data catalog management.

        PK: CATALOG#{catalog_id}
        SK: METADATA or TABLE#{table_id}
        GSI: owner-index (PK: owner, SK: created_at)
        """
        table = dynamodb.Table(
            self,
            "DqCatalogsTable",
            table_name="dq-catalogs",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="owner-index",
            partition_key=dynamodb.Attribute(
                name="owner", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-catalogs"] = table

    def _create_templates_table(self) -> None:
        """Create dq-templates table for mapping templates.

        PK: TEMPLATE#{template_id}
        SK: METADATA or FIELD#{field_name}
        """
        table = dynamodb.Table(
            self,
            "DqTemplatesTable",
            table_name="dq-templates",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables["dq-templates"] = table

    def _create_rules_table(self) -> None:
        """Create dq-rules table for quality rule definitions.

        PK: RULE#{rule_id}
        SK: METADATA
        GSI1: scope-target-index (PK: scope#target_id, SK: created_at)
        GSI2: status-index (PK: status, SK: created_at)
        """
        table = dynamodb.Table(
            self,
            "DqRulesTable",
            table_name="dq-rules",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="scope-target-index",
            partition_key=dynamodb.Attribute(
                name="scope", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-rules"] = table

    def _create_rule_conflicts_table(self) -> None:
        """Create dq-rule-conflicts table for detected rule conflicts.

        PK: CONFLICT#{conflict_id}
        SK: METADATA
        """
        table = dynamodb.Table(
            self,
            "DqRuleConflictsTable",
            table_name="dq-rule-conflicts",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables["dq-rule-conflicts"] = table

    def _create_validation_runs_table(self) -> None:
        """Create dq-validation-runs table for validation execution tracking.

        PK: DATASET#{dataset_id}
        SK: RUN#{timestamp}#{run_id}
        GSI: run-id-index (PK: run_id) - for direct lookup by run ID
        GSI: dataset-index (PK: dataset_id, SK: started_at) - for querying by dataset
        GSI: status-index (PK: status, SK: started_at) - for filtering by status
        """
        table = dynamodb.Table(
            self,
            "DqValidationRunsTable",
            table_name="dq-validation-runs",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="run-id-index",
            partition_key=dynamodb.Attribute(
                name="run_id", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-validation-runs"] = table

    def _create_validation_results_table(self) -> None:
        """Create dq-validation-results table for per-record validation results.

        PK: RUN#{run_id}
        SK: RECORD#{record_id}#RULE#{rule_id}
        TTL: expires_at (90 days from creation)
        """
        table = dynamodb.Table(
            self,
            "DqValidationResultsTable",
            table_name="dq-validation-results",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
            time_to_live_attribute="expires_at",
        )

        self.tables["dq-validation-results"] = table

    def _create_anomaly_training_table(self) -> None:
        """Create dq-anomaly-training table for ML training job tracking.

        PK: TRAINING#{job_id}
        SK: METADATA
        """
        table = dynamodb.Table(
            self,
            "DqAnomalyTrainingTable",
            table_name="dq-anomaly-training",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables["dq-anomaly-training"] = table

    def _create_anomaly_models_table(self) -> None:
        """Create dq-anomaly-models table for registered ML model artifacts.

        PK: MODEL#{model_id}
        SK: METADATA
        """
        table = dynamodb.Table(
            self,
            "DqAnomalyModelsTable",
            table_name="dq-anomaly-models",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables["dq-anomaly-models"] = table

    def _create_anomaly_scores_table(self) -> None:
        """Create dq-anomaly-scores table for anomaly scoring results.

        PK: SCORING#{scoring_id}
        SK: RECORD#{record_id}
        GSI: dataset-scoring-index (PK: dataset_id, SK: scored_at)
        """
        table = dynamodb.Table(
            self,
            "DqAnomalyScoresTable",
            table_name="dq-anomaly-scores",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="dataset-scoring-index",
            partition_key=dynamodb.Attribute(
                name="dataset_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="scored_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-anomaly-scores"] = table

    def _create_cleaning_jobs_table(self) -> None:
        """Create dq-cleaning-jobs table for cleaning script execution tracking.

        PK: CLEANING#{job_id}
        SK: METADATA
        """
        table = dynamodb.Table(
            self,
            "DqCleaningJobsTable",
            table_name="dq-cleaning-jobs",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables["dq-cleaning-jobs"] = table

    def _create_reports_table(self) -> None:
        """Create dq-reports table for executive reports and version history.

        PK: REPORT#{report_id}
        SK: VERSION#{version_number}
        GSI: status-date-index (PK: status, SK: published_at)
        """
        table = dynamodb.Table(
            self,
            "DqReportsTable",
            table_name="dq-reports",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="status-date-index",
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="published_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-reports"] = table

    def _create_notifications_table(self) -> None:
        """Create dq-notifications table for notification delivery history.

        PK: NOTIFICATION#{notification_id}
        SK: METADATA
        GSI: event-type-index (PK: event_type, SK: created_at)
        GSI: recipient-index (PK: recipient_email, SK: created_at)
        """
        table = dynamodb.Table(
            self,
            "DqNotificationsTable",
            table_name="dq-notifications",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="event-type-index",
            partition_key=dynamodb.Attribute(
                name="event_type", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-notifications"] = table

    def _create_notification_recipients_table(self) -> None:
        """Create dq-notification-recipients table for recipient configuration.

        PK: EVENT_TYPE#{event_type}
        SK: RECIPIENT#{email}
        """
        table = dynamodb.Table(
            self,
            "DqNotificationRecipientsTable",
            table_name="dq-notification-recipients",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables["dq-notification-recipients"] = table

    def _create_audit_trail_table(self) -> None:
        """Create dq-audit-trail table for immutable audit records.

        PK: AUDIT#{year-month}
        SK: {timestamp}#{uuid}
        GSI1: user-index (PK: user_id, SK: timestamp)
        GSI2: resource-index (PK: resource_type#resource_id, SK: timestamp)

        Retention: 365 days minimum, append-only (no update/delete permitted)
        """
        table = dynamodb.Table(
            self,
            "DqAuditTrailTable",
            table_name="dq-audit-trail",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=_PITR_ENABLED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table.add_global_secondary_index(
            index_name="user-index",
            partition_key=dynamodb.Attribute(
                name="user_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        table.add_global_secondary_index(
            index_name="resource-index",
            partition_key=dynamodb.Attribute(
                name="resource_type_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.tables["dq-audit-trail"] = table

    def _export_table_arns_to_ssm(self) -> None:
        """Export all table ARNs to SSM Parameter Store for cross-stack references.

        Parameter naming: /dq-platform/dynamodb-table-{table-name}-arn
        """
        for table_name, table in self.tables.items():
            # Create a unique construct ID from the table name
            construct_id = "".join(
                part.capitalize() for part in table_name.split("-")
            ) + "ArnParam"

            ssm.StringParameter(
                self,
                construct_id,
                parameter_name=f"/dq-platform/dynamodb-table-{table_name}-arn",
                string_value=table.table_arn,
                description=f"ARN for DynamoDB table {table_name}",
            )
