#!/usr/bin/env python
"""
Vector Database Population Script

This script populates the vector database with embeddings from restaurant data.
It can be run:
1. Initially to create embeddings from existing basic restaurant data
2. Periodically to update with newly scraped content
3. As part of the scraping pipeline to add embeddings for new data
"""

import os
import sys
import django
import requests
import json
import logging
from pathlib import Path

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "django_app" / "src"))
sys.path.insert(0, str(project_root / "shared" / "src"))

django.setup()

from restaurants.models import Restaurant
from token_management.token_manager import init_token_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize token manager
TOKEN_DIR = project_root / "shared" / "token_management"
init_token_manager(TOKEN_DIR)

RAG_SERVICE_URL = os.getenv('RAG_SERVICE_URL', 'http://localhost:8001')

class VectorDatabasePopulator:
    """Handles populating and updating the vector database with restaurant embeddings."""
    
    def __init__(self):
        self.rag_url = RAG_SERVICE_URL
        self.processed_count = 0
        self.error_count = 0
    
    def create_restaurant_embedding_content(self, restaurant):
        """Create rich content text for a restaurant to generate embeddings."""
        
        # Build comprehensive content from available data
        content_parts = [
            f"{restaurant.name} is a restaurant in {restaurant.city}, {restaurant.country}."
        ]
        
        if restaurant.michelin_stars > 0:
            stars_text = f"{restaurant.michelin_stars} Michelin star{'s' if restaurant.michelin_stars > 1 else ''}"
            content_parts.append(f"It has earned {stars_text}.")
        
        if restaurant.has_green_star:
            content_parts.append("A Michelin Green Star was awarded for sustainability.")
        
        if restaurant.cuisine_type and restaurant.cuisine_type != "":
            content_parts.append(f"The cuisine type is {restaurant.cuisine_type}.")
        
        if restaurant.description and restaurant.description.strip():
            content_parts.append(f"Description: {restaurant.description}")
        
        if restaurant.atmosphere and restaurant.atmosphere.strip():
            content_parts.append(f"Atmosphere: {restaurant.atmosphere}")
            
        if restaurant.price_range and restaurant.price_range.strip():
            content_parts.append(f"Price range: {restaurant.price_range}")
        
        # Add scraped content if available
        if restaurant.scraped_content and restaurant.scraped_content.strip():
            content_parts.append(f"Additional details: {restaurant.scraped_content}")
        
        # Add location details
        if restaurant.address and restaurant.address.strip():
            content_parts.append(f"Located at: {restaurant.address}")
        
        return " ".join(content_parts)
    
    def create_restaurant_metadata(self, restaurant):
        """Create metadata dictionary for a restaurant."""
        return {
            'restaurant_id': str(restaurant.id),
            'restaurant_name': restaurant.name,
            'city': restaurant.city,
            'country': restaurant.country,
            'michelin_stars': restaurant.michelin_stars,
            'cuisine_type': restaurant.cuisine_type,
            'price_range': restaurant.price_range,
            'is_featured': restaurant.is_featured,
            'latitude': float(restaurant.latitude) if restaurant.latitude else None,
            'longitude': float(restaurant.longitude) if restaurant.longitude else None,
            'website': restaurant.website,
            'has_scraped_content': bool(restaurant.scraped_content and restaurant.scraped_content.strip()),
            'last_updated': restaurant.updated_at.isoformat() if restaurant.updated_at else None
        }
    
    def create_embedding(self, content, metadata):
        """Create an embedding via the RAG service."""
        try:
            # Send as form data since FastAPI expects query/form parameters
            response = requests.post(
                f"{self.rag_url}/embeddings/generate",
                data={
                    'content': content,
                    'metadata': json.dumps(metadata)  # Convert dict to JSON string
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
    
    def populate_all_restaurants(self, force_update=False):
        """Populate embeddings for all restaurants."""
        logger.info("Starting vector database population...")
        
        # Get all active restaurants
        restaurants = Restaurant.objects.filter(is_active=True)
        total_count = restaurants.count()
        
        logger.info(f"Found {total_count} active restaurants to process")
        
        for i, restaurant in enumerate(restaurants, 1):
            logger.info(f"Processing restaurant {i}/{total_count}: {restaurant.name}")
            
            # Create content and metadata
            content = self.create_restaurant_embedding_content(restaurant)
            metadata = self.create_restaurant_metadata(restaurant)
            
            # Create embedding
            if self.create_embedding(content, metadata):
                self.processed_count += 1
                logger.info(f"✓ Created embedding for {restaurant.name}")
            else:
                self.error_count += 1
                logger.error(f"✗ Failed to create embedding for {restaurant.name}")
        
        logger.info(f"Population complete: {self.processed_count} processed, {self.error_count} errors")
        return self.processed_count, self.error_count
    
    def populate_updated_restaurants(self, since_hours=24):
        """Populate embeddings for recently updated restaurants."""
        from django.utils import timezone
        from datetime import timedelta
        
        cutoff_time = timezone.now() - timedelta(hours=since_hours)
        
        restaurants = Restaurant.objects.filter(
            is_active=True,
            updated_at__gte=cutoff_time
        )
        
        count = restaurants.count()
        logger.info(f"Found {count} restaurants updated in last {since_hours} hours")
        
        for restaurant in restaurants:
            content = self.create_restaurant_embedding_content(restaurant)
            metadata = self.create_restaurant_metadata(restaurant)
            
            if self.create_embedding(content, metadata):
                self.processed_count += 1
                logger.info(f"✓ Updated embedding for {restaurant.name}")
            else:
                self.error_count += 1
                logger.error(f"✗ Failed to update embedding for {restaurant.name}")
        
        return self.processed_count, self.error_count
    
    def test_search(self, query="French restaurant"):
        """Test vector database search functionality."""
        try:
            response = requests.get(
                f"{self.rag_url}/embeddings/search",
                params={'query': query, 'k': 5},
                timeout=30
            )
            
            if response.status_code == 200:
                results = response.json()
                logger.info(f"Search test successful: found {len(results['results'])} results for '{query}'")
                
                for i, result in enumerate(results['results'][:3], 1):
                    name = result['metadata'].get('restaurant_name', 'Unknown')
                    location = f"{result['metadata'].get('city', '')}, {result['metadata'].get('country', '')}"
                    logger.info(f"  {i}. {name} in {location}")
                
                return len(results['results'])
            else:
                logger.error(f"Search test failed: {response.status_code}")
                return 0
                
        except Exception as e:
            logger.error(f"Search test error: {str(e)}")
            return 0


def main():
    """Main function to run vector database population."""
    
    import argparse
    
    parser = argparse.ArgumentParser(description='Populate vector database with restaurant embeddings')
    parser.add_argument('--mode', choices=['all', 'updated', 'test'], default='all',
                       help='Population mode: all (all restaurants), updated (recently updated), test (search test)')
    parser.add_argument('--since-hours', type=int, default=24,
                       help='Hours to look back for updated restaurants (default: 24)')
    parser.add_argument('--force', action='store_true',
                       help='Force update even if embeddings exist')
    
    args = parser.parse_args()
    
    populator = VectorDatabasePopulator()
    
    try:
        if args.mode == 'all':
            processed, errors = populator.populate_all_restaurants(force_update=args.force)
            print(f"\n🎯 Population Summary:")
            print(f"   Processed: {processed}")
            print(f"   Errors: {errors}")
            
        elif args.mode == 'updated':
            processed, errors = populator.populate_updated_restaurants(since_hours=args.since_hours)
            print(f"\n🎯 Update Summary:")
            print(f"   Processed: {processed}")
            print(f"   Errors: {errors}")
            
        elif args.mode == 'test':
            # Test with different queries
            test_queries = [
                "French restaurant in Paris",
                "3 Michelin star restaurant",
                "Italian cuisine",
                "restaurant in New York"
            ]
            
            print("\n🔍 Testing Vector Database Search:")
            for query in test_queries:
                count = populator.test_search(query)
                print(f"   '{query}': {count} results")
        
        # Always run a quick search test at the end
        if args.mode != 'test':
            print("\n🔍 Running search validation...")
            populator.test_search("Michelin restaurant")
            
    except KeyboardInterrupt:
        logger.info("Population interrupted by user")
    except Exception as e:
        logger.error(f"Population failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()