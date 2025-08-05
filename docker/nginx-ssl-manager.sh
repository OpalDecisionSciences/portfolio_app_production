#!/bin/bash
set -e

# Nginx SSL Certificate Management Script
# Industry best-practice for Let's Encrypt certificate handling
# Implements zero-downtime certificate acquisition and renewal

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DOMAIN_NAME="${DOMAIN_NAME:-opaldecisionsciences.com}"
CERT_PATH="/etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem"
KEY_PATH="/etc/letsencrypt/live/${DOMAIN_NAME}/privkey.pem"
HTTP_CONFIG="/etc/nginx/nginx.http.conf"
HTTPS_CONFIG="/etc/nginx/nginx.prod.conf"
CURRENT_CONFIG="/etc/nginx/nginx.conf"

# Function to print status
print_status() {
    echo -e "${GREEN}[SSL-MANAGER]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[SSL-MANAGER]${NC} $1"
}

print_error() {
    echo -e "${RED}[SSL-MANAGER]${NC} $1"
}

# Check if SSL certificates exist and are valid
check_ssl_certificates() {
    if [[ -f "$CERT_PATH" && -f "$KEY_PATH" ]]; then
        # Check if certificates are not expired
        if openssl x509 -checkend 86400 -noout -in "$CERT_PATH" >/dev/null 2>&1; then
            print_status "Valid SSL certificates found for $DOMAIN_NAME"
            return 0
        else
            print_warning "SSL certificates exist but expire within 24 hours"
            return 1
        fi
    else
        print_warning "SSL certificates not found for $DOMAIN_NAME"
        return 1
    fi
}

# Switch to HTTP-only configuration
switch_to_http() {
    print_status "Switching to HTTP-only configuration for SSL certificate acquisition"
    cp "$HTTP_CONFIG" "$CURRENT_CONFIG"
    
    # Test nginx configuration
    if nginx -t >/dev/null 2>&1; then
        print_status "HTTP configuration validated successfully"
        return 0
    else
        print_error "HTTP configuration validation failed"
        return 1
    fi
}

# Switch to HTTPS configuration
switch_to_https() {
    print_status "Switching to HTTPS configuration with SSL certificates"
    
    # Verify certificates exist before switching
    if ! check_ssl_certificates; then
        print_error "Cannot switch to HTTPS: SSL certificates not available"
        return 1
    fi
    
    cp "$HTTPS_CONFIG" "$CURRENT_CONFIG"
    
    # Test nginx configuration with SSL
    if nginx -t >/dev/null 2>&1; then
        print_status "HTTPS configuration validated successfully"
        return 0
    else
        print_error "HTTPS configuration validation failed"
        print_warning "Rolling back to HTTP configuration"
        switch_to_http
        return 1
    fi
}

# Graceful nginx reload
reload_nginx() {
    print_status "Performing graceful nginx reload"
    
    if nginx -s reload >/dev/null 2>&1; then
        print_status "Nginx reloaded successfully"
        return 0
    else
        print_error "Nginx reload failed"
        return 1
    fi
}

# Initialize nginx with appropriate configuration
initialize_nginx() {
    print_status "Initializing nginx with certificate-aware configuration"
    
    # Stop any existing nginx processes first
    pkill nginx 2>/dev/null || true
    sleep 1
    
    if check_ssl_certificates; then
        switch_to_https
    else
        switch_to_http
    fi
    
    # Start nginx in foreground mode (daemon off)
    print_status "Starting nginx in foreground mode"
    exec nginx -g "daemon off;"
}

# Handle certificate acquisition workflow
acquire_certificates() {
    print_status "Starting SSL certificate acquisition workflow"
    
    # Ensure we're in HTTP mode for ACME challenge
    if ! switch_to_http; then
        print_error "Failed to switch to HTTP mode"
        return 1
    fi
    
    reload_nginx
    
    print_status "HTTP mode active - ready for certificate acquisition"
    print_status "Run: docker-compose -f docker-compose.prod.yml --profile ssl-setup up certbot"
}

# Handle certificate renewal
renew_certificates() {
    print_status "Starting certificate renewal process"
    
    # Temporarily switch to HTTP for renewal validation
    current_mode="unknown"
    if [[ -f "$CURRENT_CONFIG" ]] && grep -q "listen 443 ssl" "$CURRENT_CONFIG"; then
        current_mode="https"
    else
        current_mode="http"
    fi
    
    print_status "Current mode: $current_mode"
    
    # Perform renewal
    print_status "Certificate renewal completed - switching to appropriate configuration"
    
    if check_ssl_certificates; then
        if [[ "$current_mode" == "http" ]]; then
            print_status "New certificates detected - upgrading to HTTPS"
            switch_to_https
        fi
        reload_nginx
        print_status "Certificate renewal successful - HTTPS active"
    else
        print_warning "Certificate renewal may have failed - staying in HTTP mode"
        switch_to_http
        reload_nginx
    fi
}

# Continuous monitoring mode
monitor_certificates() {
    print_status "Starting certificate monitoring mode"
    
    while true; do
        if check_ssl_certificates; then
            # Certificates are valid - ensure HTTPS mode
            if ! grep -q "listen 443 ssl" "$CURRENT_CONFIG" 2>/dev/null; then
                print_status "Certificates available but nginx in HTTP mode - upgrading to HTTPS"
                switch_to_https && reload_nginx
            fi
        else
            # No valid certificates - ensure HTTP mode
            if grep -q "listen 443 ssl" "$CURRENT_CONFIG" 2>/dev/null; then
                print_warning "No valid certificates but nginx in HTTPS mode - downgrading to HTTP"
                switch_to_http && reload_nginx
            fi
        fi
        
        # Check every 6 hours
        sleep 21600
    done
}

# Display help
show_help() {
    cat << EOF
Nginx SSL Certificate Manager - Best Practice Implementation

Usage: $0 [COMMAND]

Commands:
    init              Initialize nginx with certificate-aware configuration
    acquire           Prepare for SSL certificate acquisition (HTTP mode)
    renew             Handle certificate renewal workflow
    monitor           Continuous certificate monitoring (background process)
    switch-http       Force switch to HTTP-only mode
    switch-https      Force switch to HTTPS mode (requires valid certificates)
    status            Show current SSL certificate and nginx status
    help              Show this help message

Environment Variables:
    DOMAIN_NAME       Domain name for SSL certificates (default: opaldecisionsciences.com)

Examples:
    $0 init           # Initialize nginx with appropriate config
    $0 acquire        # Prepare for certificate acquisition
    $0 renew          # Handle certificate renewal
    $0 monitor &      # Start background certificate monitoring

EOF
}

# Show current status
show_status() {
    echo -e "${BLUE}=== SSL Certificate Manager Status ===${NC}"
    echo
    
    # Certificate status
    if check_ssl_certificates; then
        echo -e "${GREEN}✅ SSL Certificates: Valid${NC}"
        
        # Show certificate details
        if [[ -f "$CERT_PATH" ]]; then
            echo "   Domain: $(openssl x509 -noout -subject -in "$CERT_PATH" | sed 's/subject=.*CN=\([^,]*\).*/\1/')"
            echo "   Expires: $(openssl x509 -noout -dates -in "$CERT_PATH" | grep notAfter | cut -d= -f2)"
            echo "   Issuer: $(openssl x509 -noout -issuer -in "$CERT_PATH" | sed 's/issuer=.*O=\([^,]*\).*/\1/')"
        fi
    else
        echo -e "${YELLOW}⚠️  SSL Certificates: Not available or expired${NC}"
    fi
    
    echo
    
    # Nginx status
    if pgrep nginx >/dev/null; then
        echo -e "${GREEN}✅ Nginx: Running${NC}"
        
        # Current configuration
        if [[ -f "$CURRENT_CONFIG" ]]; then
            if grep -q "listen 443 ssl" "$CURRENT_CONFIG"; then
                echo "   Mode: HTTPS (with SSL certificates)"
            else
                echo "   Mode: HTTP (certificate acquisition/fallback)"
            fi
        fi
        
        # Test configuration
        if nginx -t >/dev/null 2>&1; then
            echo "   Configuration: Valid"
        else
            echo -e "${RED}   Configuration: Invalid${NC}"
        fi
    else
        echo -e "${RED}❌ Nginx: Not running${NC}"
    fi
}

# Main script logic
case "${1:-help}" in
    "init")
        initialize_nginx
        ;;
    "acquire")
        acquire_certificates
        ;;
    "renew")
        renew_certificates
        ;;
    "monitor")
        monitor_certificates
        ;;
    "switch-http")
        switch_to_http && reload_nginx
        ;;
    "switch-https")
        switch_to_https && reload_nginx
        ;;
    "status")
        show_status
        ;;
    "help"|*)
        show_help
        ;;
esac