"""
Essential Celery tasks for the restaurants app.
Streamlined for production use - unused tasks moved to tasks_backup.py
"""
from celery import shared_task
from django.utils import timezone
from django.conf import settings
import sys
import os
from pathlib import Path
import logging
import json

from path_manager import setup_portfolio_paths
setup_portfolio_paths()
from scrapers.image_scraper import RestaurantImageScraper
from services.image_ai_service import get_image_ai_service

from .models import Restaurant, RestaurantImage

logger = logging.getLogger(__name__)


@shared_task
def update_restaurant_embeddings(restaurant_id):
    """
    Update embeddings for a restaurant in the RAG service.
    
    Args:
        restaurant_id: UUID of the restaurant
    """
    try:
        import requests
        rag_service_url = getattr(settings, 'RAG_SERVICE_URL', 'http://rag:8001')
        
        restaurant = Restaurant.objects.get(id=restaurant_id)
        
        # Generate embeddings for restaurant content
        content = f"""
        {restaurant.name}
        {restaurant.description or ''}
        {restaurant.city}, {restaurant.country}
        Cuisine: {restaurant.cuisine_type or ''}
        Michelin Stars: {restaurant.michelin_stars}
        {f'Green Star: Awarded for sustainability' if restaurant.has_green_star else ''}
        Price Range: {restaurant.get_price_range_display() or ''}
        """
        
        # Add menu content if available
        menu_content = []
        for section in restaurant.menu_sections.all():
            menu_content.append(f"{section.name}: {section.description}")
            for item in section.items.all():
                menu_content.append(f"{item.name} - {item.description}")
        
        if menu_content:
            content += "\nMenu:\n" + "\n".join(menu_content)
        
        # Call RAG service to generate and store embeddings
        metadata = {
            'restaurant_name': restaurant.name,
            'city': restaurant.city,
            'country': restaurant.country,
            'cuisine_type': restaurant.cuisine_type,
            'michelin_stars': restaurant.michelin_stars,
            'price_range': restaurant.price_range,
        }
        
        response = requests.post(
            f"{rag_service_url}/embeddings/generate",
            json={"content": content.strip(), "metadata": metadata},
            timeout=30
        )
        response.raise_for_status()
        
        logger.info(f"Updated embeddings for restaurant: {restaurant.name}")
        return {'success': True, 'restaurant_name': restaurant.name}
        
    except Exception as e:
        logger.error(f"Failed to update embeddings for restaurant {restaurant_id}: {str(e)}")
        raise


@shared_task
def process_image_ai_categorization(image_id):
    """
    Process AI categorization for a restaurant image.
    
    Args:
        image_id: UUID of the RestaurantImage to process
    """
    try:
        image = RestaurantImage.objects.get(id=image_id)
        
        if image.processing_status == 'completed':
            logger.info(f"Image {image_id} already processed")
            return {'status': 'already_completed'}
        
        image.processing_status = 'processing'
        image.save()
        
        # Use ImageAI service for categorization (no circular dependency)
        from services.image_ai_service import get_image_ai_service
        ai_service = get_image_ai_service()
        
        # Run AI categorization on the image URL
        if image.source_url:
            ai_result = ai_service.categorize_image_with_ai(image.source_url)
            
            # Update image with AI results
            image.ai_category = ai_result.get('category', 'uncategorized')
            image.ai_labels = ai_result.get('labels', [])
            image.ai_description = ai_result.get('description', '')
            image.category_confidence = ai_result.get('category_confidence', 0.0)
            image.description_confidence = ai_result.get('description_confidence', 0.0)
            image.processing_status = 'completed'
            image.processed_at = timezone.now()
            image.save()
            
            logger.info(f"AI categorization completed for image {image_id}: {image.ai_category}")
            
            # Update restaurant embeddings with new image data
            update_restaurant_embeddings.delay(image.restaurant.id)
            
            return {
                'status': 'completed',
                'category': image.ai_category,
                'confidence': image.category_confidence
            }
        
        image.processing_status = 'failed'
        image.processing_error = 'No source URL available'
        image.save()
        
        return {'status': 'no_source_url'}
        
    except Exception as e:
        try:
            image = RestaurantImage.objects.get(id=image_id)
            image.processing_status = 'failed'
            image.processing_error = str(e)
            image.save()
        except:
            pass
        
        logger.error(f"AI categorization failed for image {image_id}: {str(e)}")
        raise


@shared_task
def scrape_restaurant_images_task(restaurant_id, max_images=15):
    """
    Scrape images for a specific restaurant.
    
    Args:
        restaurant_id: UUID of the restaurant
        max_images: Maximum number of images to scrape
    """
    try:
        restaurant = Restaurant.objects.get(id=restaurant_id)
        
        if not restaurant.website and not restaurant.original_url:
            logger.warning(f"No URL available for restaurant {restaurant.name}")
            return {'success': False, 'error': 'No URL available'}
        
        scraper = RestaurantImageScraper()
        
        # Scrape images
        url = restaurant.website or restaurant.original_url
        image_results = scraper.scrape_restaurant_images(
            restaurant_url=url,
            restaurant_name=restaurant.name,
            max_images=max_images,
            enable_ai_categorization=True
        )
        
        # Save images to database
        successful_images = 0
        for img_data in image_results:
            if img_data.get('status') in ['completed', 'downloaded']:
                RestaurantImage.objects.create(
                    restaurant=restaurant,
                    source_url=img_data.get('source_url', ''),
                    caption=f"Scraped from {restaurant.name}",
                    ai_category=img_data.get('ai_category', 'uncategorized'),
                    ai_labels=img_data.get('ai_labels', []),
                    ai_description=img_data.get('ai_description', ''),
                    category_confidence=img_data.get('category_confidence', 0.0),
                    description_confidence=img_data.get('description_confidence', 0.0),
                    width=img_data.get('width'),
                    height=img_data.get('height'),
                    file_size=img_data.get('file_size'),
                    processing_status='completed' if img_data.get('ai_category') else 'pending',
                    processed_at=timezone.now() if img_data.get('ai_category') else None
                )
                successful_images += 1
        
        # Update restaurant embeddings with new image data
        if successful_images > 0:
            update_restaurant_embeddings.delay(restaurant.id)
        
        logger.info(f"Scraped {successful_images} images for restaurant: {restaurant.name}")
        
        return {
            'success': True,
            'restaurant_name': restaurant.name,
            'images_scraped': successful_images,
            'total_found': len(image_results)
        }
        
    except Exception as e:
        logger.error(f"Image scraping failed for restaurant {restaurant_id}: {str(e)}")
        raise


@shared_task
def trigger_document_embedding_on_scrape(restaurant_name, scraping_results=None):
    """
    Update embeddings when new document data is available from scraping.
    
    Args:
        restaurant_name: Name of the restaurant
        scraping_results: Optional scraping results dict
    """
    try:
        # Find the restaurant in database
        restaurant = Restaurant.objects.filter(
            name__icontains=restaurant_name.split()[0],
            is_active=True
        ).first()
        
        if restaurant:
            # Update embeddings with any new scraped content
            update_restaurant_embeddings.delay(restaurant.id)
            
            logger.info(f"Triggered embedding update for {restaurant.name} after scraping")
            
            return {
                'success': True,
                'restaurant_name': restaurant.name,
                'embedding_update_queued': True
            }
        else:
            logger.warning(f"Could not find restaurant: {restaurant_name}")
            return {
                'success': False,
                'error': 'Restaurant not found',
                'restaurant_name': restaurant_name
            }
            
    except Exception as e:
        logger.error(f"Error triggering embedding update for {restaurant_name}: {str(e)}")
        raise


@shared_task
def cleanup_old_images(days_old=90):
    """
    Clean up old restaurant images that failed processing.
    
    Args:
        days_old: Number of days old images should be before cleanup
    """
    try:
        cutoff_date = timezone.now() - timezone.timedelta(days=days_old)
        
        # Delete images that failed processing and are old
        old_failed_images = RestaurantImage.objects.filter(
            created_at__lt=cutoff_date,
            processing_status='failed'
        )
        
        count = old_failed_images.count()
        old_failed_images.delete()
        
        logger.info(f"Cleaned up {count} old failed images")
        
        return {
            'cleaned_up': count,
            'cutoff_date': cutoff_date.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up old images: {str(e)}")
        raise


@shared_task
def batch_process_pending_images(max_images=50):
    """
    Process AI categorization for pending restaurant images.
    
    Args:
        max_images: Maximum number of images to process in one batch
    """
    try:
        # Get pending images for AI processing
        pending_images = RestaurantImage.objects.filter(
            processing_status='pending'
        ).select_related('restaurant').order_by('created_at')[:max_images]
        
        processed = 0
        failed = 0
        
        for image in pending_images:
            try:
                # Queue individual AI processing task
                process_image_ai_categorization.delay(image.id)
                processed += 1
                
                # Small delay to prevent overwhelming the API
                import time
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error queuing image {image.id} for AI processing: {e}")
                failed += 1
        
        logger.info(f"Queued {processed} images for AI processing, {failed} failed")
        
        return {
            'queued': processed,
            'failed': failed,
            'total_pending': pending_images.count()
        }
        
    except Exception as e:
        logger.error(f"Error in batch image processing: {str(e)}")
        raise


@shared_task
def batch_update_recent_embeddings(hours_back=24):
    """
    Update embeddings for restaurants modified in the last X hours.
    
    Args:
        hours_back: Number of hours to look back for modified restaurants
    """
    try:
        cutoff_time = timezone.now() - timezone.timedelta(hours=hours_back)
        
        # Find recently modified restaurants
        recent_restaurants = Restaurant.objects.filter(
            modified_at__gte=cutoff_time,
            is_active=True
        ).values_list('id', flat=True)
        
        queued = 0
        for restaurant_id in recent_restaurants:
            try:
                update_restaurant_embeddings.delay(restaurant_id)
                queued += 1
            except Exception as e:
                logger.error(f"Error queuing embeddings update for restaurant {restaurant_id}: {e}")
        
        logger.info(f"Queued {queued} restaurants for embeddings update")
        
        return {
            'queued': queued,
            'hours_back': hours_back,
            'restaurants_found': len(recent_restaurants)
        }
        
    except Exception as e:
        logger.error(f"Error in batch embeddings update: {str(e)}")
        raise


@shared_task
def warm_popular_restaurant_cache():
    """
    Warm cache with popular restaurant data to improve performance.
    """
    try:
        from django.core.cache import cache
        
        warmed_count = 0
        
        # Warm featured restaurants cache
        featured_restaurants = Restaurant.objects.filter(
            is_active=True, is_featured=True
        ).select_related().prefetch_related(
            'images', 'chefs', 'menu_sections'
        ).order_by('-michelin_stars', 'name')[:20]
        
        cache.set('featured_restaurants_data', list(featured_restaurants), 1800)  # 30 minutes
        warmed_count += 1
        
        # Warm Michelin starred restaurants cache
        michelin_restaurants = Restaurant.objects.filter(
            is_active=True, michelin_stars__gt=0
        ).select_related().prefetch_related(
            'images', 'chefs', 'menu_sections'
        ).order_by('-michelin_stars', 'name')[:50]
        
        cache.set('michelin_starred_restaurants_data', list(michelin_restaurants), 1800)  # 30 minutes
        warmed_count += 1
        
        # Warm top-rated restaurants cache
        top_rated_restaurants = Restaurant.objects.filter(
            is_active=True, rating__gte=4.0
        ).select_related().prefetch_related(
            'images', 'chefs', 'reviews'
        ).order_by('-rating', '-review_count')[:30]
        
        cache.set('top_rated_restaurants_data', list(top_rated_restaurants), 1800)  # 30 minutes
        warmed_count += 1
        
        logger.info(f"Warmed {warmed_count} cache entries for popular restaurants")
        
        return {
            'warmed_entries': warmed_count,
            'featured_count': featured_restaurants.count(),
            'michelin_count': michelin_restaurants.count(),
            'top_rated_count': top_rated_restaurants.count()
        }
        
    except Exception as e:
        logger.error(f"Error warming restaurant cache: {str(e)}")
        raise


@shared_task
def system_health_check():
    """
    Perform comprehensive health check of all background services.
    """
    try:
        health_status = {
            'timestamp': timezone.now().isoformat(),
            'services': {},
            'overall_status': 'healthy'
        }
        
        # Check database connectivity
        try:
            restaurant_count = Restaurant.objects.filter(is_active=True).count()
            health_status['services']['database'] = {
                'status': 'healthy',
                'active_restaurants': restaurant_count
            }
        except Exception as e:
            health_status['services']['database'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
        
        # Check Redis connectivity
        try:
            from django.core.cache import cache
            test_key = f"health_check_{timezone.now().timestamp()}"
            cache.set(test_key, 'test', 10)
            result = cache.get(test_key)
            cache.delete(test_key)
            
            health_status['services']['redis'] = {
                'status': 'healthy' if result == 'test' else 'degraded'
            }
            
            if result != 'test':
                health_status['overall_status'] = 'degraded'
                
        except Exception as e:
            health_status['services']['redis'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'critical'
        
        # Check RAG service connectivity
        try:
            import requests
            rag_service_url = getattr(settings, 'RAG_SERVICE_URL', 'http://localhost:8001')
            response = requests.get(f"{rag_service_url}/health", timeout=5)
            
            health_status['services']['rag_service'] = {
                'status': 'healthy' if response.status_code == 200 else 'degraded',
                'response_time': response.elapsed.total_seconds()
            }
            
            if response.status_code != 200:
                health_status['overall_status'] = 'degraded'
                
        except Exception as e:
            health_status['services']['rag_service'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            # RAG service being down is not critical for core operations
            if health_status['overall_status'] == 'healthy':
                health_status['overall_status'] = 'degraded'
        
        # Check pending task queue sizes
        try:
            # This would require Celery inspection - simplified for now
            health_status['services']['task_queues'] = {
                'status': 'healthy',
                'note': 'Queue monitoring requires Celery inspection'
            }
        except Exception as e:
            health_status['services']['task_queues'] = {
                'status': 'unknown',
                'error': str(e)
            }
        
        logger.info(f"System health check completed: {health_status['overall_status']}")
        
        # Log any critical issues
        if health_status['overall_status'] == 'critical':
            logger.error(f"CRITICAL: System health check failed: {health_status}")
        elif health_status['overall_status'] == 'degraded':
            logger.warning(f"WARNING: System health degraded: {health_status}")
        
        return health_status
        
    except Exception as e:
        logger.error(f"Error in system health check: {str(e)}")
        raise