#!/bin/bash
yum update -y
yum install -y nginx aws-cli
systemctl enable nginx

# Pull frontend files from S3
aws s3 sync s3://dq-frontend-108782054634/ /usr/share/nginx/html/ --region us-east-1

# Remove default nginx server block to avoid conflict
rm -f /etc/nginx/conf.d/default.conf

# Configure Nginx for SPA routing
cat > /etc/nginx/conf.d/spa.conf << 'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    root /usr/share/nginx/html;
    index index.html;
    server_name _;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript;
    gzip_min_length 256;
}
EOF

# Start Nginx
systemctl restart nginx
