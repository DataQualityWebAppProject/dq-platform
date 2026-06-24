"""DqIamStack - IAM roles for Lambda, Glue, and SageMaker execution.

Creates three least-privilege IAM execution roles:
- DqLambdaExecutionRole: DynamoDB, S3, Bedrock, SES, Glue, SageMaker, SSM, CloudWatch Logs
- DqGlueExecutionRole: S3 (dq-raw-*, dq-clean-*, dq-scripts-*), DynamoDB, CloudWatch Logs
- DqSageMakerExecutionRole: S3 (dq-mlflow-*, dq-raw-*), ECR, CloudWatch Logs

Role ARNs are exported to SSM Parameter Store under /dq-platform/ prefix.
"""

from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_ssm as ssm,
)
from constructs import Construct


class DqIamStack(Stack):
    """IAM execution roles for DQ Platform services."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account_id = "108782054634"
        region = "us-east-1"

        # -----------------------------------------------------------
        # Lambda Execution Role - DqLambdaExecutionRole
        # -----------------------------------------------------------
        self.lambda_role = iam.Role(
            self,
            "DqLambdaExecutionRole",
            role_name="DqLambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for Data Quality Platform Lambda functions",
        )

        # Attach AWS managed policies for basic Lambda execution
        self.lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )
        self.lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaVPCAccessExecutionRole"
            )
        )

        # CloudWatch Logs
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account_id}:*",
                ],
            )
        )

        # DynamoDB read/write on all dq-* tables
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="DynamoDBAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchGetItem",
                    "dynamodb:BatchWriteItem",
                ],
                resources=[
                    f"arn:aws:dynamodb:{region}:{account_id}:table/dq-*",
                ],
            )
        )

        # S3 read/write on all dq-* buckets
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3Access",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                ],
                resources=[
                    f"arn:aws:s3:::dq-*-{account_id}/*",
                ],
            )
        )

        # Bedrock InvokeModel
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                ],
                resources=[
                    f"arn:aws:bedrock:{region}::foundation-model/*",
                ],
            )
        )

        # SES SendEmail, SendRawEmail
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="SESAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ses:SendEmail",
                    "ses:SendRawEmail",
                ],
                resources=["*"],
            )
        )

        # Glue StartJobRun, GetJobRun
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "glue:StartJobRun",
                    "glue:GetJobRun",
                ],
                resources=[
                    f"arn:aws:glue:{region}:{account_id}:job/dq-*",
                ],
            )
        )

        # SageMaker InvokeEndpoint, CreateTrainingJob, DescribeTrainingJob
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:InvokeEndpoint",
                    "sagemaker:CreateTrainingJob",
                    "sagemaker:DescribeTrainingJob",
                ],
                resources=[
                    f"arn:aws:sagemaker:{region}:{account_id}:*",
                ],
            )
        )

        # SSM GetParameter on /dq-platform/*
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMReadAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:GetParameter",
                ],
                resources=[
                    f"arn:aws:ssm:{region}:{account_id}:parameter/dq-platform/*",
                ],
            )
        )

        # -----------------------------------------------------------
        # Glue Execution Role - DqGlueExecutionRole
        # S3: dq-raw-*, dq-clean-*, dq-scripts-* buckets
        # DynamoDB: dq-validation-results, dq-cleaning-jobs
        # -----------------------------------------------------------
        self.glue_role = iam.Role(
            self,
            "DqGlueExecutionRole",
            role_name="DqGlueExecutionRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            description="Execution role for Data Quality Platform Glue jobs",
        )

        # CloudWatch Logs for Glue
        self.glue_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account_id}:*",
                ],
            )
        )

        # S3 read/write for dq-raw-*, dq-clean-*, dq-scripts-* buckets
        self.glue_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ReadWriteAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                ],
                resources=[
                    "arn:aws:s3:::dq-raw-*",
                    "arn:aws:s3:::dq-raw-*/*",
                    "arn:aws:s3:::dq-clean-*",
                    "arn:aws:s3:::dq-clean-*/*",
                    "arn:aws:s3:::dq-scripts-*",
                    "arn:aws:s3:::dq-scripts-*/*",
                ],
            )
        )

        # DynamoDB read/write for dq-validation-results and dq-cleaning-jobs
        self.glue_role.add_to_policy(
            iam.PolicyStatement(
                sid="DynamoDBReadWriteAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchGetItem",
                    "dynamodb:BatchWriteItem",
                ],
                resources=[
                    f"arn:aws:dynamodb:{region}:{account_id}:table/dq-validation-results",
                    f"arn:aws:dynamodb:{region}:{account_id}:table/dq-cleaning-jobs",
                ],
            )
        )

        # -----------------------------------------------------------
        # SageMaker Execution Role - DqSageMakerExecutionRole
        # S3: dq-mlflow-*, dq-raw-* buckets
        # ECR: pull container images
        # -----------------------------------------------------------
        self.sagemaker_role = iam.Role(
            self,
            "DqSageMakerExecutionRole",
            role_name="DqSageMakerExecutionRole",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            description="Execution role for Data Quality Platform SageMaker training and inference",
        )

        # CloudWatch Logs for SageMaker
        self.sagemaker_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account_id}:*",
                ],
            )
        )

        # S3 read/write for dq-mlflow-* and dq-raw-* buckets
        self.sagemaker_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ReadWriteAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                ],
                resources=[
                    "arn:aws:s3:::dq-mlflow-*",
                    "arn:aws:s3:::dq-mlflow-*/*",
                    "arn:aws:s3:::dq-raw-*",
                    "arn:aws:s3:::dq-raw-*/*",
                ],
            )
        )

        # ECR pull for training containers
        self.sagemaker_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRPullAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )

        # -----------------------------------------------------------
        # SSM Parameter Store exports - Role ARNs
        # -----------------------------------------------------------
        ssm.StringParameter(
            self,
            "LambdaRoleArnParam",
            parameter_name="/dq-platform/iam-lambda-role-arn",
            string_value=self.lambda_role.role_arn,
            description="ARN for the Lambda execution role",
        )

        ssm.StringParameter(
            self,
            "GlueRoleArnParam",
            parameter_name="/dq-platform/iam-glue-role-arn",
            string_value=self.glue_role.role_arn,
            description="ARN for the Glue execution role",
        )

        ssm.StringParameter(
            self,
            "SageMakerRoleArnParam",
            parameter_name="/dq-platform/iam-sagemaker-role-arn",
            string_value=self.sagemaker_role.role_arn,
            description="ARN for the SageMaker execution role",
        )
