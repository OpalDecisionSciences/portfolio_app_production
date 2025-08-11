"""
Comprehensive Scraping Monitor for Michelin Restaurant Data
Monitors all aspects of the scraping pipeline including:
- CSV processing and database insertion
- Web scraping with translations and summarizations 
- Document.txt generation
- Menu item and pricing parsing
- Image scraping with S3 storage
- Vector embeddings generation
- Real-time progress tracking
"""

import os
import sys
import time
import json
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import requests
from concurrent.futures import ThreadPoolExecutor
import asyncio

# Setup portfolio paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

from django.db.models import Count, Q
from restaurants.models import Restaurant, RestaurantImage, MenuSection, MenuItem
from restaurants.tasks import process_image_ai_categorization, update_restaurant_embeddings
from services.s3_service import get_s3_service
from services.image_ai_service import get_image_ai_service
from scrapers.s3_image_scraper import S3RestaurantImageScraper
from scrapers.comprehensive_restaurant_scraper import ComprehensiveRestaurantScraper
from token_management.token_manager import get_token_usage_summary, log_s3_operation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'scraping_monitor_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ComprehensiveScrapingMonitor:
    """Monitor for comprehensive Michelin restaurant scraping process."""
    
    def __init__(self, csv_path: str, batch_size: int = 10, max_restaurants: Optional[int] = None):
        """
        Initialize the monitoring system.
        
        Args:
            csv_path: Path to Michelin CSV file
            batch_size: Number of restaurants to process per batch
            max_restaurants: Maximum restaurants to process (None for all)
        """
        self.csv_path = Path(csv_path)
        self.batch_size = batch_size
        self.max_restaurants = max_restaurants
        
        # Initialize services
        self.s3_service = get_s3_service()
        self.image_ai_service = get_image_ai_service()
        self.s3_scraper = S3RestaurantImageScraper()
        self.comprehensive_scraper = ComprehensiveRestaurantScraper()
        
        # Tracking variables
        self.start_time = datetime.now()
        self.stats = {
            'total_restaurants': 0,
            'processed_restaurants': 0,
            'successful_restaurants': 0,
            'failed_restaurants': 0,
            'images_scraped': 0,
            's3_uploads': 0,
            'ai_categorizations': 0,
            'translations_completed': 0,
            'documents_generated': 0,
            'menu_items_parsed': 0,
            'embeddings_generated': 0,
            'errors': []
        }
        
        # Status tracking
        self.current_batch = 0
        self.current_restaurant = ""
        self.last_update = datetime.now()
        
        logger.info(f"Scraping monitor initialized for {csv_path}")
        logger.info(f"Batch size: {batch_size}, Max restaurants: {max_restaurants or 'ALL'}")
    
    def load_csv_data(self) -> pd.DataFrame:
        """Load and validate CSV data."""
        try:
            df = pd.read_csv(self.csv_path)
            logger.info(f"Loaded CSV with {len(df)} restaurants")
            
            # Validate required columns
            required_cols = ['Name', 'WebsiteUrl', 'Description', 'Url']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")
            
            # Filter out rows with missing essential data
            df = df.dropna(subset=['Name', 'WebsiteUrl']).copy()
            logger.info(f"After filtering: {len(df)} restaurants with valid data")
            
            if self.max_restaurants:
                df = df.head(self.max_restaurants)
                logger.info(f"Limited to first {self.max_restaurants} restaurants")
            
            self.stats['total_restaurants'] = len(df)
            return df
            
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
            raise
    
    def get_database_stats(self) -> Dict[str, int]:
        """Get current database statistics."""
        try:
            return {
                'restaurants': Restaurant.objects.count(),
                'active_restaurants': Restaurant.objects.filter(is_active=True).count(),
                'images': RestaurantImage.objects.count(),
                's3_images': RestaurantImage.objects.exclude(s3_url='').count(),
                'ai_processed_images': RestaurantImage.objects.filter(ai_processed=True).count(),
                'menu_sections': MenuSection.objects.count(),
                'menu_items': MenuItem.objects.count(),
                'restaurants_with_images': Restaurant.objects.filter(images__isnull=False).distinct().count(),
                'restaurants_with_menus': Restaurant.objects.filter(menu_sections__isnull=False).distinct().count()
            }
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}
    
    def monitor_s3_status(self) -> Dict[str, Any]:
        """Monitor S3 bucket status and usage."""
        try:
            # List recent S3 objects
            recent_objects = self.s3_service.list_objects('restaurant-images/', max_results=100)
            
            return {
                'recent_uploads': len(recent_objects),
                'total_size_mb': sum(obj.get('size', 0) for obj in recent_objects) / (1024 * 1024),
                'latest_upload': max([obj.get('last_modified', '') for obj in recent_objects]) if recent_objects else None
            }
        except Exception as e:
            logger.error(f"Error monitoring S3: {e}")
            return {'error': str(e)}
    
    def monitor_rag_service(self) -> Dict[str, Any]:
        """Monitor RAG service and embedding generation."""
        try:
            # Check if RAG service is available
            rag_url = 'http://localhost:8001'  # Adjust based on your setup
            
            health_response = requests.get(f"{rag_url}/health", timeout=5)
            if health_response.status_code == 200:
                # Get embeddings count
                embeddings_response = requests.get(f"{rag_url}/embeddings/count", timeout=5)
                embeddings_count = embeddings_response.json().get('count', 0) if embeddings_response.status_code == 200 else 0
                
                return {
                    'status': 'healthy',
                    'embeddings_count': embeddings_count,
                    'last_check': datetime.now().isoformat()
                }
            else:
                return {'status': 'unhealthy', 'error': f'HTTP {health_response.status_code}'}
                
        except Exception as e:
            logger.warning(f"RAG service not available: {e}")
            return {'status': 'unavailable', 'error': str(e)}
    
    def print_status_report(self):
        """Print comprehensive status report."""
        current_time = datetime.now()
        elapsed = current_time - self.start_time
        
        db_stats = self.get_database_stats()
        s3_stats = self.monitor_s3_status()
        rag_stats = self.monitor_rag_service()
        token_usage = get_token_usage_summary()
        
        print("\n" + "="*80)
        print(f"🍽️  COMPREHENSIVE SCRAPING MONITOR - {current_time.strftime('%H:%M:%S')}")
        print("="*80)
        
        # Progress Overview
        if self.stats['total_restaurants'] > 0:
            progress_pct = (self.stats['processed_restaurants'] / self.stats['total_restaurants']) * 100
            print(f"📊 PROGRESS: {self.stats['processed_restaurants']}/{self.stats['total_restaurants']} ({progress_pct:.1f}%)")
        
        print(f"⏱️  ELAPSED TIME: {elapsed}")
        print(f"🏠 CURRENT: {self.current_restaurant}")
        print(f"📦 BATCH: {self.current_batch}")
        
        # Restaurant Processing Stats
        print(f"\n🍴 RESTAURANT PROCESSING:")
        print(f"   ✅ Successful: {self.stats['successful_restaurants']}")
        print(f"   ❌ Failed: {self.stats['failed_restaurants']}")
        print(f"   📝 Documents: {self.stats['documents_generated']}")
        print(f"   🌍 Translations: {self.stats['translations_completed']}")
        
        # Database Stats
        print(f"\n🗄️  DATABASE STATUS:")
        for key, value in db_stats.items():
            print(f"   {key.replace('_', ' ').title()}: {value}")
        
        # Image Processing Stats  
        print(f"\n🖼️  IMAGE PROCESSING:")
        print(f"   📸 Images Scraped: {self.stats['images_scraped']}")
        print(f"   ☁️  S3 Uploads: {self.stats['s3_uploads']}")
        print(f"   🤖 AI Categorized: {self.stats['ai_categorizations']}")
        print(f"   📊 Menu Items: {self.stats['menu_items_parsed']}")
        
        # S3 Status
        print(f"\n☁️  S3 STATUS:")
        if 'error' not in s3_stats:
            print(f"   Recent Uploads: {s3_stats.get('recent_uploads', 0)}")
            print(f"   Total Size: {s3_stats.get('total_size_mb', 0):.1f} MB")
            print(f"   Latest: {s3_stats.get('latest_upload', 'None')}")
        else:
            print(f"   ❌ Error: {s3_stats['error']}")
        
        # RAG/Embeddings Status
        print(f"\n🔍 RAG/EMBEDDINGS:")
        print(f"   Status: {rag_stats.get('status', 'unknown')}")
        print(f"   Embeddings: {rag_stats.get('embeddings_count', 0)}")
        print(f"   Generated: {self.stats['embeddings_generated']}")
        
        # Token Usage
        print(f"\n🪙 TOKEN USAGE:")
        usage_by_model = token_usage.get('usage_by_model', {})
        for model, usage in usage_by_model.items():
            print(f"   {model}: {usage:,} tokens")
        
        # Performance Metrics
        if self.stats['processed_restaurants'] > 0:
            restaurants_per_hour = (self.stats['processed_restaurants'] / elapsed.total_seconds()) * 3600
            print(f"\n⚡ PERFORMANCE:")
            print(f"   Rate: {restaurants_per_hour:.1f} restaurants/hour")
            
            if self.stats['total_restaurants'] > self.stats['processed_restaurants']:
                remaining = self.stats['total_restaurants'] - self.stats['processed_restaurants']
                eta_hours = remaining / restaurants_per_hour if restaurants_per_hour > 0 else 0
                eta_time = current_time + timedelta(hours=eta_hours)
                print(f"   ETA: {eta_time.strftime('%H:%M:%S')} ({eta_hours:.1f}h remaining)")
        
        # Recent Errors
        if self.stats['errors']:
            print(f"\n⚠️  RECENT ERRORS ({len(self.stats['errors'])}):")
            for error in self.stats['errors'][-3:]:  # Show last 3 errors
                print(f"   • {error}")
        
        print("="*80)
    
    async def process_restaurant_complete(self, restaurant_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single restaurant with complete pipeline."""
        restaurant_name = restaurant_data.get('Name', 'Unknown')
        website_url = restaurant_data.get('WebsiteUrl', '')
        
        self.current_restaurant = restaurant_name
        result = {'name': restaurant_name, 'status': 'processing', 'details': {}}
        
        try:
            logger.info(f"Processing restaurant: {restaurant_name}")
            
            # Step 1: Create/update restaurant in database
            restaurant = await self.create_or_update_restaurant(restaurant_data)
            if not restaurant:
                raise Exception("Failed to create restaurant in database")
            
            result['details']['restaurant_created'] = True
            
            # Step 2: Scrape website content with translations
            if website_url:
                scraping_result = await self.comprehensive_scraper.process_single_restaurant_from_data(restaurant_data)
                if scraping_result:
                    result['details']['content_scraped'] = True
                    if scraping_result.translation_completed:
                        self.stats['translations_completed'] += 1
                        result['details']['translated'] = True
                    if scraping_result.document_generated:
                        self.stats['documents_generated'] += 1
                        result['details']['document_generated'] = True
            
            # Step 3: Scrape images with S3 storage
            if website_url:
                image_results = await self.scrape_images_with_s3(restaurant_name, website_url)
                if image_results:
                    self.stats['images_scraped'] += len(image_results)
                    s3_uploads = len([img for img in image_results if img.get('s3_url')])
                    self.stats['s3_uploads'] += s3_uploads
                    result['details']['images_scraped'] = len(image_results)
                    result['details']['s3_uploads'] = s3_uploads
            
            # Step 4: Process AI categorization for images
            if restaurant.images.exists():
                ai_results = await self.process_ai_categorization(restaurant)
                self.stats['ai_categorizations'] += ai_results
                result['details']['ai_processed'] = ai_results
            
            # Step 5: Parse menu items if available
            menu_count = await self.parse_menu_items(restaurant)
            if menu_count > 0:
                self.stats['menu_items_parsed'] += menu_count
                result['details']['menu_items'] = menu_count
            
            # Step 6: Generate embeddings
            if await self.generate_embeddings(restaurant):
                self.stats['embeddings_generated'] += 1
                result['details']['embeddings_generated'] = True
            
            # Success
            result['status'] = 'completed'
            self.stats['successful_restaurants'] += 1
            logger.info(f"✅ Completed: {restaurant_name}")
            
        except Exception as e:
            error_msg = f"{restaurant_name}: {str(e)}"
            self.stats['errors'].append(error_msg)
            self.stats['failed_restaurants'] += 1
            result['status'] = 'failed'
            result['error'] = str(e)
            logger.error(f"❌ Failed: {error_msg}")
        
        finally:
            self.stats['processed_restaurants'] += 1
        
        return result
    
    async def create_or_update_restaurant(self, data: Dict[str, Any]) -> Optional[Restaurant]:
        """Create or update restaurant in database."""
        try:
            from django.contrib.gis.geos import Point
            
            # Convert price format
            price_mapping = {'€€€€': 4, '$$$': 3, '€€€': 3, '$$': 2, '€€': 2, '$': 1, '€': 1}
            price_level = price_mapping.get(data.get('Price', ''), 0)
            
            # Extract coordinates
            longitude = data.get('Longitude', 0) or 0
            latitude = data.get('Latitude', 0) or 0
            
            restaurant, created = await Restaurant.objects.aupdate_or_create(
                name=data.get('Name', ''),
                defaults={
                    'description': data.get('Description', ''),
                    'website': data.get('WebsiteUrl', ''),
                    'original_url': data.get('Url', ''),
                    'cuisine_type': data.get('Cuisine', ''),
                    'country': data.get('Location', '').split(', ')[-1] if data.get('Location') else '',
                    'city': data.get('Location', '').split(', ')[0] if data.get('Location') else '',
                    'address': data.get('Address', ''),
                    'phone_number': data.get('PhoneNumber', ''),
                    'price_level': price_level,
                    'michelin_stars': data.get('Award', '').count('Star'),
                    'green_star': data.get('GreenStar', '0') == '1',
                    'facilities': data.get('FacilitiesAndServices', ''),
                    'longitude': float(longitude) if longitude else None,
                    'latitude': float(latitude) if latitude else None,
                    'geolocation': Point(float(longitude), float(latitude), srid=4326) if longitude and latitude else None,
                    'is_active': True
                }
            )
            
            return restaurant
            
        except Exception as e:
            logger.error(f"Error creating restaurant {data.get('Name', '')}: {e}")
            return None
    
    async def scrape_images_with_s3(self, restaurant_name: str, website_url: str, max_images: int = 10) -> List[Dict]:
        """Scrape images and upload to S3."""
        try:
            results = self.s3_scraper.scrape_restaurant_images(
                restaurant_name=restaurant_name,
                website_url=website_url,
                max_images=max_images,
                save_to_db=True
            )
            
            # Log S3 operations
            for result in results:
                if result.get('s3_url'):
                    log_s3_operation(
                        operation_type='upload',
                        s3_key=result.get('s3_key', ''),
                        status='success',
                        metadata={
                            'restaurant': restaurant_name,
                            'file_size': result.get('file_size', 0),
                            'ai_category': result.get('category', 'unknown')
                        }
                    )
            
            return results
            
        except Exception as e:
            logger.error(f"Error scraping images for {restaurant_name}: {e}")
            return []
    
    async def process_ai_categorization(self, restaurant: Restaurant) -> int:
        """Process AI categorization for restaurant images."""
        try:
            uncategorized_images = restaurant.images.filter(ai_processed=False)
            count = 0
            
            for image in uncategorized_images:
                if image.s3_url or image.source_url:
                    # Process with AI
                    image_identifier = image.s3_url or image.source_url
                    ai_result = self.image_ai_service.categorize_image_with_ai(image_identifier)
                    
                    if ai_result.get('category'):
                        image.ai_category = ai_result.get('category')
                        image.ai_description = ai_result.get('description', '')
                        image.ai_tags = ai_result.get('tags', [])
                        image.ai_processed = True
                        await image.asave()
                        count += 1
            
            return count
            
        except Exception as e:
            logger.error(f"Error processing AI categorization: {e}")
            return 0
    
    async def parse_menu_items(self, restaurant: Restaurant) -> int:
        """Parse and create menu items if available."""
        try:
            # This would be implemented based on scraped content
            # For now, return 0 as placeholder
            return 0
        except Exception as e:
            logger.error(f"Error parsing menu items: {e}")
            return 0
    
    async def generate_embeddings(self, restaurant: Restaurant) -> bool:
        """Generate vector embeddings for restaurant."""
        try:
            # Trigger embedding generation task
            update_restaurant_embeddings.delay(str(restaurant.id))
            return True
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            return False
    
    async def run_monitoring_loop(self):
        """Run the main monitoring and processing loop."""
        logger.info("🚀 Starting comprehensive scraping process...")
        
        # Load CSV data
        df = self.load_csv_data()
        
        # Print initial status
        self.print_status_report()
        
        # Process in batches
        for i in range(0, len(df), self.batch_size):
            batch = df.iloc[i:i + self.batch_size]
            self.current_batch = (i // self.batch_size) + 1
            
            logger.info(f"🔄 Processing batch {self.current_batch} ({len(batch)} restaurants)")
            
            # Process batch
            tasks = []
            for _, restaurant_data in batch.iterrows():
                task = self.process_restaurant_complete(restaurant_data.to_dict())
                tasks.append(task)
            
            # Wait for batch completion
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in batch_results:
                if isinstance(result, Exception):
                    self.stats['errors'].append(f"Batch error: {str(result)}")
                    self.stats['failed_restaurants'] += 1
            
            # Print status every batch
            self.print_status_report()
            
            # Brief pause between batches
            await asyncio.sleep(2)
        
        # Final report
        logger.info("🎉 Scraping process completed!")
        self.print_status_report()
        self.generate_final_report()
    
    def generate_final_report(self):
        """Generate comprehensive final report."""
        elapsed = datetime.now() - self.start_time
        
        report = {
            'scraping_session': {
                'start_time': self.start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'duration_hours': elapsed.total_seconds() / 3600,
                'csv_file': str(self.csv_path),
                'batch_size': self.batch_size
            },
            'processing_stats': self.stats,
            'final_database_stats': self.get_database_stats(),
            'final_s3_stats': self.monitor_s3_status(),
            'final_rag_stats': self.monitor_rag_service(),
            'token_usage': get_token_usage_summary()
        }
        
        # Save report
        report_file = f"scraping_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"📊 Final report saved to: {report_file}")
        
        # Print summary
        success_rate = (self.stats['successful_restaurants'] / self.stats['total_restaurants']) * 100 if self.stats['total_restaurants'] > 0 else 0
        print(f"\n🎯 FINAL SUMMARY:")
        print(f"   Success Rate: {success_rate:.1f}%")
        print(f"   Total Time: {elapsed}")
        print(f"   Images Processed: {self.stats['images_scraped']}")
        print(f"   S3 Uploads: {self.stats['s3_uploads']}")
        print(f"   AI Categorizations: {self.stats['ai_categorizations']}")
        print(f"   Embeddings Generated: {self.stats['embeddings_generated']}")


async def main():
    """Main entry point."""
    csv_path = "/Users/iamai/projects/portfolio_app_production/data_pipeline/src/ingestion/michelin_my_maps.csv"
    
    # Start with a small batch for testing
    monitor = ComprehensiveScrapingMonitor(
        csv_path=csv_path,
        batch_size=5,  # Small batch for initial testing
        max_restaurants=20  # Limit to first 20 for testing
    )
    
    await monitor.run_monitoring_loop()


if __name__ == "__main__":
    asyncio.run(main())