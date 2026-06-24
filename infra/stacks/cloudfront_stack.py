"""DqCloudFrontStack - CloudFront distribution for frontend and API.

Creates:
- Origin Access Identity for S3 frontend bucket
- CloudFront distribution with S3 as default origin
- SPA routing via custom error responses (403/404 -> /index.html)
- SSM export of CloudFront domain name
"""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from constructs import Construct


class DqCloudFrontStack(Stack):
    """CloudFront distribution with S3 frontend origin (default) and
    API Gateway origin (/api/*). OAI, SPA routing, cache policies."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Import the frontend bucket by name
        frontend_bucket = s3.Bucket.from_bucket_name(
            self, "FrontendBucket", "dq-frontend-108782054634"
        )

        # Origin Access Identity for S3
        oai = cloudfront.OriginAccessIdentity(
            self,
            "FrontendOAI",
            comment="OAI for DQ Platform frontend bucket",
        )

        # Grant read access to OAI on the frontend bucket
        frontend_bucket.grant_read(oai)

        # CloudFront Distribution
        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            comment="DQ Platform - Data Quality Frontend",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    frontend_bucket,
                    origin_access_identity=oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            ),
            # SPA routing - redirect 403/404 to index.html
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        # SSM Parameter for CloudFront domain
        ssm.StringParameter(
            self,
            "CloudFrontDomainParam",
            parameter_name="/dq-platform/cloudfront-domain",
            string_value=distribution.distribution_domain_name,
            description="CloudFront distribution domain name for DQ Platform",
        )

        # CloudFormation Output
        CfnOutput(
            self,
            "DistributionDomainName",
            value=distribution.distribution_domain_name,
            description="CloudFront Distribution Domain Name",
        )

        CfnOutput(
            self,
            "DistributionId",
            value=distribution.distribution_id,
            description="CloudFront Distribution ID",
        )
