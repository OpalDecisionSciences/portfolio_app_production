# Django Settings for Portfolio Application
import os
from pathlib import Path
from dotenv import load_dotenv
from decouple import config
import warnings

# Set up Python paths for shared modules
from . import path_setup

# Suppress common setuptools/distutils compatibility warnings
warnings.filterwarnings("ignore", message=".*Setuptools is replacing distutils.*")
warnings.filterwarnings("ignore", message=".*Distutils was imported before Setuptools.*")

# Import security utilities
from .security import (
    get_env_variable, 
    get_env_bool, 
    get_env_list,
    get_admin_allowed_ips,
    get_allowed_hosts,
    get_cors_allowed_origins,
    get_database_config,
    get_security_middleware,
    get_production_security_settings,
    get_logging_config,
    validate_production_settings
)

# Import constants for consistency
from .constants import *

# Load environment variables
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Validate production settings if not in debug mode
if not get_env_bool('DEBUG', False):
    validation_errors = validate_production_settings()
    if validation_errors:
        raise Exception(f"Production configuration errors: {', '.join(validation_errors)}")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = get_env_variable('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = get_env_bool('DEBUG', False)

ALLOWED_HOSTS = get_allowed_hosts()

# Admin Panel IP Whitelist Configuration
# Admin panel IP whitelist - supports both combined and individual environment variables
# Examples: "192.168.1.1,10.0.0.0/24,2001:db8::/32"
ADMIN_ALLOWED_IPS = get_admin_allowed_ips()

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'django_filters',
    'django_extensions',
    'django_celery_beat',
    'storages',
    
    # Native async Django components
    'channels',
    
    # Local apps
    'restaurants',
    'accounts',
    'chat',
    'api',
]

MIDDLEWARE = get_security_middleware()

ROOT_URLCONF = 'portfolio_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'portfolio_project.wsgi.application'

# ASGI Application for native async Django support
ASGI_APPLICATION = 'portfolio_project.asgi.application'

# Channel Layer Configuration for native async Redis
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [(get_env_variable('REDIS_HOST', 'redis'), get_env_variable('REDIS_PORT', 6379))],
            'symmetric_encryption_keys': [SECRET_KEY],
        },
    },
}

# Database
DATABASES = get_database_config()

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# AWS S3 Configuration - Production Only
# Static and Media files stored on S3 for production deployment
AWS_ACCESS_KEY_ID = get_env_variable('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = get_env_variable('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = get_env_variable('AWS_STORAGE_BUCKET_NAME')
AWS_MEDIA_BUCKET_NAME = get_env_variable('AWS_MEDIA_BUCKET_NAME')
AWS_S3_REGION_NAME = get_env_variable('AWS_S3_REGION_NAME', 'us-east-1')
AWS_S3_CUSTOM_DOMAIN = get_env_variable('AWS_S3_CUSTOM_DOMAIN', f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com')

# S3 Static files settings
AWS_LOCATION = 'static'
AWS_DEFAULT_ACL = 'public-read'
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',  # 1 day cache
}

# Static files configuration for S3
STATICFILES_STORAGE = 'storages.backends.s3boto3.S3StaticStorage'
STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_LOCATION}/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# S3 Media files settings
AWS_MEDIA_LOCATION = 'media'
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
MEDIA_URL = f'https://{AWS_MEDIA_BUCKET_NAME}.s3.amazonaws.com/{AWS_MEDIA_LOCATION}/'

print(f"[S3 STATIC] Using S3 bucket: {AWS_STORAGE_BUCKET_NAME}")
print(f"[S3 STATIC] Static URL: {STATIC_URL}")
print(f"[S3 MEDIA] Using S3 bucket: {AWS_MEDIA_BUCKET_NAME}") 
print(f"[S3 MEDIA] Media URL: {MEDIA_URL}")

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

# CORS settings
CORS_ALLOWED_ORIGINS = get_cors_allowed_origins()

# Logging configuration
LOGGING = get_logging_config(base_dir=BASE_DIR)

# Create logs directory if it doesn't exist
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# OpenAI Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Google Maps API Configuration
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

# OpenWeather API Configuration
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')

# RAG Service Configuration
RAG_SERVICE_URL = os.getenv('RAG_SERVICE_URL', 'http://localhost:8001')

# Redis Configuration (for chat sessions)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Consolidated Cache Configuration
# Multi-tier caching strategy:
# - DB 0: Django default cache (sessions, view fragments, templates)
# - DB 1: Weather API cache (managed separately) 
# - DB 2: Unified search cache primary (handled by UnifiedCacheManager)
# - DB 3: Unified search cache secondary (handled by UnifiedCacheManager)
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,  # Uses DB 0
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            },
            'PARSER_CLASS': 'redis.connection.HiredisParser',
            'PICKLE_VERSION': -1,
        },
        'KEY_PREFIX': 'portfolio_django',
        'TIMEOUT': CACHE_TIMEOUT_MEDIUM,  # Default 1 hour
    },
    'session': {
        'BACKEND': 'django_redis.cache.RedisCache', 
        'LOCATION': REDIS_URL,  # Uses DB 0
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'portfolio_session',
        'TIMEOUT': 86400,  # 24 hours for session data
    }
}

# Cache middleware settings for view caching
CACHE_MIDDLEWARE_ALIAS = 'default'
CACHE_MIDDLEWARE_SECONDS = CACHE_TIMEOUT_MEDIUM
CACHE_MIDDLEWARE_KEY_PREFIX = 'portfolio_middleware'

# Session engine configuration to use Redis
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'session'
SESSION_COOKIE_AGE = 86400  # 24 hours

# Celery Configuration (for background tasks)
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Celery configuration settings
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True

# Task routing configuration
CELERY_TASK_ROUTES = {
    'restaurants.tasks.update_restaurant_embeddings': {'queue': 'embeddings'},
    'restaurants.tasks.process_image_ai_categorization': {'queue': 'ai_processing'},
    'restaurants.tasks.scrape_restaurant_images_task': {'queue': 'scraping'},
    'restaurants.tasks.cleanup_old_images': {'queue': 'maintenance'},
}

# Task execution settings
CELERY_TASK_SOFT_TIME_LIMIT = 300  # 5 minutes
CELERY_TASK_TIME_LIMIT = 600  # 10 minutes
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Result backend settings
CELERY_RESULT_EXPIRES = 3600  # 1 hour
CELERY_TASK_IGNORE_RESULT = False

# Redis broker settings
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 10

# Beat scheduler configuration for periodic tasks
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Clean up old failed images every day at 2 AM
    'cleanup-old-images': {
        'task': 'restaurants.tasks.cleanup_old_images',
        'schedule': crontab(hour=2, minute=0),
        'kwargs': {'days_old': 90},
        'options': {'queue': 'maintenance'}
    },
    
    # Process pending AI image categorization every 4 hours
    'process-pending-ai-images': {
        'task': 'restaurants.tasks.batch_process_pending_images',
        'schedule': crontab(minute=0, hour='*/4'),
        'options': {'queue': 'ai_processing'}
    },
    
    # Update embeddings for recently modified restaurants every 6 hours
    'update-recent-embeddings': {
        'task': 'restaurants.tasks.batch_update_recent_embeddings',
        'schedule': crontab(minute=30, hour='*/6'),
        'options': {'queue': 'embeddings'}
    },
    
    # Cache warming for popular restaurants every hour
    'warm-restaurant-cache': {
        'task': 'restaurants.tasks.warm_popular_restaurant_cache',
        'schedule': crontab(minute=15, hour='*'),
        'options': {'queue': 'maintenance'}
    },
    
    # Health check for all background services every 30 minutes
    'system-health-check': {
        'task': 'restaurants.tasks.system_health_check',
        'schedule': crontab(minute='*/30'),
        'options': {'queue': 'maintenance'}
    },
}

# Custom settings
PORTFOLIO_DATA_DIR = BASE_DIR / 'data'
PORTFOLIO_SCRAPING_BATCH_SIZE = 10
PORTFOLIO_TOKEN_MANAGEMENT_DIR = BASE_DIR / 'token_management'

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Chat Safety Settings
CHAT_MAX_MESSAGE_LENGTH = 1000
CHAT_RATE_LIMIT_MESSAGES = 20
CHAT_RATE_LIMIT_WINDOW = 60  # seconds

# Email Configuration for Password Reset
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Opal Decision Sciences <noreply@opaldecisionsciences.com>')

# Account Settings
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_EMAIL_REQUIRED = True

# Create necessary directories
os.makedirs(PORTFOLIO_DATA_DIR, exist_ok=True)
os.makedirs(PORTFOLIO_TOKEN_MANAGEMENT_DIR, exist_ok=True)

# Production Security Settings
# Apply security settings if not in debug mode
if not DEBUG:
    security_settings = get_production_security_settings()
    for key, value in security_settings.items():
        globals()[key] = value

# Additional Security Settings for Production
# Admin security
ADMIN_URL = get_env_variable('ADMIN_URL', 'admin')  # Custom admin URL

# Rate limiting configuration
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'