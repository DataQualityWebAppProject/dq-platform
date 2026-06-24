# EC2 Frontend Deployment Summary

## Deployment Details

| Resource | Value |
|----------|-------|
| **Instance ID** | i-0d328d87783a23598 |
| **Public IP** | 98.80.197.70 |
| **Frontend URL** | http://98.80.197.70/ |
| **Instance Type** | t2.micro |
| **AMI** | ami-08f44e8eca9095668 (Amazon Linux 2023) |
| **VPC** | vpc-0044be29ab11478a0 |
| **Subnet** | subnet-05e18d09fc7d1186d (public, us-east-1a) |
| **Security Group** | sg-07c89119f64004f24 (dq-frontend-ec2-sg) |
| **Key Pair** | dq-platform-key (saved as dq-platform-key.pem) |
| **IAM Role** | dq-ec2-frontend-role |
| **Instance Profile** | dq-ec2-frontend-profile |
| **API Gateway** | https://86iruyzin2.execute-api.us-east-1.amazonaws.com |

## Security Group Rules (sg-07c89119f64004f24)

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 80 | TCP | 0.0.0.0/0 | HTTP (Nginx) |
| 443 | TCP | 0.0.0.0/0 | HTTPS |
| 22 | TCP | 0.0.0.0/0 | SSH Management |

## Architecture

```
User Browser --> EC2 (Nginx on port 80) --> Serves React SPA
                                        --> SPA calls API Gateway directly
```

## Nginx Configuration

- Web root: `/usr/share/nginx/html`
- SPA routing: all paths fallback to `/index.html`
- Assets caching: 1 year with immutable headers
- Gzip compression enabled

## S3 Staging Bucket

Frontend build files are stored in `s3://dq-frontend-108782054634/` as a staging area.
The EC2 instance pulls files from S3 on boot via user data script.

## SSH Access

```bash
ssh -i dq-platform-key.pem ec2-user@98.80.197.70
```

## Updating the Frontend

To deploy a new frontend version:
```bash
# 1. Build the frontend
cd frontend && npm run build

# 2. Upload to S3
aws s3 sync frontend/dist/ s3://dq-frontend-108782054634/ --region us-east-1

# 3. Pull on EC2 (via SSH or SSM)
ssh -i dq-platform-key.pem ec2-user@98.80.197.70 "sudo aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1"
```
