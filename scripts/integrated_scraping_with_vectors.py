#!/usr/bin/env python
"""
Integrated Scraping and Vector Population Pipeline

This script enhances the existing web scraping process to automatically
populate the vector database as restaurants are scraped and saved.
"""

import os
import sys
import django
import requests
import json
import logging
from pathlib import Path
from typing import Dict, Optional

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "django_app" / "src"))
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "data_pipeline" / "src" / "scrapers"))

django.setup()

from restaurants.models import Restaurant
from vector_management.vector_state_manager import VectorStateManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

RAG_SERVICE_URL = os.getenv('RAG_SERVICE_URL', 'http://localhost:8001')

class IntegratedVectorScraper:
    """Integrates vector database population with restaurant scraping."""
    
    def __init__(self):
        """Initialize the integrated scraper."""
        self.rag_url = RAG_SERVICE_URL
        self.state_manager = VectorStateManager()
        
        # Test RAG connection
        if not self._test_rag_connection():
            logger.warning("RAG service not available - vector population will be skipped")
            self.rag_available = False
        else:
            self.rag_available = True
    
    def _test_rag_connection(self) -> bool:
        """Test connection to RAG service."""
        try:
            response = requests.get(f"{self.rag_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def create_restaurant_content_for_embedding(self, restaurant: Restaurant) -> str:
        """Create rich content text for a restaurant to generate embeddings."""
        content_parts = [
            f"{restaurant.name} is a restaurant in {restaurant.city}, {restaurant.country}."
        ]
        
        if restaurant.michelin_stars > 0:
            stars_text = f"{restaurant.michelin_stars} Michelin star{'s' if restaurant.michelin_stars > 1 else ''}"
            content_parts.append(f"It has earned {stars_text}.")
        
        if restaurant.has_green_star:
            content_parts.append("A Michelin Green Star was awarded for sustainability.")
        
        if restaurant.cuisine_type and restaurant.cuisine_type.strip():
            content_parts.append(f"The cuisine type is {restaurant.cuisine_type}.")
        
        if restaurant.description and restaurant.description.strip():
            content_parts.append(f"Description: {restaurant.description}")
        
        if restaurant.atmosphere and restaurant.atmosphere.strip():
            content_parts.append(f"Atmosphere: {restaurant.atmosphere}")
            
        if restaurant.price_range and restaurant.price_range.strip():
            content_parts.append(f"Price range: {restaurant.price_range}")
        
        # Add scraped content if available (most recent and comprehensive)
        if restaurant.scraped_content and restaurant.scraped_content.strip():
            # Truncate if very long to stay within embedding limits
            scraped_content = restaurant.scraped_content
            if len(scraped_content) > 2000:
                scraped_content = scraped_content[:2000] + "..."
            content_parts.append(f"Additional details: {scraped_content}")
        
        # Add location details
        if restaurant.address and restaurant.address.strip():
            content_parts.append(f"Located at: {restaurant.address}")
        
        # Add website
        if restaurant.website:
            content_parts.append(f"Website: {restaurant.website}")
        
        return " ".join(content_parts)
    
    def create_restaurant_metadata(self, restaurant: Restaurant) -> Dict:
        """Create metadata dictionary for a restaurant."""
        metadata = {
            'restaurant_id': str(restaurant.id),
            'restaurant_name': restaurant.name,
            'city': restaurant.city,
            'country': restaurant.country,
            'michelin_stars': restaurant.michelin_stars,
            'cuisine_type': restaurant.cuisine_type or '',
            'price_range': restaurant.price_range or '',
            'is_featured': restaurant.is_featured,
            'is_active': restaurant.is_active,
            'website': restaurant.website or '',
            'source': 'integrated_scraping',
            'scraped_at': restaurant.scraped_at.isoformat() if restaurant.scraped_at else None,
            'last_updated': restaurant.updated_at.isoformat() if restaurant.updated_at else None
        }
        
        # Add location data if available
        if restaurant.latitude and restaurant.longitude:
            metadata['latitude'] = float(restaurant.latitude)
            metadata['longitude'] = float(restaurant.longitude)
        
        # Add timezone info if available
        if hasattr(restaurant, 'timezone_info') and restaurant.timezone_info:
            if isinstance(restaurant.timezone_info, dict):
                metadata['timezone'] = restaurant.timezone_info.get('local_timezone', '')
                metadata['utc_offset'] = restaurant.timezone_info.get('utc_offset', '')
        
        # Add content indicators
        metadata['has_scraped_content'] = bool(restaurant.scraped_content and restaurant.scraped_content.strip())
        metadata['has_description'] = bool(restaurant.description and restaurant.description.strip())
        metadata['content_length'] = len(restaurant.scraped_content or '')
        
        return metadata
    
    def create_embedding(self, content: str, metadata: Dict) -> bool:
        """Create an embedding via the RAG service."""
        if not self.rag_available:
            return False
        
        try:
            response = requests.post(
                f"{self.rag_url}/embeddings/generate",
                data={
                    'content': content,
                    'metadata': json.dumps(metadata)
                },
                timeout=30
            )
            
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Failed to create embedding: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating embedding: {str(e)}")
            return False
    
    def process_restaurant_for_vectors(self, restaurant: Restaurant, force_update: bool = False) -> bool:
        """Process a single restaurant for vector database embedding."""
        
        if not self.rag_available:
            logger.debug(f"Skipping vector processing for {restaurant.name} - RAG service unavailable")
            return False
        
        # Skip if restaurant doesn't have sufficient content (unless forced)
        if not force_update:
            has_content = (
                (restaurant.scraped_content and restaurant.scraped_content.strip()) or
                (restaurant.description and restaurant.description.strip())
            )
            if not has_content:
                logger.debug(f"Skipping vector processing for {restaurant.name} - insufficient content")
                return False
        
        # Create content and metadata
        content = self.create_restaurant_content_for_embedding(restaurant)
        metadata = self.create_restaurant_metadata(restaurant)
        
        # Create embedding
        if self.create_embedding(content, metadata):
            logger.info(f"✅ Created vector embedding for {restaurant.name}")
            
            # Update state tracking
            self.state_manager.vector_state["total_restaurants_processed"] += 1
            self.state_manager.vector_state["total_embeddings_created"] += 1
            self.state_manager._save_vector_state()
            
            return True
        else:
            logger.error(f"❌ Failed to create vector embedding for {restaurant.name}")
            
            # Update error tracking
            self.state_manager.vector_state["failed_embeddings"] += 1
            self.state_manager._save_vector_state()
            
            return False
    
    def bulk_process_existing_restaurants(self, limit: int = None, force_update: bool = False) -> Dict:
        """Process existing restaurants in bulk for vector embeddings."""
        
        if not self.rag_available:
            logger.error("RAG service not available for bulk processing")
            return {'processed': 0, 'success': 0, 'errors': 0}
        
        logger.info("Starting bulk vector processing of existing restaurants...")
        
        # Get restaurants to process
        restaurants = Restaurant.objects.filter(is_active=True)
        
        if not force_update:
            # Only process restaurants with substantial content
            restaurants = restaurants.filter(
                scraped_content__isnull=False
            ).exclude(scraped_content='')
        
        if limit:
            restaurants = restaurants[:limit]
        
        total_count = restaurants.count()
        logger.info(f"Processing {total_count} restaurants for vector embeddings...")
        
        # Process restaurants
        processed = 0
        success = 0
        errors = 0
        
        for i, restaurant in enumerate(restaurants, 1):
            logger.info(f"Processing {i}/{total_count}: {restaurant.name}")
            
            if self.process_restaurant_for_vectors(restaurant, force_update):
                success += 1
            else:
                errors += 1
            
            processed += 1
            
            # Progress reporting
            if processed % 25 == 0:
                progress = (processed / total_count) * 100
                logger.info(f"Progress: {processed}/{total_count} ({progress:.1f}%) - Success: {success}, Errors: {errors}")
        
        logger.info(f"Bulk processing completed: {success} success, {errors} errors")
        
        return {
            'processed': processed,
            'success': success,
            'errors': errors
        }
    
    def get_integration_status(self) -> Dict:
        """Get status of the integrated scraping and vector system."""
        
        # Get restaurant counts
        total_restaurants = Restaurant.objects.count()
        active_restaurants = Restaurant.objects.filter(is_active=True).count()
        scraped_restaurants = Restaurant.objects.filter(
            scraped_content__isnull=False
        ).exclude(scraped_content='').count()
        
        # Get vector state
        vector_summary = self.state_manager.get_progress_summary()
        
        return {
            'rag_service_available': self.rag_available,
            'restaurants': {
                'total': total_restaurants,
                'active': active_restaurants,
                'with_scraped_content': scraped_restaurants,
                'ready_for_vectors': scraped_restaurants
            },
            'vector_database': vector_summary['vector_database'],
            'csv_processing': vector_summary['csv_processing'],
            'scraped_docs': vector_summary['scraped_docs']
        }


# Hook function that can be called from the scraper
def post_scraping_vector_hook(restaurant: Restaurant) -> bool:
    """
    Hook function to be called after a restaurant is scraped and saved.
    
    This can be integrated into the existing scraping pipeline to automatically
    create vector embeddings for newly scraped restaurants.
    
    Args:
        restaurant: The Restaurant object that was just scraped/updated
        
    Returns:
        bool: True if vector embedding was created successfully
    """
    try:
        scraper = IntegratedVectorScraper()
        return scraper.process_restaurant_for_vectors(restaurant)
    except Exception as e:
        logger.error(f"Vector hook failed for {restaurant.name}: {e}")
        return False


def main():
    """Main function for integrated scraping and vector operations."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Integrated scraping and vector database operations')
    parser.add_argument('--status', action='store_true',
                       help='Show integration status')
    parser.add_argument('--bulk-process', type=int, metavar='LIMIT',
                       help='Process existing restaurants for vector embeddings (optional limit)')
    parser.add_argument('--force-update', action='store_true',
                       help='Force update all restaurants even without content')
    parser.add_argument('--test-restaurant', type=str, metavar='NAME',
                       help='Test vector processing for a specific restaurant')
    
    args = parser.parse_args()
    
    scraper = IntegratedVectorScraper()
    
    if args.status:
        status = scraper.get_integration_status()
        
        print("\n🔗 Integrated Scraping & Vector System Status:")
        print(f"   RAG Service Available: {'✅' if status['rag_service_available'] else '❌'}")
        
        restaurants = status['restaurants']
        print(f"\n📊 Restaurant Database:")
        print(f"   Total Restaurants: {restaurants['total']:,}")
        print(f"   Active Restaurants: {restaurants['active']:,}")
        print(f"   With Scraped Content: {restaurants['with_scraped_content']:,}")
        print(f"   Ready for Vectors: {restaurants['ready_for_vectors']:,}")
        
        vector_db = status['vector_database']
        print(f"\n🔢 Vector Database:")
        print(f"   Total Embeddings Created: {vector_db['total_embeddings_created']:,}")
        print(f"   Failed Embeddings: {vector_db['failed_embeddings']:,}")
        print(f"   Current Session: {vector_db['current_session']}")
        
        csv_proc = status['csv_processing']
        print(f"\n📄 CSV Processing:")
        print(f"   Status: {csv_proc['status']}")
        print(f"   Progress: {csv_proc['progress_percentage']}%")
        print(f"   Processed: {csv_proc['processed']:,}")
        
        return
    
    if args.test_restaurant:
        try:
            restaurant = Restaurant.objects.get(
                name__icontains=args.test_restaurant,
                is_active=True
            )
            print(f"\n🧪 Testing vector processing for: {restaurant.name}")
            
            success = scraper.process_restaurant_for_vectors(restaurant, force_update=True)
            if success:
                print("✅ Vector embedding created successfully")
            else:
                print("❌ Vector embedding failed")
                
        except Restaurant.DoesNotExist:
            print(f"❌ Restaurant not found: {args.test_restaurant}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        return
    
    if args.bulk_process is not None:
        results = scraper.bulk_process_existing_restaurants(
            limit=args.bulk_process if args.bulk_process > 0 else None,
            force_update=args.force_update
        )
        
        print(f"\n🎯 Bulk Processing Results:")
        print(f"   Processed: {results['processed']}")
        print(f"   Successful: {results['success']}")
        print(f"   Errors: {results['errors']}")
        
        return
    
    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()