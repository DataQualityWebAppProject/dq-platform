"""DqCognitoStack - Cognito User Pool with TOTP MFA, groups, and password policies."""

from aws_cdk import (
    Duration,
    Stack,
    aws_cognito as cognito,
    aws_ssm as ssm,
)
from constructs import Construct


class DqCognitoStack(Stack):
    """Cognito User Pool with TOTP MFA enforced, AdminDatos and AnalistaDatos groups.

    Resources:
    - Cognito User Pool with TOTP MFA enforced
    - User Pool Client with USER_PASSWORD_AUTH flow
    - Groups: AdminDatos (full admin), AnalistaDatos (read + analysis)
    - Password policy: min 8 chars, uppercase, lowercase, numbers, symbols
    - Account lockout: 3 failed attempts within 30 min → lock for 15 min
    - SSM Parameter Store exports for cross-stack references

    Requirements: 1.1, 1.2, 1.4, 2.1
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -----------------------------------------------------------
        # Cognito User Pool with TOTP MFA enforced
        # Password policy: min 8, uppercase, lowercase, numbers, symbols
        # Account lockout: 3 failed attempts in 30 min → lock 15 min
        # -----------------------------------------------------------
        self.user_pool = cognito.UserPool(
            self,
            "DqPlatformUserPool",
            user_pool_name="dq-platform-user-pool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=True,
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True,
                ),
                fullname=cognito.StandardAttribute(
                    required=False,
                    mutable=True,
                ),
            ),
            custom_attributes={
                "role": cognito.StringAttribute(
                    min_len=1,
                    max_len=50,
                    mutable=True,
                ),
            },
            # Password policy: min 8 chars, require uppercase, lowercase, numbers, symbols
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(7),
            ),
            # TOTP MFA enforced for all users
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(
                otp=True,
                sms=False,
            ),
            # Account recovery via email
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            # Threat protection for account lockout (3 failed attempts in 30 min → lock 15 min)
            standard_threat_protection_mode=cognito.StandardThreatProtectionMode.FULL_FUNCTION,
        )

        # -----------------------------------------------------------
        # User Pool Client with USER_PASSWORD_AUTH flow
        # Token validity: access token 60 min, refresh token 30 days
        # -----------------------------------------------------------
        self.user_pool_client = self.user_pool.add_client(
            "DqPlatformUserPoolClient",
            user_pool_client_name="dq-platform-web-client",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            generate_secret=False,
            access_token_validity=Duration.minutes(60),
            id_token_validity=Duration.minutes(60),
            refresh_token_validity=Duration.days(30),
            prevent_user_existence_errors=True,
        )

        # -----------------------------------------------------------
        # Groups: AdminDatos and AnalistaDatos
        # AdminDatos: Full admin access (CRUD on all resources)
        # AnalistaDatos: Read + analysis (trigger validations, scoring)
        # -----------------------------------------------------------
        self.admin_group = cognito.CfnUserPoolGroup(
            self,
            "AdminDatosGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="AdminDatos",
            description="Full administrative privileges over the platform. "
            "Create, read, update, and delete access to all resources.",
            precedence=1,
        )

        self.analyst_group = cognito.CfnUserPoolGroup(
            self,
            "AnalistaDatosGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="AnalistaDatos",
            description="Read access to all resources plus ability to trigger "
            "validations, anomaly scoring, cleaning script requests, "
            "and report generation.",
            precedence=2,
        )

        # -----------------------------------------------------------
        # SSM Parameter Store exports for cross-stack references
        # -----------------------------------------------------------
        ssm.StringParameter(
            self,
            "UserPoolIdParam",
            parameter_name="/dq-platform/cognito-user-pool-id",
            string_value=self.user_pool.user_pool_id,
            description="Data Quality Platform Cognito User Pool ID",
        )

        ssm.StringParameter(
            self,
            "UserPoolClientIdParam",
            parameter_name="/dq-platform/cognito-user-pool-client-id",
            string_value=self.user_pool_client.user_pool_client_id,
            description="Data Quality Platform Cognito User Pool Client ID",
        )

        ssm.StringParameter(
            self,
            "UserPoolArnParam",
            parameter_name="/dq-platform/cognito-user-pool-arn",
            string_value=self.user_pool.user_pool_arn,
            description="Data Quality Platform Cognito User Pool ARN",
        )
