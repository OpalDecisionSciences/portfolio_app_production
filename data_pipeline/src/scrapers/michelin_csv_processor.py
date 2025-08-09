"""
Michelin CSV Processor - Process michelin_my_maps.csv and scrape additional data.
"""
import csv
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Setup portfolio paths for cross-component imports
# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Handle both relative and absolute imports
try:
    from .unified_restaurant_scraper import UnifiedRestaurantScraper
    from .scrape_utils import clean_filename
except ImportError:
    from unified_restaurant_scraper import UnifiedRestaurantScraper
    from scrape_utils import clean_filename

from token_management.token_manager import init_token_manager, get_token_usage_summary

# Set up Django environment
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

import django
django.setup()

from django.utils import timezone
from restaurants.models import Restaurant, ScrapingJob
from processors.data_processor import DataProcessor

logger = logging.getLogger(__name__)


class MichelinCSVProcessor:
    """
    Process Michelin CSV data and scrape additional restaurant information.
    """
    
    def __init__(self, csv_file_path: Path, token_dir: Optional[Path] = None):
        """
        Initialize the Michelin CSV processor.
        
        Args:
            csv_file_path: Path to the michelin_my_maps.csv file
            token_dir: Directory for token management
        """
        self.csv_file_path = csv_file_path
        
        # Initialize token manager
        if token_dir is None:
            token_dir = Path(__file__).parent.parent.parent.parent / "shared" / "token_management"
        
        init_token_manager(token_dir)
        
        # Initialize components
        self.restaurant_scraper = UnifiedRestaurantScraper(token_dir)
        self.data_processor = DataProcessor()
        
        logger.info("Michelin CSV processor initialized")
    
    def process_csv_file(self, start_row: int = 0, max_restaurants: Optional[int] = None) -> Dict[str, Any]:
        """
        Process the Michelin CSV file and scrape restaurant data.
        
        Args:
            start_row: Row to start processing from (for resuming)
            max_restaurants: Maximum number of restaurants to process
            
        Returns:
            Dictionary with processing results
        """
        try:
            # Create scraping job
            job = ScrapingJob.objects.create(
                job_name=f"Michelin CSV Processing - {timezone.now().strftime('%Y-%m-%d %H:%M')}",
                status='running',
                started_at=timezone.now()
            )
            
            logger.info(f"Started scraping job: {job.job_name}")
            
            # Read CSV file
            restaurants_data = self._read_csv_file()
            total_restaurants = len(restaurants_data)
            
            if max_restaurants:
                restaurants_data = restaurants_data[:max_restaurants]
            
            if start_row > 0:
                restaurants_data = restaurants_data[start_row:]
                logger.info(f"Resuming from row {start_row}")
            
            # Update job with total URLs
            job.total_urls = len(restaurants_data)
            job.save()
            
            results = {
                'total_processed': 0,
                'successful_imports': 0,
                'successful_scrapes': 0,
                'failed_imports': 0,
                'failed_scrapes': 0,
                'errors': []
            }
            
            # Process each restaurant
            for idx, restaurant_data in enumerate(restaurants_data):
                try:
                    current_row = start_row + idx
                    logger.info(f"Processing restaurant {current_row + 1}/{total_restaurants}: {restaurant_data.get('Name', 'Unknown')}")
                    
                    # Step 1: Import basic data from CSV
                    basic_restaurant = self._import_restaurant_from_csv(restaurant_data)
                    if basic_restaurant:
                        results['successful_imports'] += 1
                        logger.info(f"Successfully imported: {basic_restaurant.name}")
                        
                        # Queue embedding update for basic restaurant data (will be enhanced if comprehensive scraping succeeds)
                        try:
                            from restaurants.tasks import update_restaurant_embeddings
                            update_restaurant_embeddings.delay(basic_restaurant.id)
                            logger.info(f"  - Queued basic embedding update for: {basic_restaurant.name}")
                        except Exception as e:
                            logger.warning(f"  - Failed to queue basic embedding update: {str(e)}")
                        
                        # Step 2: Comprehensive scrape with LLM analysis from website if URL exists
                        website_url = restaurant_data.get('WebsiteUrl', '').strip()
                        if website_url and website_url != '':
                            # Use unified scraper for complete analysis
                            scraped_data = self.restaurant_scraper.scrape_restaurant_complete(
                                website_url, basic_restaurant.name, 
                                max_images=10, save_to_db=False  # Don't auto-save, we'll integrate manually
                            )
                            
                            if scraped_data and scraped_data.get('scraping_success', False):
                                # Update restaurant with comprehensive scraped data
                                updated_restaurant = self._update_restaurant_with_comprehensive_data(
                                    basic_restaurant, scraped_data
                                )
                                if updated_restaurant:
                                    results['successful_scrapes'] += 1
                                    logger.info(f"Successfully scraped comprehensive data for: {basic_restaurant.name}")
                                    
                                    # Queue embedding update for the restaurant
                                    try:
                                        from restaurants.tasks import update_restaurant_embeddings
                                        update_restaurant_embeddings.delay(updated_restaurant.id)
                                        logger.info(f"  - Queued embedding update for: {basic_restaurant.name}")
                                    except Exception as e:
                                        logger.warning(f"  - Failed to queue embedding update: {str(e)}")
                                    
                                    # Log what was extracted
                                    llm_data = scraped_data.get('llm_analysis', {})
                                    if llm_data.get('restaurant_summary'):
                                        logger.info(f"  - Restaurant summary extracted")
                                    if llm_data.get('structured_menu'):
                                        menu_sections = len(llm_data['structured_menu'])
                                        logger.info(f"  - Menu parsed: {menu_sections} sections")
                                    if scraped_data.get('image_scraping', {}).get('successful_images', 0) > 0:
                                        img_count = scraped_data['image_scraping']['successful_images']
                                        logger.info(f"  - Images scraped: {img_count}")
                                else:
                                    results['failed_scrapes'] += 1
                                    logger.warning(f"Failed to update restaurant with comprehensive data: {basic_restaurant.name}")
                            else:
                                results['failed_scrapes'] += 1
                                error_msg = scraped_data.get('error', 'Unknown error') if scraped_data else 'No response'
                                logger.warning(f"Failed to scrape website: {website_url} - {error_msg}")
                        else:
                            logger.info(f"No website URL found for: {basic_restaurant.name}")
                    else:
                        results['failed_imports'] += 1
                        logger.error(f"Failed to import restaurant: {restaurant_data.get('Name', 'Unknown')}")
                    
                    results['total_processed'] += 1
                    
                    # Update job progress
                    job.processed_urls = results['total_processed']
                    job.successful_urls = results['successful_imports']
                    job.failed_urls = results['failed_imports']
                    job.save()
                    
                    # Check token usage to see if we should stop
                    token_summary = get_token_usage_summary()
                    if not token_summary.get('current_model'):
                        logger.warning("Token limits exhausted. Stopping processing.")
                        break
                    
                except Exception as e:
                    error_msg = f"Error processing restaurant {current_row}: {str(e)}"
                    logger.error(error_msg)
                    results['errors'].append(error_msg)
                    results['failed_imports'] += 1
            
            # Complete the job
            job.status = 'completed'
            job.completed_at = timezone.now()
            job.results = results
            job.save()
            
            logger.info(f"Completed processing. Results: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error in process_csv_file: {str(e)}")
            if 'job' in locals():
                job.status = 'failed'
                job.error_log = str(e)
                job.save()
            raise
    
    def _read_csv_file(self) -> List[Dict[str, str]]:
        """Read and parse the CSV file."""
        restaurants_data = []
        
        with open(self.csv_file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                restaurants_data.append(row)
        
        logger.info(f"Read {len(restaurants_data)} restaurants from CSV")
        return restaurants_data
    
    def _import_restaurant_from_csv(self, csv_data: Dict[str, str]) -> Optional[Restaurant]:
        """
        Import restaurant from CSV data into database.
        
        Args:
            csv_data: Dictionary with CSV row data
            
        Returns:
            Restaurant instance if successful, None otherwise
        """
        try:
            name = csv_data.get('Name', '').strip().strip('"')
            if not name:
                logger.error("Restaurant name is required")
                return None
            
            # Parse location
            location = csv_data.get('Location', '').strip()
            city, country = self._parse_location(location)
            
            # Ensure country is not blank (required field)
            if not country:
                country = 'Unknown'
            
            # Parse address
            address = csv_data.get('Address', '').strip().strip('"')
            
            # Parse price range
            price_range = self._parse_price_range(csv_data.get('Price', ''))
            
            # Parse Michelin stars
            michelin_stars = self._parse_michelin_stars(csv_data.get('Award', ''))
            
            # Parse coordinates
            latitude = self._parse_decimal(csv_data.get('Latitude'))
            longitude = self._parse_decimal(csv_data.get('Longitude'))
            
            # Check if restaurant already exists
            existing = Restaurant.objects.filter(
                name=name,
                city=city,
                country=country
            ).first()
            
            if existing:
                logger.info(f"Restaurant already exists: {name}")
                return existing
            
            # Create new restaurant
            restaurant_data = {
                'name': name,
                'description': csv_data.get('Description', '').strip().strip('"'),
                'country': country,
                'city': city,
                'address': address,
                'latitude': latitude,
                'longitude': longitude,
                'phone': csv_data.get('PhoneNumber', '').strip(),
                'website': csv_data.get('WebsiteUrl', '').strip(),
                'michelin_stars': michelin_stars,
                'cuisine_type': csv_data.get('Cuisine', '').strip(),
                'price_range': price_range,
                'original_url': csv_data.get('Url', '').strip(),
                'scraped_at': timezone.now().isoformat(),
                'scraped_content': f"Imported from Michelin CSV: {csv_data.get('Description', '')}",
            }
            
            # Create restaurant using data processor
            restaurant = self.data_processor.process_restaurant_data(restaurant_data)
            
            if restaurant:
                logger.info(f"Successfully created restaurant: {restaurant.name}")
                return restaurant
            else:
                logger.error(f"Failed to create restaurant: {name}")
                return None
                
        except Exception as e:
            logger.error(f"Error importing restaurant from CSV: {str(e)}")
            return None
    
    def _update_restaurant_with_comprehensive_data(self, restaurant: Restaurant, scraped_data: Dict[str, Any]) -> Optional[Restaurant]:
        """
        Update existing restaurant with comprehensive scraped data including LLM analysis.
        
        Args:
            restaurant: Existing restaurant instance
            scraped_data: Comprehensive scraped data dictionary
            
        Returns:
            Updated restaurant instance
        """
        try:
            from restaurants.models import MenuSection, MenuItem, RestaurantImage
            from processors.image_integrator import ImageIntegrator
            
            # Update basic scraped content
            content = scraped_data.get('content', '')
            if content:
                restaurant.scraped_content = content
                restaurant.scraped_at = timezone.now()
            
            # Process LLM analysis data
            llm_analysis = scraped_data.get('llm_analysis', {})
            
            # Update restaurant fields with LLM summary
            if llm_analysis.get('restaurant_summary'):
                summary = llm_analysis['restaurant_summary']
                
                # Update atmosphere from ambiance analysis
                if summary.get('ambiance') and len(summary['ambiance']) > len(restaurant.atmosphere or ''):
                    restaurant.atmosphere = summary['ambiance'][:100]
                
                # Update cuisine type
                if summary.get('cuisine') and not restaurant.cuisine_type:
                    restaurant.cuisine_type = summary['cuisine'][:100]
                
                # Update description with philosophy/highlights
                if summary.get('philosophy'):
                    philosophy = summary['philosophy'][:300]
                    if len(philosophy) > len(restaurant.description or ''):
                        restaurant.description = philosophy
                
                # Parse location if available
                if summary.get('location') and not restaurant.city:
                    location = summary['location']
                    if ',' in location:
                        parts = location.split(',')
                        restaurant.city = parts[0].strip()[:100]
                        if len(parts) > 1:
                            restaurant.country = parts[-1].strip()[:100]
            
            # Save restaurant updates
            restaurant.save()
            
            # Process menu data into MenuSection and MenuItem models
            menu_sections_created = 0
            menu_items_created = 0
            
            if llm_analysis.get('structured_menu'):
                # Clear existing menu data for this restaurant
                MenuSection.objects.filter(restaurant=restaurant).delete()
                
                for order, section_data in enumerate(llm_analysis['structured_menu']):
                    section_name = section_data.get('section', 'Unknown Section')
                    
                    # Create menu section
                    menu_section = MenuSection.objects.create(
                        restaurant=restaurant,
                        name=section_name[:100],
                        description='',
                        order=order
                    )
                    menu_sections_created += 1
                    
                    # Create menu items
                    items = section_data.get('items', [])
                    for item_data in items:
                        MenuItem.objects.create(
                            section=menu_section,
                            name=item_data.get('name', 'Unknown Item')[:200],
                            description=item_data.get('description', '')[:500],
                            price=item_data.get('price', '')[:20],
                            is_available=True
                        )
                        menu_items_created += 1
                
                logger.info(f"Created {menu_sections_created} menu sections and {menu_items_created} menu items")
            
            # Process images
            images_integrated = 0
            if scraped_data.get('image_scraping', {}).get('images'):
                try:
                    integrator = ImageIntegrator()
                    images_integrated = integrator.integrate_restaurant_images(
                        restaurant, 
                        scraped_data['image_scraping']['images']
                    )
                except Exception as e:
                    logger.error(f"Error integrating images: {e}")
            
            logger.info(f"Successfully updated restaurant {restaurant.name} with comprehensive data:")
            logger.info(f"  - Menu sections: {menu_sections_created}")
            logger.info(f"  - Menu items: {menu_items_created}")
            logger.info(f"  - Images integrated: {images_integrated}")
            logger.info(f"  - Atmosphere: {'Yes' if restaurant.atmosphere else 'No'}")
            logger.info(f"  - Cuisine type: {'Yes' if restaurant.cuisine_type else 'No'}")
            
            return restaurant
            
        except Exception as e:
            logger.error(f"Error updating restaurant with comprehensive data: {str(e)}")
            return None
    
    def _parse_location(self, location: str) -> tuple[str, str]:
        """Parse location string into city and country."""
        if not location:
            return '', ''
        
        # Remove quotes and split by comma
        location = location.strip().strip('"')
        parts = [part.strip() for part in location.split(',')]
        
        if len(parts) >= 2:
            city = parts[0]
            country = parts[-1]
        elif len(parts) == 1:
            city = parts[0]
            country = ''
        else:
            city = location
            country = ''
        
        return city, country
    
    def _parse_price_range(self, price: str) -> str:
        """Parse price string into standardized price range."""
        if not price:
            return ''
        
        price = price.strip()
        euro_count = price.count('€')
        dollar_count = price.count('$')
        
        if euro_count >= 4 or dollar_count >= 4:
            return '$$$$'
        elif euro_count == 3 or dollar_count == 3:
            return '$$$'
        elif euro_count == 2 or dollar_count == 2:
            return '$$'
        elif euro_count == 1 or dollar_count == 1:
            return '$'
        else:
            return ''
    
    def _parse_michelin_stars(self, award: str) -> int:
        """Parse Michelin award string into number of stars."""
        if not award:
            return 0
        
        award = award.lower().strip().strip('"')
        
        if '3 star' in award:
            return 3
        elif '2 star' in award:
            return 2
        elif '1 star' in award:
            return 1
        else:
            return 0
    
    def _parse_decimal(self, value: str) -> Optional[Decimal]:
        """Parse string to Decimal with max 6 decimal places."""
        if not value or value.strip() == '':
            return None
        
        try:
            decimal_value = Decimal(str(value).strip())
            # Round to 6 decimal places to match model constraints
            return decimal_value.quantize(Decimal('0.000001'))
        except (InvalidOperation, ValueError):
            return None


def main():
    """Main function to run the Michelin CSV processor."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    # Path to CSV file
    csv_file_path = Path(__file__).parent.parent / "ingestion" / "michelin_my_maps.csv"
    
    if not csv_file_path.exists():
        logger.error(f"CSV file not found: {csv_file_path}")
        return
    
    # Initialize processor
    processor = MichelinCSVProcessor(csv_file_path)
    
    # Process the CSV file
    try:
        results = processor.process_csv_file(
            start_row=0,  # Start from beginning, change this to resume from a specific row
            max_restaurants=None  # Process all restaurants, set a number to limit
        )
        
        print("\n" + "="*60)
        print("MICHELIN CSV PROCESSING COMPLETE")
        print("="*60)
        print(f"Total processed: {results['total_processed']}")
        print(f"Successful imports: {results['successful_imports']}")
        print(f"Successful scrapes: {results['successful_scrapes']}")
        print(f"Failed imports: {results['failed_imports']}")
        print(f"Failed scrapes: {results['failed_scrapes']}")
        
        if results['errors']:
            print(f"\nErrors encountered: {len(results['errors'])}")
            for error in results['errors'][:5]:  # Show first 5 errors
                print(f"  - {error}")
        
        print("\nCheck the Django admin or database for imported restaurants.")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        print(f"Processing failed: {str(e)}")


if __name__ == "__main__":
    main()