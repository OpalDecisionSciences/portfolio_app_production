"""
Error handling utilities for data pipeline scrapers.
Provides Django-compatible error tracking that integrates with Restaurant model.
"""
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, Union
import os
import sys
from pathlib import Path

# Setup Django environment
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['django', 'data_pipeline'])

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

try:
    import django
    django.setup()
    from django.db import transaction
    from restaurants.models import Restaurant, ScrapingJob, ImageScrapingJob
    DJANGO_AVAILABLE = True
except ImportError as e:
    print(f"Django not available for scraper error tracking: {e}")
    DJANGO_AVAILABLE = False

# Configure logger for scrapers
logger = logging.getLogger('scrapers')


class ScraperErrorTypes:
    """Error types specific to scraping operations."""
    SCRAPING_ERROR = 'scraping_error'
    PARSING_ERROR = 'parsing_error'
    NETWORK_ERROR = 'network_error'
    SELENIUM_ERROR = 'selenium_error'
    LLM_ERROR = 'llm_error'
    IMAGE_PROCESSING_ERROR = 'image_processing_error'
    DATABASE_ERROR = 'database_error'
    VALIDATION_ERROR = 'validation_error'
    TIMEOUT_ERROR = 'timeout_error'
    AUTHENTICATION_ERROR = 'authentication_error'


def log_scraper_error(error: Exception,
                     error_type: str = ScraperErrorTypes.SCRAPING_ERROR,
                     context: Optional[Dict[str, Any]] = None,
                     restaurant_name: str = None,
                     restaurant_url: str = None,
                     scraping_job_id: str = None,
                     save_to_db: bool = True) -> str:
    """
    Log scraping error with restaurant and job tracking.
    
    Args:
        error: The exception that occurred
        error_type: Type of error from ScraperErrorTypes
        context: Additional context information
        restaurant_name: Name of restaurant being scraped
        restaurant_url: URL being scraped
        scraping_job_id: ID of the scraping job
        save_to_db: Whether to save error to database
        
    Returns:
        Error ID for tracking
    """
    error_id = f"{error_type}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    # Build comprehensive error message
    error_msg = str(error)
    context_info = ""
    if context:
        context_info = f" Context: {context}"
    
    # Log the error with full details
    logger.error(
        f"[{error_id}] SCRAPER {error_type.upper()}: {error_msg}{context_info}",
        extra={
            'error_id': error_id,
            'error_type': error_type,
            'context': context or {},
            'restaurant_name': restaurant_name,
            'restaurant_url': restaurant_url,
            'scraping_job_id': scraping_job_id,
            'traceback': traceback.format_exc()
        }
    )
    
    # Save to database if Django is available and requested
    if DJANGO_AVAILABLE and save_to_db:
        try:
            # Try to find and update restaurant
            restaurant = None
            if restaurant_name:
                try:
                    restaurant = Restaurant.objects.filter(
                        name__icontains=restaurant_name
                    ).first()
                except Exception:
                    pass
            
            # Update restaurant error tracking
            if restaurant:
                restaurant.log_processing_error(
                    error_type=error_type,
                    error_message=f"{error_msg} (ID: {error_id})",
                    save_to_db=True
                )
            
            # Update scraping job if available
            if scraping_job_id:
                try:
                    scraping_job = ScrapingJob.objects.filter(id=scraping_job_id).first()
                    if scraping_job:
                        scraping_job.status = 'failed'
                        scraping_job.error_message = f"{error_msg} (ID: {error_id})"
                        scraping_job.save()
                except Exception as job_error:
                    logger.warning(f"Failed to update scraping job {scraping_job_id}: {job_error}")
                    
        except Exception as db_error:
            logger.warning(f"Failed to save error to database: {db_error}")
    
    return error_id


def safe_scrape_operation(operation,
                         error_type: str = ScraperErrorTypes.SCRAPING_ERROR,
                         default_return=None,
                         restaurant_name: str = None,
                         restaurant_url: str = None,
                         context: Optional[Dict[str, Any]] = None,
                         raise_on_error: bool = False):
    """
    Safely execute a scraping operation with consistent error handling.
    
    Args:
        operation: Callable to execute
        error_type: Type of error from ScraperErrorTypes
        default_return: Value to return on error
        restaurant_name: Name of restaurant being scraped
        restaurant_url: URL being scraped
        context: Additional context information
        raise_on_error: Whether to re-raise the exception
        
    Returns:
        Operation result or default_return on error
    """
    try:
        return operation()
    except Exception as e:
        log_scraper_error(
            e, 
            error_type, 
            context, 
            restaurant_name, 
            restaurant_url
        )
        if raise_on_error:
            raise
        return default_return


def create_scraping_job_with_error_tracking(restaurant_name: str,
                                          url: str,
                                          job_type: str = 'unified_scraper') -> Optional[str]:
    """
    Create a scraping job with error tracking enabled.
    
    Args:
        restaurant_name: Name of restaurant
        url: URL being scraped
        job_type: Type of scraping job
        
    Returns:
        Scraping job ID if successful, None otherwise
    """
    if not DJANGO_AVAILABLE:
        return None
        
    try:
        with transaction.atomic():
            scraping_job = ScrapingJob.objects.create(
                restaurant_name=restaurant_name,
                url=url,
                job_type=job_type,
                status='in_progress',
                started_at=datetime.now()
            )
            return str(scraping_job.id)
    except Exception as e:
        logger.warning(f"Failed to create scraping job: {e}")
        return None


def complete_scraping_job(job_id: str, 
                         success: bool = True, 
                         error_message: str = None,
                         scraped_data: Dict[str, Any] = None):
    """
    Mark scraping job as complete.
    
    Args:
        job_id: Scraping job ID
        success: Whether the job completed successfully
        error_message: Error message if job failed
        scraped_data: Summary of scraped data
    """
    if not DJANGO_AVAILABLE or not job_id:
        return
        
    try:
        scraping_job = ScrapingJob.objects.get(id=job_id)
        scraping_job.status = 'completed' if success else 'failed'
        scraping_job.completed_at = datetime.now()
        
        if error_message:
            scraping_job.error_message = error_message
            
        if scraped_data:
            # Store summary of what was scraped
            scraping_job.scraped_content = {
                'summary': scraped_data,
                'scraped_at': datetime.now().isoformat()
            }
            
        scraping_job.save()
        logger.info(f"Scraping job {job_id} marked as {'completed' if success else 'failed'}")
        
    except Exception as e:
        logger.warning(f"Failed to update scraping job {job_id}: {e}")


def log_scraper_warning(message: str,
                       context: Optional[Dict[str, Any]] = None,
                       restaurant_name: str = None,
                       restaurant_url: str = None):
    """
    Log warning with scraper context.
    
    Args:
        message: Warning message
        context: Additional context
        restaurant_name: Name of restaurant
        restaurant_url: URL being scraped
    """
    context_info = ""
    if context:
        context_info = f" Context: {context}"
        
    logger.warning(
        f"SCRAPER WARNING: {message}{context_info}",
        extra={
            'context': context or {},
            'restaurant_name': restaurant_name,
            'restaurant_url': restaurant_url
        }
    )


def log_scraper_info(message: str,
                    context: Optional[Dict[str, Any]] = None,
                    restaurant_name: str = None,
                    restaurant_url: str = None):
    """
    Log info with scraper context.
    
    Args:
        message: Info message
        context: Additional context
        restaurant_name: Name of restaurant
        restaurant_url: URL being scraped
    """
    context_info = ""
    if context:
        context_info = f" Context: {context}"
        
    logger.info(
        f"SCRAPER: {message}{context_info}",
        extra={
            'context': context or {},
            'restaurant_name': restaurant_name,
            'restaurant_url': restaurant_url
        }
    )


class ScrapingErrorContext:
    """Context manager for scraping operations with automatic error tracking."""
    
    def __init__(self, 
                 operation_name: str,
                 restaurant_name: str = None,
                 restaurant_url: str = None,
                 error_type: str = ScraperErrorTypes.SCRAPING_ERROR,
                 job_id: str = None):
        self.operation_name = operation_name
        self.restaurant_name = restaurant_name
        self.restaurant_url = restaurant_url
        self.error_type = error_type
        self.job_id = job_id
    
    def __enter__(self):
        log_scraper_info(
            f"Starting {self.operation_name}",
            restaurant_name=self.restaurant_name,
            restaurant_url=self.restaurant_url
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            log_scraper_error(
                exc_val,
                self.error_type,
                context={'operation': self.operation_name},
                restaurant_name=self.restaurant_name,
                restaurant_url=self.restaurant_url,
                scraping_job_id=self.job_id
            )
        else:
            log_scraper_info(
                f"Completed {self.operation_name}",
                restaurant_name=self.restaurant_name,
                restaurant_url=self.restaurant_url
            )
        return False  # Don't suppress exceptions