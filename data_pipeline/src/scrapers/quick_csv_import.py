"""
Quick CSV import script - Import Michelin restaurants without web scraping.
Use this for quick testing or when you just want the basic CSV data.
"""
import csv
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Setup portfolio paths for cross-component imports
# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Set up Django environment
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

import django
django.setup()

from restaurants.models import Restaurant

logger = logging.getLogger(__name__)


def parse_location(location: str) -> tuple[str, str]:
    """Parse location string into city and country."""
    if not location:
        return '', ''
    
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


def parse_price_range(price: str) -> str:
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


def parse_michelin_stars(award: str) -> int:
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


def parse_decimal(value: str) -> Optional[Decimal]:
    """Parse string to Decimal."""
    if not value or value.strip() == '':
        return None
    
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def quick_import_csv(csv_file_path: Path, max_restaurants: Optional[int] = None) -> Dict[str, int]:
    """
    Quick import of restaurants from CSV without web scraping.
    
    Args:
        csv_file_path: Path to the CSV file
        max_restaurants: Maximum number of restaurants to import
        
    Returns:
        Dictionary with import statistics
    """
    results = {
        'total_processed': 0,
        'successful_imports': 0,
        'failed_imports': 0,
        'already_exists': 0
    }
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for idx, row in enumerate(reader):
                if max_restaurants and idx >= max_restaurants:
                    break
                
                try:
                    name = row.get('Name', '').strip().strip('"')
                    if not name:
                        logger.warning(f"Row {idx + 1}: No name found, skipping")
                        results['failed_imports'] += 1
                        continue
                    
                    # Parse location
                    location = row.get('Location', '').strip()
                    city, country = parse_location(location)
                    
                    # Check if restaurant already exists
                    existing = Restaurant.objects.filter(
                        name=name,
                        city=city,
                        country=country
                    ).first()
                    
                    if existing:
                        logger.info(f"Restaurant already exists: {name}")
                        results['already_exists'] += 1
                        results['total_processed'] += 1
                        continue
                    
                    # Create new restaurant
                    restaurant = Restaurant.objects.create(
                        name=name,
                        description=row.get('Description', '').strip().strip('"'),
                        country=country,
                        city=city,
                        address=row.get('Address', '').strip().strip('"'),
                        latitude=parse_decimal(row.get('Latitude')),
                        longitude=parse_decimal(row.get('Longitude')),
                        phone=row.get('PhoneNumber', '').strip(),
                        website=row.get('WebsiteUrl', '').strip(),
                        michelin_stars=parse_michelin_stars(row.get('Award', '')),
                        cuisine_type=row.get('Cuisine', '').strip(),
                        price_range=parse_price_range(row.get('Price', '')),
                        original_url=row.get('Url', '').strip(),
                        scraped_at=datetime.now(),
                        scraped_content=f"Imported from Michelin CSV: {row.get('Description', '')}",
                        is_active=True
                    )
                    
                    logger.info(f"Successfully imported: {restaurant.name}")
                    results['successful_imports'] += 1
                    
                except Exception as e:
                    logger.error(f"Error importing row {idx + 1}: {str(e)}")
                    results['failed_imports'] += 1
                
                results['total_processed'] += 1
                
                # Progress logging
                if results['total_processed'] % 10 == 0:
                    logger.info(f"Processed {results['total_processed']} restaurants...")
        
        return results
        
    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}")
        raise


def main():
    """Main function for quick CSV import."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    # Path to CSV file
    csv_file_path = Path(__file__).parent.parent / "ingestion" / "michelin_my_maps.csv"
    
    if not csv_file_path.exists():
        logger.error(f"CSV file not found: {csv_file_path}")
        print(f"CSV file not found: {csv_file_path}")
        return
    
    print("=" * 60)
    print("QUICK MICHELIN CSV IMPORT")
    print("=" * 60)
    print(f"Processing: {csv_file_path}")
    print("Note: This will only import CSV data, no web scraping.")
    print()
    
    try:
        # Import the CSV data
        results = quick_import_csv(
            csv_file_path,
            max_restaurants=None  # Set a number here to limit import
        )
        
        print("\n" + "=" * 60)
        print("IMPORT COMPLETE")
        print("=" * 60)
        print(f"Total processed: {results['total_processed']}")
        print(f"Successful imports: {results['successful_imports']}")
        print(f"Already existed: {results['already_exists']}")
        print(f"Failed imports: {results['failed_imports']}")
        print()
        print("Check the Django admin at /admin/ to view imported restaurants.")
        print("To scrape additional data, use the full michelin_csv_processor.py")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Import failed: {str(e)}")
        print(f"Import failed: {str(e)}")


if __name__ == "__main__":
    main()