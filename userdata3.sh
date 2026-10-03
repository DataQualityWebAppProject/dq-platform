#!/bin/bash
yum update -y
yum install -y nginx aws-cli cronie
systemctl enable nginx
systemctl enable crond
systemctl start crond

# Download frontend files from S3
aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1 --exclude "nginx-spa.conf"

# Download nginx config with reverse proxy
aws s3 cp s3://dq-frontend-108782054634/nginx-spa.conf /etc/nginx/conf.d/spa.conf --region us-east-1
rm -f /etc/nginx/conf.d/default.conf
rm -f /usr/share/nginx/html/nginx-spa.conf

# Start nginx
systemctl start nginx

# Setup recurring sync every 2 minutes AND on reboot
cat > /etc/cron.d/frontend-sync << 'CRONEOF'
*/2 * * * * root aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1 --exclude "nginx-spa.conf" 2>/dev/null
@reboot root sleep 30 && aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1 --exclude "nginx-spa.conf" && systemctl restart nginx 2>/dev/null
CRONEOF
chmod 644 /etc/cron.d/frontend-sync
