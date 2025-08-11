"""
Django management command to migrate existing restaurant images to S3.

Usage:
    python manage.py migrate_images_to_s3 --dry-run
    python manage.py migrate_images_to_s3 --batch-size 50
    python manage.py migrate_images_to_s3 --restaurant-id <uuid>
    python manage.py migrate_images_to_s3 --cleanup-local
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from restaurants.models import RestaurantImage
from services.s3_service import get_s3_service
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate existing restaurant images from local storage to S3'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without actually doing it'
        )
        
        parser.add_argument(
            '--restaurant-id',
            type=str,
            help='Migrate images for a specific restaurant ID only'
        )
        
        parser.add_argument(
            '--batch-size',
            type=int,
            default=20,
            help='Number of images to process in each batch (default: 20)'
        )
        
        parser.add_argument(
            '--max-workers',
            type=int,
            default=3,
            help='Number of parallel workers for S3 uploads (default: 3)'
        )
        
        parser.add_argument(
            '--cleanup-local',
            action='store_true',
            help='Delete local image files after successful S3 migration (USE WITH CAUTION)'
        )
        
        parser.add_argument(
            '--skip-existing-s3',
            action='store_true',
            help='Skip images that already have S3 URLs (default behavior)'
        )

    def handle(self, *args, **options):
        try:
            # Initialize S3 service
            s3_service = get_s3_service()
            
            # Build queryset
            queryset = self.build_queryset(options)
            
            if not queryset.exists():
                self.stdout.write(
                    self.style.WARNING('No images found to migrate')
                )
                return
            
            total_images = queryset.count()
            
            if options['dry_run']:
                self.handle_dry_run(queryset, total_images, options)
            else:
                self.handle_migration(queryset, total_images, options, s3_service)
                
        except Exception as e:
            logger.error(f"Migration command failed: {e}")
            raise CommandError(f"Migration failed: {e}")

    def build_queryset(self, options):
        """Build queryset based on command options."""
        queryset = RestaurantImage.objects.select_related('restaurant')
        
        # Filter by restaurant if specified
        if options['restaurant_id']:
            queryset = queryset.filter(restaurant_id=options['restaurant_id'])
        
        # Skip images that already have S3 URLs (unless explicitly requested)
        if options['skip_existing_s3']:
            queryset = queryset.filter(
                Q(s3_url__isnull=True) | Q(s3_url='')
            )
        
        # Only include images that have either local files or source URLs
        queryset = queryset.filter(
            Q(image__isnull=False) | Q(source_url__isnull=False)
        ).exclude(
            Q(image='') & (Q(source_url__isnull=True) | Q(source_url=''))
        )
        
        return queryset.order_by('restaurant__name', 'created_at')

    def handle_dry_run(self, queryset, total_images, options):
        """Handle dry run - show what would be migrated."""
        self.stdout.write(
            self.style.SUCCESS(f'\n=== DRY RUN: S3 Migration Plan ===')
        )
        
        # Count by type
        local_images = queryset.filter(image__isnull=False).exclude(image='').count()
        url_images = queryset.filter(
            Q(image__isnull=True) | Q(image=''),
            source_url__isnull=False
        ).exclude(source_url='').count()
        
        self.stdout.write(f'Total images to migrate: {total_images}')
        self.stdout.write(f'  - Local files: {local_images}')
        self.stdout.write(f'  - Source URLs: {url_images}')
        
        # Show sample of what would be migrated
        self.stdout.write('\nSample images to migrate:')
        for image in queryset[:5]:
            source_type = 'Local file' if image.image else 'Source URL'
            source_value = image.image.name if image.image else image.source_url
            
            self.stdout.write(
                f'  - {image.restaurant.name}: {source_type} ({source_value})'
            )
        
        if total_images > 5:
            self.stdout.write(f'  ... and {total_images - 5} more')
        
        # Estimate
        batch_size = options['batch_size']
        estimated_batches = (total_images + batch_size - 1) // batch_size
        estimated_time_minutes = estimated_batches * 2  # Rough estimate
        
        self.stdout.write(f'\nEstimated migration:')
        self.stdout.write(f'  - Batches: {estimated_batches}')
        self.stdout.write(f'  - Estimated time: {estimated_time_minutes} minutes')
        
        self.stdout.write(
            self.style.WARNING('\nThis was a dry run. Use --no-dry-run to perform actual migration.')
        )

    def handle_migration(self, queryset, total_images, options, s3_service):
        """Handle actual migration to S3."""
        self.stdout.write(
            self.style.SUCCESS(f'\n=== Starting S3 Migration ===')
        )
        self.stdout.write(f'Total images to migrate: {total_images}')
        
        batch_size = options['batch_size']
        max_workers = options['max_workers']
        cleanup_local = options['cleanup_local']
        
        # Process in batches
        processed = 0
        successful = 0
        failed = 0
        
        for batch_start in range(0, total_images, batch_size):
            batch_end = min(batch_start + batch_size, total_images)
            batch = queryset[batch_start:batch_end]
            
            self.stdout.write(f'\nProcessing batch {batch_start + 1}-{batch_end} of {total_images}...')
            
            # Process batch with threading
            batch_results = self.process_batch(batch, max_workers, s3_service)
            
            # Update counters
            batch_successful = len([r for r in batch_results if r['status'] in ['migrated', 'already_migrated']])
            batch_failed = len([r for r in batch_results if r['status'] in ['failed', 'error']])
            
            successful += batch_successful
            failed += batch_failed
            processed += len(batch_results)
            
            # Show batch results
            self.stdout.write(f'  Batch results: {batch_successful} successful, {batch_failed} failed')
            
            # Cleanup local files if requested
            if cleanup_local and batch_successful > 0:
                self.cleanup_local_files(batch_results)
            
            # Progress
            progress_percent = (processed / total_images) * 100
            self.stdout.write(f'  Overall progress: {processed}/{total_images} ({progress_percent:.1f}%)')
            
            # Brief pause between batches
            time.sleep(1)
        
        # Final summary
        self.stdout.write(
            self.style.SUCCESS(f'\n=== Migration Complete ===')
        )
        self.stdout.write(f'Total processed: {processed}')
        self.stdout.write(f'Successful: {successful}')
        self.stdout.write(f'Failed: {failed}')
        
        if failed > 0:
            self.stdout.write(
                self.style.WARNING(f'Note: {failed} images failed to migrate. Check logs for details.')
            )

    def process_batch(self, batch, max_workers, s3_service):
        """Process a batch of images with parallel workers."""
        results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_image = {
                executor.submit(self.migrate_single_image, image, s3_service): image
                for image in batch
            }
            
            for future in as_completed(future_to_image):
                image = future_to_image[future]
                try:
                    result = future.result(timeout=60)
                    result['image_id'] = str(image.id)
                    result['restaurant_name'] = image.restaurant.name
                    results.append(result)
                    
                    if result['status'] in ['failed', 'error']:
                        self.stdout.write(
                            self.style.ERROR(f"    Failed: {image.restaurant.name} - {result['message']}")
                        )
                    else:
                        self.stdout.write(f"    Success: {image.restaurant.name}")
                        
                except Exception as e:
                    logger.error(f"Batch processing error for image {image.id}: {e}")
                    results.append({
                        'image_id': str(image.id),
                        'restaurant_name': image.restaurant.name,
                        'status': 'error',
                        'message': f'Processing error: {str(e)}'
                    })
        
        return results

    def migrate_single_image(self, image, s3_service):
        """Migrate a single image to S3."""
        try:
            # Use the model's built-in migration method
            result = image.migrate_to_s3()
            return result
            
        except Exception as e:
            logger.error(f"Single image migration failed for {image.id}: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }

    def cleanup_local_files(self, batch_results):
        """Clean up local image files after successful S3 migration."""
        for result in batch_results:
            if result['status'] == 'migrated':
                try:
                    image = RestaurantImage.objects.get(id=result['image_id'])
                    if image.image and hasattr(image.image, 'path'):
                        local_path = Path(image.image.path)
                        if local_path.exists():
                            local_path.unlink()
                            logger.info(f"Deleted local file: {local_path}")
                            
                            # Clear the image field
                            image.image = None
                            image.save(update_fields=['image'])
                            
                except Exception as e:
                    logger.error(f"Failed to cleanup local file for {result['image_id']}: {e}")

    def get_migration_stats(self):
        """Get current migration statistics."""
        total_images = RestaurantImage.objects.count()
        s3_images = RestaurantImage.objects.filter(
            s3_url__isnull=False
        ).exclude(s3_url='').count()
        
        local_only = RestaurantImage.objects.filter(
            Q(s3_url__isnull=True) | Q(s3_url=''),
            image__isnull=False
        ).exclude(image='').count()
        
        url_only = RestaurantImage.objects.filter(
            Q(s3_url__isnull=True) | Q(s3_url=''),
            Q(image__isnull=True) | Q(image=''),
            source_url__isnull=False
        ).exclude(source_url='').count()
        
        return {
            'total': total_images,
            's3_stored': s3_images,
            'local_only': local_only,
            'url_only': url_only,
            'migration_percent': (s3_images / total_images * 100) if total_images > 0 else 0
        }