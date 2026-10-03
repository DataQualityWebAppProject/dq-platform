#!/bin/bash
yum update -y
yum install -y nginx aws-cli
systemctl enable nginx
aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1
rm -f /etc/nginx/conf.d/default.conf
cat > /etc/nginx/conf.d/spa.conf << 'EOF'
server {
    listen 80 default_server;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF
systemctl restart nginx
echo '*/5 * * * * root aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1' > /etc/cron.d/frontend-sync
