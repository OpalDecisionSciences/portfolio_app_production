"""
Django management command to run comprehensive Michelin restaurant scraping.

This command integrates with token_manager.py's existing functionality:
- When call_openai_chat() returns None (token limit reached), scraping stops gracefully
- Uses update_last_completed_row() to save progress after each restaurant
- Uses get_last_completed_row() to resume from where it left off
- Automatically handles daily token reset

Usage:
    python manage.py run_comprehensive_scraping --test-run     # Test with 5 restaurants
    python manage.py run_comprehensive_scraping                # Resume or start scraping
    python manage.py run_comprehensive_scraping --full-run     # Process all 18,113
"""

import os
import sys
import json
import asyncio
import pandas as pd
from pathlib import Path
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# Setup portfolio paths - need to add parent paths for imports
base_path = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(base_path / "data_pipeline" / "src"))
sys.path.insert(0, str(base_path / "shared" / "src"))

# Setup Django environment for scrapers
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

class Command(BaseCommand):
    help = 'Run comprehensive Michelin restaurant scraping with automatic token management and resume'

    def add_arguments(self, parser):
        # Determine default CSV path based on environment
        if os.path.exists('/app'):
            # Docker environment
            default_csv = '/data_pipeline/src/ingestion/michelin_my_maps.csv'
        else:
            # Local development
            default_csv = '/Users/iamai/projects/portfolio_app_production/data_pipeline/src/ingestion/michelin_my_maps.csv'
        
        parser.add_argument(
            '--csv-path',
            type=str,
            default=default_csv,
            help='Path to Michelin CSV file'
        )
        
        parser.add_argument(
            '--batch-size',
            type=int,
            default=5,
            help='Number of restaurants to process per batch (default: 5)'
        )
        
        parser.add_argument(
            '--test-run',
            action='store_true',
            help='Small test run with 5 restaurants for validation'
        )
        
        parser.add_argument(
            '--full-run',
            action='store_true',
            help='Process all 18,113 restaurants (will take multiple days due to token limits)'
        )
        
        parser.add_argument(
            '--force-restart',
            action='store_true',
            help='Force restart from beginning (clears token_manager saved progress)'
        )

    def handle(self, *args, **options):
        """Handle the management command execution."""
        try:
            # Import here to avoid Django setup issues
            from scrapers.comprehensive_restaurant_scraper import ComprehensiveRestaurantScraper
            from scrapers.s3_image_scraper import S3RestaurantImageScraper
            from token_management.token_manager import (
                init_token_manager, 
                get_token_usage_summary, 
                get_last_completed_row,
                update_last_completed_row,
                call_openai_chat
            )
            from restaurants.models import Restaurant, RestaurantImage
            from services.s3_service import get_s3_service
            import logging
            
            # Configure logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            logger = logging.getLogger(__name__)
            
            # Initialize token manager for production
            # In Docker, we want to use /app as the base directory
            if os.path.exists('/app'):
                project_dir = Path('/app')
            else:
                project_dir = Path(settings.BASE_DIR).parent.parent
            
            # Ensure state directory exists with proper permissions
            state_dir = project_dir / 'state'
            state_dir.mkdir(parents=True, exist_ok=True)
            
            init_token_manager(project_dir)
            
            # Check current token usage and date
            token_summary = get_token_usage_summary()
            self.stdout.write(
                self.style.SUCCESS(f'\n💰 Token Status for {token_summary["date"]}:')
            )
            for model, usage in token_summary.get('usage_by_model', {}).items():
                # Show usage vs limits
                limits = {'gpt-4o': 240_000, 'gpt-4o-mini': 2_450_000}
                limit = limits.get(model, 0)
                percent = (usage / limit * 100) if limit > 0 else 0
                self.stdout.write(f'   {model}: {usage:,}/{limit:,} tokens ({percent:.1f}%)')
            
            # Get last completed row from token_manager
            last_row = get_last_completed_row()
            
            # Force restart if requested
            if options['force_restart']:
                self.stdout.write(
                    self.style.WARNING('⚠️  Force restart: Resetting progress to beginning')
                )
                update_last_completed_row(-1)
                last_row = -1
            
            # Load CSV
            csv_path = Path(options['csv_path'])
            if not csv_path.exists():
                raise CommandError(f"CSV file not found: {csv_path}")
            
            df = pd.read_csv(csv_path)
            total_restaurants = len(df)
            
            # Configure run parameters
            if options['test_run']:
                max_restaurants = 5
                batch_size = 2
                self.stdout.write(
                    self.style.WARNING('🧪 TEST RUN: Processing 5 restaurants')
                )
            elif options['full_run']:
                max_restaurants = total_restaurants
                batch_size = 10
                self.stdout.write(
                    self.style.SUCCESS(f'🚀 FULL RUN: Processing all {total_restaurants} restaurants')
                )
            else:
                # Default: process what we can with current token limits
                max_restaurants = total_restaurants
                batch_size = options['batch_size']
                self.stdout.write(
                    self.style.SUCCESS(f'📊 Processing restaurants (batch size: {batch_size})')
                )
            
            # Calculate starting position
            start_index = last_row + 1 if last_row >= 0 else 0
            
            # Check if already completed
            if start_index >= min(total_restaurants, max_restaurants):
                self.stdout.write(
                    self.style.SUCCESS(f'✅ All {max_restaurants} restaurants already processed!')
                )
                return
            
            # Show resume status
            if start_index > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'\n♻️  RESUMING from row {start_index} (already processed: {start_index})')
                )
                remaining = min(total_restaurants, max_restaurants) - start_index
                self.stdout.write(f'   Remaining to process: {remaining}')
            
            # Database status
            restaurant_count = Restaurant.objects.count()
            self.stdout.write(f'\n📊 Database Status:')
            self.stdout.write(f'   Total restaurants in DB: {restaurant_count}')
            self.stdout.write(f'   Starting CSV row: {start_index}')
            self.stdout.write(f'   Total CSV rows: {total_restaurants}')
            self.stdout.write('=' * 60)
            
            # Initialize scrapers
            comprehensive_scraper = ComprehensiveRestaurantScraper()
            s3_image_scraper = S3RestaurantImageScraper()
            s3_service = get_s3_service()
            
            # Process restaurants
            processed_count = 0
            successful_count = 0
            failed_count = 0
            token_limit_reached = False
            
            self.stdout.write('\n⚡ Starting scraping process...\n')
            
            # Process from start_index to max_restaurants
            for i in range(start_index, min(total_restaurants, max_restaurants), batch_size):
                batch_end = min(i + batch_size, min(total_restaurants, max_restaurants))
                batch = df.iloc[i:batch_end]
                
                self.stdout.write(f'\n📦 Processing batch: rows {i}-{batch_end-1}')
                
                for idx, row in batch.iterrows():
                    restaurant_name = row.get('Name', 'Unknown')
                    self.stdout.write(f'\n🍴 Processing: {restaurant_name} (row {idx})')
                    
                    try:
                        # Step 1: Create/update restaurant in database
                        restaurant_data = row.to_dict()
                        restaurant = self.create_or_update_restaurant(restaurant_data)
                        
                        # Step 2: Comprehensive scraping (uses call_openai_chat internally)
                        # This will return None if token limit is reached
                        scraping_result = comprehensive_scraper.process_single_restaurant_from_data(restaurant_data)
                        
                        if scraping_result is None:
                            # Token limit reached - token_manager returned None
                            self.stdout.write(
                                self.style.ERROR(f'🛑 Token limit reached at row {idx}')
                            )
                            token_limit_reached = True
                            break
                        
                        # Step 3: Image scraping with S3
                        if row.get('WebsiteUrl'):
                            try:
                                image_results = s3_image_scraper.scrape_restaurant_images(
                                    restaurant_name=restaurant_name,
                                    website_url=row['WebsiteUrl'],
                                    max_images=5,
                                    save_to_db=True
                                )
                                self.stdout.write(f'   📸 Scraped {len(image_results)} images')
                            except Exception as img_error:
                                logger.warning(f"Image scraping failed for {restaurant_name}: {img_error}")
                        
                        # Step 4: Update progress in token_manager
                        update_last_completed_row(idx)
                        
                        successful_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f'   ✅ Completed row {idx}: {restaurant_name}')
                        )
                        
                    except Exception as e:
                        # Check if error is token-related
                        error_msg = str(e).lower()
                        if 'token' in error_msg or 'all model tiers exhausted' in error_msg:
                            self.stdout.write(
                                self.style.ERROR(f'🛑 Token error at row {idx}: {e}')
                            )
                            token_limit_reached = True
                            break
                        
                        failed_count += 1
                        logger.error(f"Failed to process {restaurant_name}: {e}")
                        self.stdout.write(
                            self.style.ERROR(f'   ❌ Failed: {e}')
                        )
                        
                        # Still update progress even on failure
                        update_last_completed_row(idx)
                    
                    processed_count += 1
                
                # Check if we hit token limit
                if token_limit_reached:
                    break
                
                # Brief pause between batches
                import time
                time.sleep(2)
            
            # Final summary
            self.stdout.write('\n' + '=' * 60)
            if token_limit_reached:
                self.stdout.write(
                    self.style.WARNING(
                        f'\n⏸️  PAUSED: Token limit reached for today'
                    )
                )
                self.stdout.write(
                    f'   Processed: {processed_count} restaurants'
                )
                self.stdout.write(
                    f'   Successful: {successful_count}'
                )
                self.stdout.write(
                    f'   Failed: {failed_count}'
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n🔄 Run this command again tomorrow to continue from row {get_last_completed_row() + 1}'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n🎉 COMPLETED: All restaurants processed!'
                    )
                )
                self.stdout.write(
                    f'   Total processed: {processed_count}'
                )
                self.stdout.write(
                    f'   Successful: {successful_count}'
                )
                self.stdout.write(
                    f'   Failed: {failed_count}'
                )
            
            # Show final token usage
            final_summary = get_token_usage_summary()
            self.stdout.write(f'\n💰 Final Token Usage:')
            for model, usage in final_summary.get('usage_by_model', {}).items():
                limits = {'gpt-4o': 240_000, 'gpt-4o-mini': 2_450_000}
                limit = limits.get(model, 0)
                percent = (usage / limit * 100) if limit > 0 else 0
                self.stdout.write(f'   {model}: {usage:,}/{limit:,} tokens ({percent:.1f}%)')
            
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('\n⚠️ Interrupted by user. Progress saved automatically.')
            )
            self.stdout.write(
                f'   Resume from row {get_last_completed_row() + 1} next time'
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\n❌ Command failed: {str(e)}')
            )
            raise CommandError(f'Scraping failed: {e}')
    
    def create_or_update_restaurant(self, data):
        """Create or update restaurant in database."""
        from restaurants.models import Restaurant
        from django.contrib.gis.geos import Point
        
        # Convert price format to match Restaurant model choices
        price_mapping = {'€€€€': '$$$$', '€€€': '$$$', '€€': '$$', '€': '$', 
                       '$$$$': '$$$$', '$$$': '$$$', '$$': '$$', '$': '$'}
        price_range = price_mapping.get(data.get('Price', ''), '')
        
        # Extract coordinates
        longitude = data.get('Longitude', 0) or 0
        latitude = data.get('Latitude', 0) or 0
        
        restaurant, created = Restaurant.objects.update_or_create(
            name=data.get('Name', ''),
            defaults={
                'description': data.get('Description', ''),
                'website': data.get('WebsiteUrl', ''),
                'original_url': data.get('Url', ''),
                'cuisine_type': data.get('Cuisine', ''),
                'country': data.get('Location', '').split(', ')[-1] if data.get('Location') else '',
                'city': data.get('Location', '').split(', ')[0] if data.get('Location') else '',
                'address': data.get('Address', ''),
                'phone': data.get('PhoneNumber', ''),  # Fixed: phone not phone_number
                'price_range': price_range,  # Fixed: price_range not price_level
                'michelin_stars': data.get('Award', '').count('Star'),
                'has_green_star': data.get('GreenStar', '0') == '1',  # Fixed: has_green_star field added
                'facilities': data.get('FacilitiesAndServices', ''),
                'longitude': float(longitude) if longitude else None,
                'latitude': float(latitude) if latitude else None,
                'geolocation': Point(float(longitude), float(latitude), srid=4326) if longitude and latitude else None,
                'is_active': True
            }
        )
        
        return restaurant