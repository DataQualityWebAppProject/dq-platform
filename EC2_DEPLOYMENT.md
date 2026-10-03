# EC2 Deployment — DQ Platform

## Deployment Details

| Resource | Value |
|----------|-------|
| **Instance ID** | i-09f368ef41ad9d52c |
| **Public IP** | 184.193.20.166 |
| **Frontend URL** | http://184.193.20.166/ |
| **Instance Type** | t3.small |
| **AMI** | Amazon Linux 2023 |
| **VPC** | vpc-0044be29ab11478a0 |
| **Subnet** | subnet-05e18d09fc7d1186d (public, us-east-1a) |
| **Security Group** | sg-07c89119f64004f24 (dq-frontend-ec2-sg) |
| **Key Pair** | dq-ec2-key (saved as dq-ec2-key.pem, not committed) |
| **IAM Role** | dq-ec2-frontend-role |
| **Instance Profile** | dq-ec2-frontend-profile |
| **API Gateway** | https://oyw54eum4m.execute-api.us-east-1.amazonaws.com |
| **Cognito User Pool** | us-east-1_5wvUIjDvC |

## Security Group Rules (sg-07c89119f64004f24)

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 80 | TCP | 0.0.0.0/0 | HTTP (FastAPI/uvicorn) |
| 443 | TCP | 0.0.0.0/0 | HTTPS |
| 22 | TCP | 0.0.0.0/0 | SSH Management |

## Architecture

```
User Browser → EC2 (FastAPI/uvicorn on port 80)
                 ├── Serves the React SPA (static build)
                 ├── /auth/*     → Cognito (server-side, httpOnly cookie)
                 ├── /api/catalog, /api/rules, /api/validations,
                 │   /api/cleaning, /api/reports → direct DynamoDB/S3/Bedrock
                 └── /api/* (fallback) → proxy to API Gateway
```

The server (`server/app.py`) runs under systemd as the `dqplatform` service,
using the venv at `/opt/dqplatform/venv`. It talks to AWS directly via the
`dq-ec2-frontend-role` instance profile — no access keys stored on the box.

## Running the server locally for development

```bash
cd server
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## SSH Access

```bash
ssh -i dq-ec2-key.pem ec2-user@184.193.20.166
```

## Updating the deployment

```bash
# 1. Build the frontend
cd frontend && npm run build

# 2. Copy build output + server code to the instance
scp -i dq-ec2-key.pem -r frontend/dist/* ec2-user@184.193.20.166:/tmp/static/
scp -i dq-ec2-key.pem server/app.py ec2-user@184.193.20.166:/tmp/app.py

# 3. Deploy and restart on the instance
ssh -i dq-ec2-key.pem ec2-user@184.193.20.166 "
  sudo cp /tmp/app.py /opt/dqplatform/app.py &&
  sudo rm -f /opt/dqplatform/static/assets/index-*.js /opt/dqplatform/static/assets/index-*.css &&
  sudo cp -r /tmp/static/* /opt/dqplatform/static/ &&
  sudo systemctl restart dqplatform
"
```

## Infrastructure stacks (CDK, see `infra/`)

| Stack | Resources |
|-------|-----------|
| `DqVpcStack` | VPC, subnets, NAT gateway, S3/DynamoDB endpoints |
| `DqCognitoStack` | User Pool, client, AdminDatos/AnalistaDatos groups |
| `DqDynamoDBStack` | 14 tables (catalogs, rules, validations, etc.) |
| `DqS3Stack` | 9 buckets (raw, clean, scripts, mlflow, reports, etc.) |
| `DqIamStack` | Lambda, Glue, SageMaker execution roles |
| `DqLambdaStack` | 22 Lambda functions for all backend services |
| `DqApiGatewayStack` | HTTP API with Cognito JWT authorizer, 40+ routes |

Deploy with:

```bash
cd infra
cdk deploy --all --require-approval never
```
