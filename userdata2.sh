#!/bin/bash
yum update -y
yum install -y nginx aws-cli
systemctl enable nginx

# Download frontend files
aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1 --exclude "nginx-spa.conf"

# Download and install nginx config with API reverse proxy
aws s3 cp s3://dq-frontend-108782054634/nginx-spa.conf /etc/nginx/conf.d/spa.conf --region us-east-1
rm -f /etc/nginx/conf.d/default.conf
rm -f /usr/share/nginx/html/nginx-spa.conf

# Start nginx
systemctl restart nginx

# Cron to sync frontend every 5 min
echo '*/5 * * * * root aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1 --exclude "nginx-spa.conf" && systemctl reload nginx' > /etc/cron.d/frontend-sync
