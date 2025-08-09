"""
Data processor for handling scraped restaurant data and saving to Django database.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal, InvalidOperation

# Setup portfolio paths for cross-component imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

import django
django.setup()

from restaurants.models import (
    Restaurant, Chef, MenuSection, MenuItem, 
    RestaurantImage, ScrapingJob
)

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    Processes scraped restaurant data and saves it to the Django database.
    """
    
    def __init__(self):
        """Initialize the data processor."""
        logger.info("Data processor initialized")
    
    def process_restaurant_data(self, scraped_data: Dict[str, Any]) -> Optional[Restaurant]:
        """
        Process scraped restaurant data and save to database.
        
        Args:
            scraped_data: Dictionary containing scraped restaurant data
            
        Returns:
            Restaurant instance if successful, None otherwise
        """
        try:
            # Extract basic restaurant information
            restaurant_data = self._extract_restaurant_fields(scraped_data)
            
            if not restaurant_data:
                logger.warning("Could not extract restaurant fields from scraped data")
                return None
            
            # Create or update restaurant
            restaurant = self._create_or_update_restaurant(restaurant_data)
            
            if not restaurant:
                logger.error("Failed to create or update restaurant")
                return None
            
            # Process related data
            self._process_chefs(restaurant, scraped_data.get('chefs', []))
            self._process_menu_sections(restaurant, scraped_data.get('menu_sections', []))
            
            logger.info(f"Successfully processed restaurant: {restaurant.name}")
            return restaurant
            
        except Exception as e:
            logger.error(f"Error processing restaurant data: {str(e)}")
            return None
    
    def _extract_restaurant_fields(self, scraped_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract and validate restaurant fields from scraped data.
        
        Args:
            scraped_data: Raw scraped data
            
        Returns:
            Dictionary with validated restaurant fields
        """
        try:
            # Required fields
            name = scraped_data.get('name', '').strip()
            if not name:
                logger.error("Restaurant name is required")
                return None
            
            # Basic information
            restaurant_data = {
                'name': name,
                'description': scraped_data.get('description', '').strip(),
                'country': scraped_data.get('country', '').strip(),
                'city': scraped_data.get('city', '').strip(),
                'address': scraped_data.get('address', '').strip(),
                'phone': scraped_data.get('phone', '').strip(),
                'email': scraped_data.get('email', '').strip(),
                'website': scraped_data.get('website', '').strip(),
                'cuisine_type': scraped_data.get('cuisine_type', '').strip(),
                'atmosphere': scraped_data.get('atmosphere', '').strip(),
                'opening_hours': scraped_data.get('opening_hours', '').strip(),
                'original_url': scraped_data.get('original_url', '').strip(),
                'scraped_content': scraped_data.get('scraped_content', '').strip(),
                'is_active': True,
                'is_featured': False,
            }
            
            # Handle coordinates
            latitude = scraped_data.get('latitude')
            longitude = scraped_data.get('longitude')
            
            if latitude is not None:
                try:
                    restaurant_data['latitude'] = Decimal(str(latitude))
                except (InvalidOperation, ValueError):
                    restaurant_data['latitude'] = None
            
            if longitude is not None:
                try:
                    restaurant_data['longitude'] = Decimal(str(longitude))
                except (InvalidOperation, ValueError):
                    restaurant_data['longitude'] = None
            
            # Handle Michelin stars
            michelin_stars = scraped_data.get('michelin_stars', 0)
            try:
                restaurant_data['michelin_stars'] = max(0, min(3, int(michelin_stars)))
            except (ValueError, TypeError):
                restaurant_data['michelin_stars'] = 0
            
            # Handle price range
            price_range = scraped_data.get('price_range', '').strip()
            valid_price_ranges = ['$', '$$', '$$$', '$$$$']
            if price_range in valid_price_ranges:
                restaurant_data['price_range'] = price_range
            else:
                restaurant_data['price_range'] = ''
            
            # Handle seating capacity
            seating_capacity = scraped_data.get('seating_capacity')
            if seating_capacity is not None:
                try:
                    restaurant_data['seating_capacity'] = int(seating_capacity)
                except (ValueError, TypeError):
                    restaurant_data['seating_capacity'] = None
            
            # Handle private dining
            restaurant_data['has_private_dining'] = bool(scraped_data.get('has_private_dining', False))
            
            # Handle scraped_at timestamp
            scraped_at = scraped_data.get('scraped_at')
            if scraped_at:
                try:
                    if isinstance(scraped_at, str):
                        # Parse ISO format and ensure timezone-aware
                        parsed_dt = datetime.fromisoformat(scraped_at.replace('Z', '+00:00'))
                        if parsed_dt.tzinfo is None:
                            # If naive, make it timezone-aware in UTC
                            restaurant_data['scraped_at'] = timezone.make_aware(parsed_dt, timezone.utc)
                        else:
                            restaurant_data['scraped_at'] = parsed_dt
                    else:
                        # Ensure datetime object is timezone-aware
                        if hasattr(scraped_at, 'tzinfo') and scraped_at.tzinfo is None:
                            restaurant_data['scraped_at'] = timezone.make_aware(scraped_at, timezone.utc)
                        else:
                            restaurant_data['scraped_at'] = scraped_at
                except (ValueError, TypeError):
                    restaurant_data['scraped_at'] = timezone.now()
            else:
                restaurant_data['scraped_at'] = timezone.now()
            
            return restaurant_data
            
        except Exception as e:
            logger.error(f"Error extracting restaurant fields: {str(e)}")
            return None
    
    def _create_or_update_restaurant(self, restaurant_data: Dict[str, Any]) -> Optional[Restaurant]:
        """
        Create or update a restaurant in the database.
        
        Args:
            restaurant_data: Validated restaurant data
            
        Returns:
            Restaurant instance if successful, None otherwise
        """
        try:
            # Generate slug
            base_slug = slugify(f"{restaurant_data['name']}-{restaurant_data['city']}")
            slug = base_slug
            
            # Check if restaurant already exists
            existing_restaurant = None
            
            # Try to find by URL first
            if restaurant_data.get('original_url'):
                existing_restaurant = Restaurant.objects.filter(
                    original_url=restaurant_data['original_url']
                ).first()
            
            # If not found by URL, try by name and city
            if not existing_restaurant:
                existing_restaurant = Restaurant.objects.filter(
                    name=restaurant_data['name'],
                    city=restaurant_data['city'],
                    country=restaurant_data['country']
                ).first()
            
            if existing_restaurant:
                # Update existing restaurant
                logger.info(f"Updating existing restaurant: {existing_restaurant.name}")
                
                for field, value in restaurant_data.items():
                    if field != 'slug':  # Don't update slug
                        setattr(existing_restaurant, field, value)
                
                # Update timestamp
                existing_restaurant.updated_at = timezone.now()
                
                try:
                    existing_restaurant.full_clean()
                    existing_restaurant.save()
                    return existing_restaurant
                except ValidationError as e:
                    logger.error(f"Validation error updating restaurant: {e}")
                    return None
            
            else:
                # Create new restaurant
                logger.info(f"Creating new restaurant: {restaurant_data['name']}")
                
                # Ensure unique slug
                counter = 1
                while Restaurant.objects.filter(slug=slug).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                
                restaurant_data['slug'] = slug
                
                try:
                    restaurant = Restaurant(**restaurant_data)
                    restaurant.full_clean()
                    restaurant.save()
                    return restaurant
                except ValidationError as e:
                    logger.error(f"Validation error creating restaurant: {e}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error creating/updating restaurant: {str(e)}")
            return None
    
    def _process_chefs(self, restaurant: Restaurant, chefs_data: List[Dict[str, Any]]) -> None:
        """
        Process chef data and save to database.
        
        Args:
            restaurant: Restaurant instance
            chefs_data: List of chef data dictionaries
        """
        try:
            if not chefs_data:
                return
            
            # Remove existing chefs for this restaurant
            restaurant.chefs.all().delete()
            
            for chef_data in chefs_data:
                try:
                    # Validate required fields
                    first_name = chef_data.get('first_name', '').strip()
                    last_name = chef_data.get('last_name', '').strip()
                    
                    if not first_name and not last_name:
                        logger.warning("Chef data missing name, skipping")
                        continue
                    
                    # Validate position
                    position = chef_data.get('position', 'chef_de_partie')
                    valid_positions = [
                        'head_chef', 'executive_chef', 'sous_chef', 
                        'pastry_chef', 'chef_de_partie'
                    ]
                    if position not in valid_positions:
                        position = 'chef_de_partie'
                    
                    # Handle years_experience
                    years_experience = chef_data.get('years_experience')
                    if years_experience is not None:
                        try:
                            years_experience = int(years_experience)
                        except (ValueError, TypeError):
                            years_experience = None
                    
                    # Create chef
                    chef = Chef(
                        restaurant=restaurant,
                        first_name=first_name,
                        last_name=last_name,
                        position=position,
                        biography=chef_data.get('biography', '').strip(),
                        years_experience=years_experience,
                        awards=chef_data.get('awards', '').strip()
                    )
                    
                    chef.full_clean()
                    chef.save()
                    
                    logger.info(f"Created chef: {chef.full_name}")
                    
                except ValidationError as e:
                    logger.error(f"Validation error creating chef: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error creating chef: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error processing chefs: {str(e)}")
    
    def _process_menu_sections(self, restaurant: Restaurant, menu_sections_data: List[Dict[str, Any]]) -> None:
        """
        Process menu section data and save to database.
        
        Args:
            restaurant: Restaurant instance
            menu_sections_data: List of menu section data dictionaries
        """
        try:
            if not menu_sections_data:
                return
            
            # Remove existing menu sections for this restaurant
            restaurant.menu_sections.all().delete()
            
            for order, section_data in enumerate(menu_sections_data):
                try:
                    # Validate required fields
                    section_name = section_data.get('name', '').strip()
                    if not section_name:
                        logger.warning("Menu section missing name, skipping")
                        continue
                    
                    # Create menu section
                    menu_section = MenuSection(
                        restaurant=restaurant,
                        name=section_name,
                        description=section_data.get('description', '').strip(),
                        order=order
                    )
                    
                    menu_section.full_clean()
                    menu_section.save()
                    
                    # Process menu items
                    items_data = section_data.get('items', [])
                    self._process_menu_items(menu_section, items_data)
                    
                    logger.info(f"Created menu section: {section_name}")
                    
                except ValidationError as e:
                    logger.error(f"Validation error creating menu section: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error creating menu section: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error processing menu sections: {str(e)}")
    
    def _process_menu_items(self, menu_section: MenuSection, items_data: List[Dict[str, Any]]) -> None:
        """
        Process menu item data and save to database.
        
        Args:
            menu_section: MenuSection instance
            items_data: List of menu item data dictionaries
        """
        try:
            if not items_data:
                return
            
            for item_data in items_data:
                try:
                    # Validate required fields
                    item_name = item_data.get('name', '').strip()
                    if not item_name:
                        logger.warning("Menu item missing name, skipping")
                        continue
                    
                    # Create menu item
                    menu_item = MenuItem(
                        section=menu_section,
                        name=item_name,
                        description=item_data.get('description', '').strip(),
                        price=item_data.get('price', '').strip(),
                        is_vegetarian=bool(item_data.get('is_vegetarian', False)),
                        is_vegan=bool(item_data.get('is_vegan', False)),
                        is_gluten_free=bool(item_data.get('is_gluten_free', False)),
                        allergens=item_data.get('allergens', '').strip(),
                        is_available=bool(item_data.get('is_available', True)),
                        is_signature=bool(item_data.get('is_signature', False))
                    )
                    
                    menu_item.full_clean()
                    menu_item.save()
                    
                    logger.debug(f"Created menu item: {item_name}")
                    
                except ValidationError as e:
                    logger.error(f"Validation error creating menu item: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error creating menu item: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error processing menu items: {str(e)}")
    
    def process_batch_data(self, scraped_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process multiple scraped restaurant data in batch.
        
        Args:
            scraped_data_list: List of scraped restaurant data dictionaries
            
        Returns:
            Dictionary with processing results
        """
        results = {
            'total': len(scraped_data_list),
            'successful': 0,
            'failed': 0,
            'created': 0,
            'updated': 0,
            'errors': []
        }
        
        for scraped_data in scraped_data_list:
            try:
                restaurant = self.process_restaurant_data(scraped_data)
                
                if restaurant:
                    results['successful'] += 1
                    
                    # Check if it was created or updated
                    if restaurant.created_at == restaurant.updated_at:
                        results['created'] += 1
                    else:
                        results['updated'] += 1
                        
                    logger.info(f"Successfully processed: {restaurant.name}")
                else:
                    results['failed'] += 1
                    error_msg = f"Failed to process restaurant: {scraped_data.get('name', 'Unknown')}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
                    
            except Exception as e:
                results['failed'] += 1
                error_msg = f"Error processing restaurant {scraped_data.get('name', 'Unknown')}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(error_msg)
        
        logger.info(f"Batch processing completed: {results['successful']} successful, {results['failed']} failed")
        return results
    
    def get_restaurant_by_url(self, url: str) -> Optional[Restaurant]:
        """
        Get restaurant by original URL.
        
        Args:
            url: Original URL
            
        Returns:
            Restaurant instance if found, None otherwise
        """
        try:
            return Restaurant.objects.filter(original_url=url).first()
        except Exception as e:
            logger.error(f"Error getting restaurant by URL: {str(e)}")
            return None
    
    def get_restaurants_for_update(self, days_old: int = 7) -> List[Restaurant]:
        """
        Get restaurants that need updating based on age.
        
        Args:
            days_old: Number of days old to consider for update
            
        Returns:
            List of restaurants that need updating
        """
        try:
            cutoff_date = timezone.now() - timezone.timedelta(days=days_old)
            return Restaurant.objects.filter(
                scraped_at__lt=cutoff_date,
                is_active=True
            ).order_by('scraped_at')
        except Exception as e:
            logger.error(f"Error getting restaurants for update: {str(e)}")
            return []
    
    def mark_restaurant_as_inactive(self, restaurant_id: str) -> bool:
        """
        Mark a restaurant as inactive.
        
        Args:
            restaurant_id: Restaurant ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id)
            restaurant.is_active = False
            restaurant.save()
            logger.info(f"Marked restaurant as inactive: {restaurant.name}")
            return True
        except Restaurant.DoesNotExist:
            logger.error(f"Restaurant not found: {restaurant_id}")
            return False
        except Exception as e:
            logger.error(f"Error marking restaurant as inactive: {str(e)}")
            return False