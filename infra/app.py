#!/usr/bin/env python3
"""CDK app entry point for the Data Quality Platform infrastructure.

Monorepo: DataQualityWebAppProject/dq-platform
AWS Account: 108782054634
Region: us-east-1
CDK Version: 2.1128.1
"""
import aws_cdk as cdk

from stacks.vpc_stack import DqVpcStack
from stacks.cognito_stack import DqCognitoStack
from stacks.dynamodb_stack import DqDynamoDBStack
from stacks.s3_stack import DqS3Stack
from stacks.iam_stack import DqIamStack
from stacks.lambda_stack import DqLambdaStack
from stacks.api_gateway_stack import DqApiGatewayStack
from stacks.cloudfront_stack import DqCloudFrontStack

app = cdk.App()

env = cdk.Environment(
    account="108782054634",
    region="us-east-1",
)

# Foundation infrastructure stacks
vpc_stack = DqVpcStack(app, "DqVpcStack", env=env)

cognito_stack = DqCognitoStack(app, "DqCognitoStack", env=env)

dynamodb_stack = DqDynamoDBStack(app, "DqDynamoDBStack", env=env)

s3_stack = DqS3Stack(app, "DqS3Stack", env=env)

iam_stack = DqIamStack(app, "DqIamStack", env=env)
iam_stack.add_dependency(s3_stack)
iam_stack.add_dependency(dynamodb_stack)

# Compute and API stacks
lambda_stack = DqLambdaStack(app, "DqLambdaStack", env=env)
lambda_stack.add_dependency(vpc_stack)
lambda_stack.add_dependency(iam_stack)
lambda_stack.add_dependency(dynamodb_stack)
lambda_stack.add_dependency(s3_stack)

api_gateway_stack = DqApiGatewayStack(app, "DqApiGatewayStack", env=env)
api_gateway_stack.add_dependency(cognito_stack)
api_gateway_stack.add_dependency(lambda_stack)

cloudfront_stack = DqCloudFrontStack(app, "DqCloudFrontStack", env=env)
cloudfront_stack.add_dependency(s3_stack)
cloudfront_stack.add_dependency(api_gateway_stack)

app.synth()
