#!/bin/bash

# Quick App Update Script for EC2
# Use this after initial deployment to push updates

set -e

# Configuration
EC2_IP="34.233.24.183"
KEY_FILE="~/.ssh/opal-decision-sciences-prod-kp.pem"
EC2_USER="ubuntu"
APP_DIR="/home/ubuntu/portfolio_app_production"

echo "🔄 Updating Opal Decision Sciences app..."

# 1. Sync only changed files (fast)
echo "📁 Syncing changes..."
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='*.pyc' \
    --exclude='logs/' --exclude='ssl/' \
    -e "ssh -i $KEY_FILE -o StrictHostKeyChecking=no" \
    ./ $EC2_USER@$EC2_IP:$APP_DIR/

# 2. Restart services
echo "🔄 Restarting services..."
ssh -i $KEY_FILE -o StrictHostKeyChecking=no $EC2_USER@$EC2_IP << EOF
    cd $APP_DIR
    docker-compose -f docker-compose.prod.yml down
    docker-compose -f docker-compose.prod.yml up -d
    echo "✅ App updated successfully!"
EOF

echo "🎉 Update complete! Check: https://www.opaldecisionsciences.com"
