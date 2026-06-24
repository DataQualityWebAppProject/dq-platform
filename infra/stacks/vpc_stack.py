"""DqVpcStack - VPC with 2 AZs, subnets, NAT Gateway, and VPC Endpoints."""

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ssm as ssm,
)
from constructs import Construct


class DqVpcStack(Stack):
    """VPC infrastructure for the Data Quality Platform.

    Resources:
    - VPC with CIDR 10.0.0.0/16, 2 AZs, public and private subnets
    - 1 NAT Gateway (cost optimization)
    - S3 Gateway Endpoint
    - DynamoDB Gateway Endpoint
    - SSM Parameter Store exports for cross-stack references
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -----------------------------------------------------------
        # VPC: 10.0.0.0/16, 2 AZs, public/private subnets, 1 NAT GW
        # -----------------------------------------------------------
        self.vpc = ec2.Vpc(
            self,
            "DqPlatformVpc",
            vpc_name="dq-platform-vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # -----------------------------------------------------------
        # VPC Endpoints: S3 Gateway and DynamoDB Gateway
        # These reduce NAT Gateway traffic costs for S3/DynamoDB access
        # -----------------------------------------------------------
        self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        self.vpc.add_gateway_endpoint(
            "DynamoDbEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        )

        # -----------------------------------------------------------
        # SSM Parameter Store exports for cross-stack references
        # -----------------------------------------------------------
        ssm.StringParameter(
            self,
            "VpcIdParam",
            parameter_name="/dq-platform/vpc-id",
            string_value=self.vpc.vpc_id,
            description="Data Quality Platform VPC ID",
        )

        # Export private subnet IDs as comma-separated list
        private_subnet_ids = ",".join(
            [subnet.subnet_id for subnet in self.vpc.private_subnets]
        )
        ssm.StringParameter(
            self,
            "PrivateSubnetIdsParam",
            parameter_name="/dq-platform/private-subnet-ids",
            string_value=private_subnet_ids,
            description="Data Quality Platform private subnet IDs (comma-separated)",
        )

        # Export public subnet IDs as comma-separated list
        public_subnet_ids = ",".join(
            [subnet.subnet_id for subnet in self.vpc.public_subnets]
        )
        ssm.StringParameter(
            self,
            "PublicSubnetIdsParam",
            parameter_name="/dq-platform/public-subnet-ids",
            string_value=public_subnet_ids,
            description="Data Quality Platform public subnet IDs (comma-separated)",
        )
