"""DqS3Stack - S3 buckets for the Data Quality Platform.

Creates individual S3 buckets for each concern:
- dq-raw-108782054634: Dataset uploads (RETAIN, IA transition after 90 days)
- dq-clean-108782054634: Cleaned datasets (RETAIN)
- dq-metrics-108782054634: Validation metrics (RETAIN)
- dq-scripts-108782054634: Generated scripts (RETAIN)
- dq-frontend-108782054634: Frontend SPA assets (DESTROY, OAI access)
- dq-mlflow-108782054634: Model artifacts (RETAIN)
- dq-exports-108782054634: Anomaly CSV exports (DESTROY, 7-day expiry)
- dq-backups-108782054634: Pre-cleaning backups (RETAIN)
- dq-reports-108782054634: Report storage (RETAIN)

All buckets block public access, use SSE-S3 encryption, and export ARNs to SSM.
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from constructs import Construct


class DqS3Stack(Stack):
    """S3 buckets for the Data Quality Platform with lifecycle policies and SSM exports."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account_suffix = "108782054634"

        # -----------------------------------------------------------
        # dq-raw: Dataset uploads
        # Lifecycle: transition to IA after 90 days
        # -----------------------------------------------------------
        self.raw_bucket = s3.Bucket(
            self,
            "RawBucket",
            bucket_name=f"dq-raw-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="transition-to-ia-90d",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(90),
                        )
                    ],
                ),
            ],
        )

        # -----------------------------------------------------------
        # dq-clean: Cleaned datasets
        # -----------------------------------------------------------
        self.clean_bucket = s3.Bucket(
            self,
            "CleanBucket",
            bucket_name=f"dq-clean-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # dq-metrics: Validation metrics
        # -----------------------------------------------------------
        self.metrics_bucket = s3.Bucket(
            self,
            "MetricsBucket",
            bucket_name=f"dq-metrics-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # dq-scripts: Generated validation/cleaning scripts
        # -----------------------------------------------------------
        self.scripts_bucket = s3.Bucket(
            self,
            "ScriptsBucket",
            bucket_name=f"dq-scripts-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # dq-frontend: Frontend SPA assets (CloudFront OAI access)
        # -----------------------------------------------------------
        self.frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"dq-frontend-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # dq-mlflow: Model artifacts
        # -----------------------------------------------------------
        self.mlflow_bucket = s3.Bucket(
            self,
            "MlflowBucket",
            bucket_name=f"dq-mlflow-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # dq-exports: Anomaly CSV exports
        # Lifecycle: objects expire after 7 days
        # -----------------------------------------------------------
        self.exports_bucket = s3.Bucket(
            self,
            "ExportsBucket",
            bucket_name=f"dq-exports-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-after-7d",
                    expiration=Duration.days(7),
                ),
            ],
        )

        # -----------------------------------------------------------
        # dq-backups: Pre-cleaning backups
        # -----------------------------------------------------------
        self.backups_bucket = s3.Bucket(
            self,
            "BackupsBucket",
            bucket_name=f"dq-backups-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # dq-reports: Report storage
        # -----------------------------------------------------------
        self.reports_bucket = s3.Bucket(
            self,
            "ReportsBucket",
            bucket_name=f"dq-reports-{account_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            enforce_ssl=True,
        )

        # -----------------------------------------------------------
        # SSM Parameter Store exports - Bucket ARNs
        # -----------------------------------------------------------
        buckets = {
            "raw": self.raw_bucket,
            "clean": self.clean_bucket,
            "metrics": self.metrics_bucket,
            "scripts": self.scripts_bucket,
            "frontend": self.frontend_bucket,
            "mlflow": self.mlflow_bucket,
            "exports": self.exports_bucket,
            "backups": self.backups_bucket,
            "reports": self.reports_bucket,
        }

        for name, bucket in buckets.items():
            ssm.StringParameter(
                self,
                f"{name.capitalize()}BucketArnParam",
                parameter_name=f"/dq-platform/s3-{name}-bucket-arn",
                string_value=bucket.bucket_arn,
                description=f"ARN for dq-{name} S3 bucket",
            )
            ssm.StringParameter(
                self,
                f"{name.capitalize()}BucketNameParam",
                parameter_name=f"/dq-platform/s3-{name}-bucket-name",
                string_value=bucket.bucket_name,
                description=f"Name of the dq-{name} S3 bucket",
            )
