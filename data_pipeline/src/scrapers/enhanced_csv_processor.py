"""
Enhanced CSV Processor with improved scraping techniques.
"""

import sys
import os
from pathlib import Path

# Setup paths
# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Override database host
os.environ['DATABASE_HOST'] = 'localhost'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

import django
django.setup()

from restaurants.models import Restaurant
from scrapers.enhanced_restaurant_scraper import EnhancedRestaurantScraper
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def enhanced_scrape_restaurants(max_restaurants: int = 100) -> dict:
    """
    Scrape restaurants using the enhanced scraper and update database.
    
    Args:
        max_restaurants: Maximum number of restaurants to process
        
    Returns:
        Dictionary with results
    """
    # Get restaurants that need scraping
    restaurants_to_scrape = Restaurant.objects.filter(
        website__isnull=False
    ).exclude(website='').filter(
        scraped_content__isnull=True
    ).union(
        Restaurant.objects.filter(website__isnull=False).exclude(website='').filter(
            scraped_content=''
        )
    ).union(
        Restaurant.objects.filter(website__isnull=False).exclude(website='').filter(
            scraped_content__startswith='Imported from Michelin CSV'
        )
    )[:max_restaurants]
    
    logger.info(f"Found {restaurants_to_scrape.count()} restaurants to scrape")
    
    # Initialize enhanced scraper
    scraper = EnhancedRestaurantScraper()
    
    results = {
        'total_attempted': 0,
        'successful_updates': 0,
        'failed_scrapes': 0,
        'errors': []
    }
    
    for i, restaurant in enumerate(restaurants_to_scrape):
        try:
            logger.info(f"Processing {i+1}/{len(restaurants_to_scrape)}: {restaurant.name}")
            results['total_attempted'] += 1
            
            # Scrape the restaurant website
            scraped_data = scraper.scrape_restaurant(restaurant.website, use_selenium=True)
            
            if scraped_data and scraped_data.get('quality_score', 0) > 0.2:
                # Update restaurant with scraped data
                restaurant.scraped_content = scraped_data.get('content', '')
                restaurant.scraped_at = scraped_data.get('scraped_at')
                
                # Update additional fields if available
                if scraped_data.get('ai_enhanced'):
                    ai_data = scraped_data['ai_enhanced']
                    
                    # Update description if AI provided a better one
                    if ai_data.get('description') and len(ai_data['description']) > len(restaurant.description or ''):
                        restaurant.description = ai_data['description']
                    
                    # Update cuisine type if not set
                    if ai_data.get('cuisine_type') and not restaurant.cuisine_type:
                        restaurant.cuisine_type = ai_data['cuisine_type']
                    
                    # Update atmosphere if not set
                    if ai_data.get('atmosphere'):
                        restaurant.atmosphere = ai_data['atmosphere']
                    
                    # Update price range if not set
                    if ai_data.get('price_range') and not restaurant.price_range:
                        restaurant.price_range = ai_data['price_range']
                
                # Save contact info if extracted
                if scraped_data.get('contact_info'):
                    contact = scraped_data['contact_info']
                    if contact.get('phone') and not restaurant.phone:
                        restaurant.phone = contact['phone']
                
                # Save opening hours if extracted
                if scraped_data.get('opening_hours') and not restaurant.opening_hours:
                    restaurant.opening_hours = scraped_data['opening_hours']
                
                restaurant.save()
                results['successful_updates'] += 1
                logger.info(f"✅ Successfully updated {restaurant.name} (Quality: {scraped_data.get('quality_score', 0):.2f})")
                
            else:
                results['failed_scrapes'] += 1
                logger.warning(f"❌ Failed to scrape meaningful content for {restaurant.name}")
                
        except Exception as e:
            error_msg = f"Error processing {restaurant.name}: {str(e)}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
            results['failed_scrapes'] += 1
    
    # Calculate success rate
    if results['total_attempted'] > 0:
        success_rate = (results['successful_updates'] / results['total_attempted']) * 100
        results['success_rate'] = success_rate
    
    logger.info(f"Enhanced scraping completed: {results['successful_updates']}/{results['total_attempted']} successful ({results.get('success_rate', 0):.1f}%)")
    return results

if __name__ == "__main__":
    print("Starting enhanced restaurant scraping...")
    
    # Process 50 restaurants as a test
    results = enhanced_scrape_restaurants(max_restaurants=50)
    
    print("\n" + "="*60)
    print("ENHANCED SCRAPING RESULTS")
    print("="*60)
    print(f"Total attempted: {results['total_attempted']}")
    print(f"Successful updates: {results['successful_updates']}")
    print(f"Failed scrapes: {results['failed_scrapes']}")
    print(f"Success rate: {results.get('success_rate', 0):.1f}%")
    
    if results.get('errors'):
        print(f"\nErrors encountered: {len(results['errors'])}")
        for error in results['errors'][:5]:
            print(f"  - {error}")
    
    print("\nEnhanced scraping completed!")