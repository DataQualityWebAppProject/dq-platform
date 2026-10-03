#!/bin/bash
set -e
exec > /var/log/user-data.log 2>&1

echo "=== Starting DQ Platform deployment ==="

yum update -y
yum install -y python3.11 python3.11-pip aws-cli

# Create app directory
mkdir -p /opt/dqplatform/static

# Download server code from S3
aws s3 sync s3://dq-frontend-108782054634/server/ /opt/dqplatform/ --region us-east-1 --exclude "static/*"

# Download React build from S3
aws s3 sync s3://dq-frontend-108782054634/static/ /opt/dqplatform/static/ --region us-east-1

# Install Python deps
cd /opt/dqplatform
pip3.11 install -r requirements.txt

# Create systemd service
cat > /etc/systemd/system/dqplatform.service << 'EOF'
[Unit]
Description=DQ Platform FastAPI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/dqplatform
ExecStart=/usr/bin/python3.11 -m uvicorn app:app --host 0.0.0.0 --port 80
Restart=always
RestartSec=5
Environment=AWS_DEFAULT_REGION=us-east-1
Environment=API_GATEWAY_URL=https://86iruyzin2.execute-api.us-east-1.amazonaws.com
Environment=COGNITO_USER_POOL_ID=us-east-1_8KvqRmGSN
Environment=COGNITO_CLIENT_ID=4q5odh7hskaevkpphb4p8jgl3j
Environment=S3_BUCKET_RAW=dq-raw-108782054634

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable dqplatform
systemctl start dqplatform

echo "=== Deployment complete ==="
