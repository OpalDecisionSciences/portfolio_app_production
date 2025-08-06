#!/bin/bash

# AWS EC2 Production Deployment Script for Portfolio App Production
# Complete deployment with SSL automation
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
EC2_IP="34.233.24.183"
KEY_FILE="~/.ssh/opal-decision-sciences-prod-kp.pem"
EC2_USER="ubuntu"
APP_DIR="/home/ubuntu/portfolio_app_production"
DOMAIN_NAME="opaldecisionsciences.com"
EMAIL="opaldecisionsciences@gmail.com"

echo -e "${BLUE}🚀 Deploying Portfolio App Production to AWS EC2...${NC}"
echo -e "${YELLOW}Domain: $DOMAIN_NAME${NC}"
echo -e "${YELLOW}Email: $EMAIL${NC}"

# Function to print status
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 1. Copy application files to EC2
print_status "📁 Copying application files..."
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='*.pyc' \
    -e "ssh -i $KEY_FILE -o StrictHostKeyChecking=no" \
    ./ $EC2_USER@$EC2_IP:$APP_DIR/

# 2. Run setup commands on EC2
print_status "⚙️ Setting up application on EC2..."
ssh -i $KEY_FILE -o StrictHostKeyChecking=no $EC2_USER@$EC2_IP << EOF
    set -e
    
    # Colors for remote output
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
    
    print_status() {
        echo -e "\${GREEN}[INFO]\${NC} \$1"
    }
    
    print_warning() {
        echo -e "\${YELLOW}[WARNING]\${NC} \$1"
    }
    
    print_error() {
        echo -e "\${RED}[ERROR]\${NC} \$1"
    }
    
    # Update system
    print_status "Updating system packages..."
    sudo apt update && sudo apt upgrade -y
    
    # Install Docker if not present
    if ! command -v docker &> /dev/null; then
        print_status "Installing Docker..."
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker ubuntu
        rm get-docker.sh
    fi
    
    # Install Docker Compose if not present
    if ! command -v docker-compose &> /dev/null; then
        print_status "Installing Docker Compose..."
        sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-\$(uname -s)-\$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi
    
    # Navigate to app directory
    cd $APP_DIR
    
    # Create necessary directories
    print_status "Creating directories..."
    mkdir -p logs ssl ssl-challenges production_logs/nginx
    
    # Set permissions
    sudo chown -R ubuntu:ubuntu $APP_DIR
    
    # Install system monitoring tools
    print_status "Installing system monitoring..."
    sudo apt-get install -y htop iotop nethogs curl
    
    # Set up UFW firewall
    print_status "Configuring firewall..."
    sudo ufw --force enable
    sudo ufw allow ssh
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    
    # Build and start services (HTTP first for SSL verification)
    print_status "Building Docker images..."
    docker-compose -f docker-compose.prod.yml build
    
    print_status "Starting services..."
    docker-compose -f docker-compose.prod.yml up -d
    
    # Wait for services to be ready
    print_status "Waiting for services to start..."
    sleep 30
    
    # Check if services are running
    print_status "Checking service health..."
    docker-compose -f docker-compose.prod.yml ps
    
    # Industry Best-Practice SSL Certificate Setup
    print_status "Setting up SSL certificates using best practices..."
    
    # Set environment variables for certificate acquisition
    export DOMAIN_NAME=$DOMAIN_NAME
    export ACME_EMAIL=$EMAIL
    
    # Phase 1: Verify HTTP deployment is working
    print_status "Phase 1: Verifying HTTP deployment..."
    sleep 10  # Allow services to fully start
    
    if curl -f -s http://$DOMAIN_NAME/health/ > /dev/null; then
        print_status "✅ HTTP deployment verified - ready for SSL certificate acquisition"
    else
        print_warning "⚠️ HTTP health check failed - continuing with SSL setup"
    fi
    
    # Phase 2: Acquire production SSL certificates
    print_status "Phase 2: Acquiring production SSL certificates..."
    print_status "Using industry-standard HTTP-01 challenge method"
    
    docker-compose -f docker-compose.prod.yml --profile ssl-setup up certbot
    
    # Phase 3: Automatic upgrade to HTTPS
    print_status "Phase 3: Automatic upgrade to HTTPS mode..."
    sleep 5
    
    # The nginx-ssl-manager automatically detects new certificates and switches to HTTPS
    print_status "Certificate detection and HTTPS upgrade handled automatically"
    
    # Verify HTTPS is working
    print_status "Verifying HTTPS deployment..."
    sleep 10
    
    if curl -f -s https://$DOMAIN_NAME/health/ > /dev/null; then
        print_status "✅ HTTPS deployment successful!"
    elif curl -f -s http://$DOMAIN_NAME/health/ > /dev/null; then
        print_warning "⚠️ HTTP working but HTTPS may need time to activate"
    else
        print_error "❌ Health check failed on both HTTP and HTTPS"
    fi
    
    # Set up SSL certificate auto-renewal
    print_status "Setting up SSL certificate auto-renewal..."
    sudo tee /etc/cron.d/certbot-renewal > /dev/null <<CRONEOF
0 12 * * * root cd $APP_DIR && docker-compose -f docker-compose.prod.yml run --rm certbot renew --quiet && docker-compose -f docker-compose.prod.yml exec nginx nginx -s reload
CRONEOF
    
    # Set up database backups
    print_status "Setting up database backups..."
    mkdir -p backups
    
    sudo tee /etc/cron.d/portfolio-backup > /dev/null <<CRONEOF
0 2 * * * root cd $APP_DIR && docker-compose -f docker-compose.prod.yml exec -T db pg_dump -U \\\$POSTGRES_USER \\\$POSTGRES_DB > backups/backup_\\\$(date +\\%Y\\%m\\%d_\\%H\\%M\\%S).sql
0 3 * * 0 root find $APP_DIR/backups -name "*.sql" -type f -mtime +30 -delete
CRONEOF
    
    # Set up log rotation
    print_status "Setting up log rotation..."
    sudo tee /etc/logrotate.d/portfolio-app > /dev/null <<LOGEOF
$APP_DIR/logs/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    create 644 ubuntu ubuntu
    postrotate
        docker-compose -f $APP_DIR/docker-compose.prod.yml exec nginx nginx -s reload
    endscript
}
LOGEOF
    
    # Final health check
    print_status "Performing final health check..."
    sleep 10
    
    # Check HTTPS
    if curl -f -s https://$DOMAIN_NAME/health/ > /dev/null; then
        print_status "✅ HTTPS Application is running successfully!"
    elif curl -f -s http://$DOMAIN_NAME/health/ > /dev/null; then
        print_warning "⚠️ HTTP Application is running (SSL may need time to propagate)"
    else
        print_error "❌ Health check failed. Check logs with: docker-compose -f docker-compose.prod.yml logs"
    fi
    
    print_status "🎉 Deployment completed!"
EOF

echo -e "${GREEN}=== Deployment Complete! ===${NC}"
echo -e "${YELLOW}Next steps:${NC}"
echo -e "${YELLOW}1. Your application should be accessible at: https://$DOMAIN_NAME${NC}"
echo -e "${YELLOW}2. Admin panel: https://$DOMAIN_NAME/admin/${NC}"
echo -e "${YELLOW}3. Monitor logs: ssh -i $KEY_FILE $EC2_USER@$EC2_IP 'cd $APP_DIR && docker-compose -f docker-compose.prod.yml logs -f'${NC}"
echo -e "${YELLOW}4. Check service status: ssh -i $KEY_FILE $EC2_USER@$EC2_IP 'cd $APP_DIR && docker-compose -f docker-compose.prod.yml ps'${NC}"

print_warning "Important:"
echo "- SSL certificates are automatically renewed"
echo "- Database backups run daily at 2 AM"
echo "- Log rotation is configured"
echo "- Firewall is configured for HTTP/HTTPS/SSH only"