# Django Portfolio Application Security Configuration
"""
Security utilities and validation functions for production deployment.
"""

import os
import secrets
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.postgresql.psycopg_any import IsolationLevel
from typing import Any, Optional


def get_env_variable(var_name: str, default: Optional[str] = None) -> str:
    """
    Get environment variable with proper error handling.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if variable is not set
        
    Returns:
        Environment variable value
        
    Raises:
        ImproperlyConfigured: If required variable is missing
    """
    try:
        return os.environ[var_name]
    except KeyError:
        if default is not None:
            return default
        error_msg = f"Set the {var_name} environment variable"
        raise ImproperlyConfigured(error_msg)


def get_env_bool(var_name: str, default: bool = False) -> bool:
    """
    Get boolean environment variable.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if variable is not set
        
    Returns:
        Boolean value
    """
    value = os.environ.get(var_name, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')


def get_env_list(var_name: str, default: Optional[list] = None) -> list:
    """
    Get list from comma-separated environment variable.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if variable is not set
        
    Returns:
        List of values
    """
    value = os.environ.get(var_name, '')
    if not value:
        return default or []
    return [item.strip() for item in value.split(',') if item.strip()]


def get_admin_allowed_ips() -> list:
    """
    Get admin allowed IPs from individual environment variables.
    Clean, simple approach following best practices.
    
    Returns:
        List of allowed IP addresses and networks
    """
    admin_ips = []
    
    # Individual IP variables with clear purposes
    user_ip = os.environ.get('ADMIN_USER_IP', '').strip()
    server_ip = os.environ.get('ADMIN_SERVER_IP', '').strip()
    docker_network = os.environ.get('ADMIN_DOCKER_NETWORK', '172.16.0.0/12').strip()
    localhost = os.environ.get('ADMIN_LOCALHOST', '127.0.0.1').strip()
    
    # Add non-empty IPs
    for ip in [user_ip, server_ip, docker_network, localhost]:
        if ip:
            admin_ips.append(ip)
    
    return admin_ips


def generate_secret_key() -> str:
    """
    Generate a cryptographically secure secret key.
    
    Returns:
        Random secret key suitable for Django
    """
    return secrets.token_urlsafe(50)


def validate_production_settings() -> list:
    """
    Validate that all required production settings are configured.
    
    Returns:
        List of validation errors
    """
    errors = []
    
    # Required environment variables for production
    required_vars = [
        'SECRET_KEY',
        'DATABASE_NAME',
        'DATABASE_USER', 
        'DATABASE_PASSWORD',
        'DATABASE_HOST',
        'OPENAI_API_KEY',
    ]
    
    for var in required_vars:
        try:
            value = get_env_variable(var)
            if not value or len(value.strip()) == 0:
                errors.append(f"Environment variable {var} is empty")
        except ImproperlyConfigured:
            errors.append(f"Required environment variable {var} is not set")
    
    # Validate SECRET_KEY length
    try:
        secret_key = get_env_variable('SECRET_KEY')
        if len(secret_key) < 50:
            errors.append("SECRET_KEY should be at least 50 characters long")
    except ImproperlyConfigured:
        pass  # Already caught above
    
    # Check DEBUG is disabled in production
    if get_env_bool('DEBUG', False):
        errors.append("DEBUG should be False in production")
    
    return errors


def get_allowed_hosts() -> list:
    """
    Get allowed hosts with proper defaults for development/production.
    
    Returns:
        List of allowed hosts
    """
    # Production hosts from environment
    production_hosts = get_env_list('ALLOWED_HOSTS')
    
    # Development defaults
    development_hosts = ['localhost', '127.0.0.1', '0.0.0.0', 'testserver']
    
    # If DEBUG is True, include development hosts
    if get_env_bool('DEBUG', False):
        return list(set(production_hosts + development_hosts))
    
    # Production mode - use specified hosts plus localhost for health checks
    if not production_hosts:
        raise ImproperlyConfigured(
            "ALLOWED_HOSTS environment variable must be set in production"
        )
    
    # Always include localhost and 127.0.0.1 for internal health checks in production
    internal_hosts = ['localhost', '127.0.0.1']
    return list(set(production_hosts + internal_hosts))


def get_cors_allowed_origins() -> list:
    """
    Get CORS allowed origins with proper defaults.
    
    Returns:
        List of allowed CORS origins
    """
    cors_origins = get_env_list('CORS_ALLOWED_ORIGINS')
    
    # Development defaults
    if get_env_bool('DEBUG', False):
        development_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000", 
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
        return list(set(cors_origins + development_origins))
    
    return cors_origins


def get_database_config() -> dict:
    """
    Get database configuration with psycopg3 async support and security best practices.
    
    Returns:
        Database configuration dictionary optimized for async Django
    """
    return {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',  # Django's native PostgreSQL backend with psycopg3
            'NAME': get_env_variable('DATABASE_NAME'),
            'USER': get_env_variable('DATABASE_USER'),
            'PASSWORD': get_env_variable('DATABASE_PASSWORD'),
            'HOST': get_env_variable('DATABASE_HOST'),
            'PORT': get_env_variable('DATABASE_PORT', '5432'),
            'OPTIONS': {
                'sslmode': get_env_variable('DATABASE_SSL_MODE', 'prefer'),
                # Pure async psycopg3 configuration - NO greenlet dependency
                'server_side_binding': True,  # Native async performance
                'prepare_threshold': None,  # Disable prepared statements for pure async
                'isolation_level': IsolationLevel.READ_COMMITTED,  # Django/psycopg3 standard isolation level
                # Native async connection tuning
                'keepalives_idle': 600,
                'keepalives_interval': 30,
                'keepalives_count': 3,
            },
            'CONN_MAX_AGE': 60,  # Connection pooling for performance
            'CONN_HEALTH_CHECKS': True,  # Health checks for connection reliability
            'ATOMIC_REQUESTS': True,  # Recommended for async Django
            # Enhanced configuration for async workers
            'TEST': {
                'NAME': 'test_' + get_env_variable('DATABASE_NAME'),
                'SERIALIZE': True,  # Better for async test isolation
            },
        }
    }


def get_security_middleware() -> list:
    """
    Get security middleware configuration.
    
    Returns:
        List of middleware classes in correct order
    """
    middleware = [
        'django.middleware.security.SecurityMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'corsheaders.middleware.CorsMiddleware',
        'django.middleware.common.CommonMiddleware', 
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
        'portfolio_project.middleware.SecurityHeadersMiddleware',
    ]
    
    # Add admin IP whitelist middleware if configured
    if get_admin_allowed_ips():
        middleware.insert(0, 'portfolio_project.middleware.AdminIPWhitelistMiddleware')
    
    return middleware


def get_production_security_settings() -> dict:
    """
    Get production security settings with HTTP-first support.
    
    Returns:
        Dictionary of security settings
    """
    # Check if SSL certificates exist (indicates HTTPS is ready)
    ssl_ready = (
        os.path.exists('/etc/letsencrypt/live/opaldecisionsciences.com/fullchain.pem') or
        get_env_bool('FORCE_HTTPS', False)
    )
    
    base_settings = {
        # Browser Security (always enabled)
        'SECURE_BROWSER_XSS_FILTER': True,
        'SECURE_CONTENT_TYPE_NOSNIFF': True,
        'SECURE_REFERRER_POLICY': 'strict-origin-when-cross-origin',
        'X_FRAME_OPTIONS': 'DENY',
        
        # Proxy header (always set for nginx)
        'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
    }
    
    if ssl_ready:
        # Full HTTPS security when certificates exist
        base_settings.update({
            # HTTPS Security
            'SECURE_HSTS_SECONDS': 31536000,  # 1 year
            'SECURE_HSTS_INCLUDE_SUBDOMAINS': True,
            'SECURE_HSTS_PRELOAD': True,
            'SECURE_SSL_REDIRECT': True,
            
            # Cookie Security
            'SESSION_COOKIE_SECURE': True,
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
            'CSRF_COOKIE_SECURE': True,
            'CSRF_COOKIE_HTTPONLY': True,
            'CSRF_COOKIE_SAMESITE': 'Lax',
        })
    else:
        # HTTP-first mode for SSL certificate generation
        base_settings.update({
            # No SSL redirect during certificate generation
            'SECURE_SSL_REDIRECT': False,
            
            # HTTP-compatible cookie settings
            'SESSION_COOKIE_SECURE': False,
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
            'CSRF_COOKIE_SECURE': False,
            'CSRF_COOKIE_HTTPONLY': True,
            'CSRF_COOKIE_SAMESITE': 'Lax',
        })
    
    return base_settings


def get_logging_config(log_level: str = 'INFO', base_dir=None) -> dict:
    """
    Get logging configuration for production.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        base_dir: Base directory path for log files
        
    Returns:
        Logging configuration dictionary
    """
    # Use project logs directory instead of system directory
    if base_dir:
        log_file = str(base_dir / 'logs' / 'django.log')
    else:
        # Fallback for development - use existing logs directory
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'django.log')
    
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
                'style': '{',
            },
            'simple': {
                'format': '{levelname} {message}',
                'style': '{',
            },
        },
        'handlers': {
            'file': {
                'level': log_level,
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': log_file,
                'maxBytes': 10 * 1024 * 1024,  # 10MB
                'backupCount': 5,
                'formatter': 'verbose',
            },
            'console': {
                'level': log_level,
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
            },
            'mail_admins': {
                'level': 'ERROR',
                'class': 'django.utils.log.AdminEmailHandler',
                'include_html': True,
            },
        },
        'root': {
            'handlers': ['console', 'file'],
            'level': log_level,
        },
        'loggers': {
            'django': {
                'handlers': ['console', 'file', 'mail_admins'],
                'level': log_level,
                'propagate': False,
            },
            'restaurants': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'accounts': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'api': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
        },
    }