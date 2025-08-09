"""
Custom middleware for the portfolio project.
Includes IP whitelisting for admin panel security.
"""
import logging
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
import ipaddress

logger = logging.getLogger(__name__)


class AdminIPWhitelistMiddleware(MiddlewareMixin):
    """
    Middleware to restrict admin panel access to whitelisted IP addresses.
    Provides protection against brute force attacks and unauthorized access.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)
        
        # Parse allowed IPs from settings
        self.allowed_ips = set()
        self.allowed_networks = []
        
        # Get IPs from environment variable (comma-separated)
        ip_whitelist = getattr(settings, 'ADMIN_ALLOWED_IPS', [])
        
        for ip_entry in ip_whitelist:
            ip_entry = ip_entry.strip()
            if not ip_entry:
                continue
                
            try:
                # Check if it's a network range (CIDR notation)
                if '/' in ip_entry:
                    network = ipaddress.ip_network(ip_entry, strict=False)
                    self.allowed_networks.append(network)
                    logger.info(f"Added admin network whitelist: {network}")
                else:
                    # Single IP address
                    ip = ipaddress.ip_address(ip_entry)
                    self.allowed_ips.add(str(ip))
                    logger.info(f"Added admin IP whitelist: {ip}")
            except ValueError as e:
                logger.error(f"Invalid IP address or network in ADMIN_ALLOWED_IPS: {ip_entry} - {e}")
        
        # Always allow localhost in development
        if settings.DEBUG:
            self.allowed_ips.update(['127.0.0.1', '::1'])
            logger.info("Added localhost to admin whitelist (DEBUG mode)")
    
    def process_request(self, request):
        """
        Check if the request is for the admin panel and validate IP.
        """
        # Only check admin URLs
        if not request.path.startswith('/admin/'):
            return None
        
        # Skip IP check if no whitelist is configured (but log a warning)
        if not self.allowed_ips and not self.allowed_networks:
            logger.warning("Admin panel accessed but no IP whitelist configured! This is a security risk.")
            if not settings.DEBUG:
                # In production, require at least one whitelisted IP
                logger.error("Admin access denied: No IP whitelist configured in production")
                return self.get_forbidden_response(request)
            return None
        
        # Get client IP address
        client_ip = self.get_client_ip(request)
        
        if not client_ip:
            logger.warning("Could not determine client IP address")
            return self.get_forbidden_response(request)
        
        # Check if IP is whitelisted
        if self.is_ip_allowed(client_ip):
            logger.info(f"Admin access granted for IP: {client_ip}")
            return None
        
        # IP not whitelisted
        logger.warning(f"Admin access denied for IP: {client_ip} - Path: {request.path}")
        return self.get_forbidden_response(request)
    
    def get_client_ip(self, request):
        """
        Get the client's IP address from the request.
        Handles proxy headers for production environments.
        """
        # Check for proxy headers (in order of preference)
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one
            client_ip = forwarded_for.split(',')[0].strip()
        elif request.META.get('HTTP_X_REAL_IP'):
            # Nginx sometimes uses X-Real-IP
            client_ip = request.META.get('HTTP_X_REAL_IP').strip()
        else:
            # Direct connection
            client_ip = request.META.get('REMOTE_ADDR', '').strip()
        
        # Validate IP address
        try:
            ipaddress.ip_address(client_ip)
            return client_ip
        except ValueError:
            logger.error(f"Invalid client IP address: {client_ip}")
            return None
    
    def is_ip_allowed(self, client_ip):
        """
        Check if the client IP is in the whitelist.
        """
        # Check exact IP match
        if client_ip in self.allowed_ips:
            return True
        
        # Check if IP is in any allowed network range
        try:
            client_ip_obj = ipaddress.ip_address(client_ip)
            for network in self.allowed_networks:
                if client_ip_obj in network:
                    return True
        except ValueError:
            logger.error(f"Invalid IP address format: {client_ip}")
        
        return False
    
    def get_forbidden_response(self, request):
        """
        Return a 403 Forbidden response for unauthorized admin access.
        """
        client_ip = self.get_client_ip(request)
        logger.warning(f"SECURITY: Unauthorized admin access attempt from IP: {client_ip}, Path: {request.path}, User-Agent: {request.META.get('HTTP_USER_AGENT', 'Unknown')}")
        
        # Don't reveal that this is an IP whitelist issue (security through obscurity)
        return HttpResponseForbidden(
            """
            <!DOCTYPE html>
            <html>
            <head>
                <title>403 Forbidden</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        text-align: center;
                        padding: 50px;
                        background-color: #f5f5f5;
                    }
                    h1 { color: #d9534f; }
                    p { color: #666; }
                </style>
            </head>
            <body>
                <h1>403 Forbidden</h1>
                <p>You don't have permission to access this resource.</p>
                <p>This incident has been logged.</p>
            </body>
            </html>
            """
        )


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Add security headers to all responses.
    """
    
    def process_response(self, request, response):
        """
        Add security headers to the response.
        """
        # Prevent clickjacking
        if not getattr(response, 'xframe_options_exempt', False):
            response['X-Frame-Options'] = 'DENY'
        
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS protection
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions policy (formerly Feature Policy)
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        return response