"""
Standardized error handling utilities for the restaurants app.
Provides consistent error logging, tracking, and response formatting.
"""
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, Union
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from functools import wraps

# Get the restaurants logger configured in security.py
logger = logging.getLogger('restaurants')


class ErrorTypes:
    """Standardized error type constants for consistent tracking."""
    API_ERROR = 'api_error'
    DATABASE_ERROR = 'database_error'
    VALIDATION_ERROR = 'validation_error'
    EXTERNAL_API_ERROR = 'external_api_error'
    SCRAPING_ERROR = 'scraping_error'
    PROCESSING_ERROR = 'processing_error'
    AUTHENTICATION_ERROR = 'authentication_error'
    PERMISSION_ERROR = 'permission_error'
    NOT_FOUND_ERROR = 'not_found_error'
    CONFIGURATION_ERROR = 'configuration_error'
    NETWORK_ERROR = 'network_error'
    TIMEOUT_ERROR = 'timeout_error'


def log_error(error: Exception, 
              error_type: str = ErrorTypes.API_ERROR,
              context: Optional[Dict[str, Any]] = None,
              restaurant=None) -> str:
    """
    Standardized error logging with restaurant-level tracking.
    
    Args:
        error: The exception that occurred
        error_type: Type of error from ErrorTypes constants
        context: Additional context information
        restaurant: Restaurant instance for error tracking
        
    Returns:
        Error ID for tracking/reference
    """
    error_id = f"{error_type}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    # Build error message
    error_msg = str(error)
    context_info = ""
    if context:
        context_info = f" Context: {context}"
    
    # Log the error with full details
    logger.error(
        f"[{error_id}] {error_type.upper()}: {error_msg}{context_info}",
        extra={
            'error_id': error_id,
            'error_type': error_type,
            'context': context or {},
            'restaurant_id': restaurant.id if restaurant else None,
            'traceback': traceback.format_exc()
        }
    )
    
    # Track error on restaurant if provided
    if restaurant:
        try:
            restaurant.log_processing_error(
                error_type=error_type,
                error_message=f"{error_msg} (ID: {error_id})",
                save_to_db=True
            )
        except Exception as tracking_error:
            logger.warning(f"Failed to track error on restaurant {restaurant.id}: {tracking_error}")
    
    return error_id


def create_error_response(error: Exception,
                         error_type: str = ErrorTypes.API_ERROR,
                         status_code: int = 500,
                         context: Optional[Dict[str, Any]] = None,
                         restaurant=None,
                         include_details: bool = False) -> JsonResponse:
    """
    Create standardized JSON error response.
    
    Args:
        error: The exception that occurred
        error_type: Type of error from ErrorTypes constants
        status_code: HTTP status code
        context: Additional context information
        restaurant: Restaurant instance for error tracking
        include_details: Whether to include error details in response
        
    Returns:
        JsonResponse with standardized error format
    """
    error_id = log_error(error, error_type, context, restaurant)
    
    response_data = {
        'error': True,
        'error_type': error_type,
        'error_id': error_id,
        'message': 'An error occurred while processing your request',
        'timestamp': datetime.now().isoformat()
    }
    
    if include_details:
        response_data['details'] = str(error)
    
    return JsonResponse(response_data, status=status_code)


def handle_view_errors(error_type: str = ErrorTypes.API_ERROR,
                      default_status: int = 500,
                      include_details: bool = False):
    """
    Decorator for consistent view error handling.
    
    Args:
        error_type: Type of error from ErrorTypes constants
        default_status: Default HTTP status code
        include_details: Whether to include error details in response
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            try:
                return view_func(*args, **kwargs)
            except ValidationError as e:
                return create_error_response(
                    e, ErrorTypes.VALIDATION_ERROR, 400, include_details=include_details
                )
            except IntegrityError as e:
                return create_error_response(
                    e, ErrorTypes.DATABASE_ERROR, 400, include_details=include_details
                )
            except Exception as e:
                return create_error_response(
                    e, error_type, default_status, include_details=include_details
                )
        return wrapper
    return decorator


def safe_execute(operation,
                error_type: str = ErrorTypes.PROCESSING_ERROR,
                default_return=None,
                restaurant=None,
                context: Optional[Dict[str, Any]] = None,
                raise_on_error: bool = False):
    """
    Safely execute an operation with consistent error handling.
    
    Args:
        operation: Callable to execute
        error_type: Type of error from ErrorTypes constants
        default_return: Value to return on error
        restaurant: Restaurant instance for error tracking
        context: Additional context information
        raise_on_error: Whether to re-raise the exception
        
    Returns:
        Operation result or default_return on error
    """
    try:
        return operation()
    except Exception as e:
        log_error(e, error_type, context, restaurant)
        if raise_on_error:
            raise
        return default_return


def log_warning_with_context(message: str, 
                           context: Optional[Dict[str, Any]] = None,
                           restaurant=None):
    """
    Log warning with consistent context formatting.
    
    Args:
        message: Warning message
        context: Additional context information
        restaurant: Restaurant instance for context
    """
    context_info = ""
    if context:
        context_info = f" Context: {context}"
    
    logger.warning(
        f"{message}{context_info}",
        extra={
            'context': context or {},
            'restaurant_id': restaurant.id if restaurant else None
        }
    )


def log_info_with_context(message: str,
                         context: Optional[Dict[str, Any]] = None,
                         restaurant=None):
    """
    Log info with consistent context formatting.
    
    Args:
        message: Info message
        context: Additional context information
        restaurant: Restaurant instance for context
    """
    context_info = ""
    if context:
        context_info = f" Context: {context}"
    
    logger.info(
        f"{message}{context_info}",
        extra={
            'context': context or {},
            'restaurant_id': restaurant.id if restaurant else None
        }
    )


class ErrorContext:
    """Context manager for error handling with automatic restaurant tracking."""
    
    def __init__(self, operation_name: str, restaurant=None, error_type: str = ErrorTypes.PROCESSING_ERROR):
        self.operation_name = operation_name
        self.restaurant = restaurant
        self.error_type = error_type
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            log_error(
                exc_val,
                self.error_type,
                context={'operation': self.operation_name},
                restaurant=self.restaurant
            )
        return False  # Don't suppress exceptions