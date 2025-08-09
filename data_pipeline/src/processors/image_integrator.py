"""
Image Integration Utility - Transfer scraped images to Django database.

This module provides functionality to transfer images from comprehensive scraper
local storage to Django's RestaurantImage model with proper categorization.
"""

import os
import shutil
import logging
# base64 no longer needed - handled by ImageAI service
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json
from PIL import Image

# Django setup
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['django'])

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from restaurants.models import Restaurant, RestaurantImage
# OpenAI integration now via ImageAI service
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)
# OpenAI client now handled by ImageAI service


class ImageIntegrator:
    """Transfer scraped images to Django database with AI categorization."""
    
    def __init__(self, scraped_images_dir: Path = None):
        """Initialize the image integrator."""
        if scraped_images_dir is None:
            scraped_images_dir = Path(__file__).parent.parent.parent.parent / "comprehensive_scraped_images"
        
        self.scraped_images_dir = scraped_images_dir
        logger.info(f"Image integrator initialized with directory: {self.scraped_images_dir}")
    
    def integrate_restaurant_images(self, restaurant: Restaurant, image_data: List[Dict]) -> int:
        """
        Integrate scraped images for a restaurant into Django database.
        
        Args:
            restaurant: Restaurant instance
            image_data: List of image dictionaries from comprehensive scraper
            
        Returns:
            Number of images successfully integrated
        """
        integrated_count = 0
        
        try:
            logger.info(f"Integrating {len(image_data)} images for {restaurant.name}")
            
            for idx, img_info in enumerate(image_data):
                try:
                    if img_info.get('status') != 'completed':
                        continue
                    
                    local_path = Path(img_info.get('local_path', ''))
                    if not local_path.exists():
                        logger.warning(f"Image file not found: {local_path}")
                        continue
                    
                    # Check if image already exists
                    existing = RestaurantImage.objects.filter(
                        restaurant=restaurant,
                        source_url=img_info.get('source_url', '')
                    ).first()
                    
                    if existing:
                        logger.info(f"Image already exists in database: {img_info.get('filename', '')}")
                        continue
                    
                    # Create RestaurantImage instance
                    restaurant_image = self._create_restaurant_image(restaurant, img_info, local_path)
                    
                    if restaurant_image:
                        integrated_count += 1
                        logger.info(f"✅ Integrated image {idx+1}/{len(image_data)}: {restaurant_image.get_display_name()}")
                    
                except Exception as e:
                    logger.error(f"Error integrating image {idx+1}: {e}")
            
            logger.info(f"Successfully integrated {integrated_count}/{len(image_data)} images for {restaurant.name}")
            return integrated_count
            
        except Exception as e:
            logger.error(f"Error integrating images for {restaurant.name}: {e}")
            return 0
    
    def _create_restaurant_image(self, restaurant: Restaurant, img_info: Dict, local_path: Path) -> Optional[RestaurantImage]:
        """Create a RestaurantImage instance from scraped data."""
        try:
            # Read image file
            with open(local_path, 'rb') as img_file:
                image_content = img_file.read()
            
            # Get image dimensions
            pil_image = Image.open(local_path)
            width, height = pil_image.size
            
            # Create Django file
            filename = img_info.get('filename', local_path.name)
            django_file = ContentFile(image_content, name=filename)
            
            # Determine AI category and confidence
            ai_category = img_info.get('ai_category', 'uncategorized')
            ai_labels = img_info.get('ai_labels', [])
            ai_description = img_info.get('ai_description', '')
            
            # Re-categorize if failed originally
            if ai_category == 'uncategorized' or 'AI categorization failed' in ai_description:
                logger.info(f"Re-categorizing image with OpenAI Vision: {filename}")
                ai_result = self._categorize_image_with_openai(local_path)
                if ai_result:
                    ai_category = ai_result.get('category', 'uncategorized')
                    ai_labels = ai_result.get('labels', [])
                    ai_description = ai_result.get('description', '')
            
            # Calculate confidence scores
            category_confidence = 0.9 if ai_category != 'uncategorized' else 0.1
            description_confidence = 0.8 if ai_description and 'failed' not in ai_description.lower() else 0.1
            
            # Map to legacy image type for backwards compatibility
            legacy_type = self._map_to_legacy_type(ai_category, ai_labels)
            
            # Create RestaurantImage
            restaurant_image = RestaurantImage(
                restaurant=restaurant,
                source_url=img_info.get('source_url', ''),
                ai_category=ai_category,
                ai_labels=ai_labels,
                ai_description=ai_description,
                category_confidence=category_confidence,
                description_confidence=description_confidence,
                image_type=legacy_type,
                width=width,
                height=height,
                file_size=len(image_content),
                processing_status='completed',
                processed_at=timezone.now()
            )
            
            # Save image file to Django storage
            restaurant_image.image.save(filename, django_file, save=False)
            
            # Set highlights based on AI analysis
            if ai_category == 'menu_item':
                restaurant_image.is_menu_highlight = True
            elif ai_category == 'scenery_ambiance':
                restaurant_image.is_ambiance_highlight = True
            
            # Save to database
            restaurant_image.save()
            
            logger.info(f"Created RestaurantImage: {ai_category} - {ai_description[:50]}...")
            return restaurant_image
            
        except Exception as e:
            logger.error(f"Error creating RestaurantImage: {e}")
            return None
    
    def _categorize_image_with_openai(self, image_path: Path) -> Optional[Dict]:
        """Re-categorize image using ImageAI service."""
        try:
            # Use the new ImageAI service instead of direct OpenAI calls
            from services.image_ai_service import get_image_ai_service
            ai_service = get_image_ai_service()
            
            result = ai_service.categorize_image_with_ai(str(image_path))
            logger.info(f"AI categorization result: {result.get('category')} - {result.get('description', '')[:50]}...")
            return result
            
        except Exception as e:
            logger.error(f"ImageAI service categorization failed: {e}")
            return None
    
    def _map_to_legacy_type(self, ai_category: str, ai_labels: List[str]) -> str:
        """Map AI category to legacy image type for backwards compatibility."""
        if ai_category == 'menu_item':
            return 'food'
        elif ai_category == 'scenery_ambiance':
            # Check labels for more specific categorization
            labels_str = ' '.join(ai_labels).lower()
            if any(term in labels_str for term in ['exterior', 'outside', 'building', 'facade']):
                return 'exterior'
            elif any(term in labels_str for term in ['view', 'mountain', 'landscape', 'scenery']):
                return 'scenery'
            elif any(term in labels_str for term in ['dining', 'table', 'seating']):
                return 'dining_room'
            else:
                return 'interior'
        else:
            return 'interior'
    
    def integrate_from_comprehensive_data(self, comprehensive_data_path: Path) -> Dict[str, int]:
        """
        Integrate images from comprehensive scraper JSON output.
        
        Args:
            comprehensive_data_path: Path to comprehensive scraper JSON file
            
        Returns:
            Dictionary with integration statistics
        """
        results = {
            'restaurants_processed': 0,
            'images_integrated': 0,
            'errors': 0
        }
        
        try:
            with open(comprehensive_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            restaurant_name = data.get('restaurant_name', '')
            url = data.get('url', '')
            
            # Find restaurant in database
            restaurant = self._find_restaurant(restaurant_name, url)
            if not restaurant:
                logger.error(f"Restaurant not found in database: {restaurant_name}")
                results['errors'] += 1
                return results
            
            # Get image data
            image_scraping = data.get('image_scraping', {})
            images = image_scraping.get('images', [])
            
            if images:
                integrated = self.integrate_restaurant_images(restaurant, images)
                results['images_integrated'] += integrated
                results['restaurants_processed'] += 1
            else:
                logger.info(f"No images found in comprehensive data for {restaurant_name}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error integrating from comprehensive data: {e}")
            results['errors'] += 1
            return results
    
    def _find_restaurant(self, name: str, url: str) -> Optional[Restaurant]:
        """Find restaurant by name and URL."""
        try:
            # Try by URL first
            if url:
                restaurant = Restaurant.objects.filter(website=url).first()
                if restaurant:
                    return restaurant
            
            # Try by name
            restaurant = Restaurant.objects.filter(name__icontains=name).first()
            return restaurant
            
        except Exception as e:
            logger.error(f"Error finding restaurant {name}: {e}")
            return None
    
    def _match_folder_to_restaurant(self, folder_name: str) -> Optional[Restaurant]:
        """Match image folder name to restaurant in database."""
        try:
            # Clean folder name for matching
            clean_name = folder_name.replace("_", " ").replace("-", " ").strip()
            
            # Try exact match first
            restaurant = Restaurant.objects.filter(name__iexact=clean_name).first()
            if restaurant:
                return restaurant
            
            # Try case-insensitive contains match
            restaurant = Restaurant.objects.filter(name__icontains=clean_name).first()
            if restaurant:
                return restaurant
            
            # Try matching individual words
            words = clean_name.split()
            if len(words) >= 2:
                # Try matching with first few words
                partial_name = " ".join(words[:2])
                restaurant = Restaurant.objects.filter(name__icontains=partial_name).first()
                if restaurant:
                    return restaurant
            
            # Special cases for common naming patterns
            special_cases = {
                "8_½_otto_e_mezzo_bombana": "8 1/2 Otto e Mezzo - Bombana",
                "alléno_paris_au_pavillon_ledoyen": "Alléno Paris au Pavillon Ledoyen",
                "château_de_beaulieu_christophe_dufossé": "Château de Beaulieu - Christophe Dufossé",
                "fg_françois_geurds": "FG - François Geurds",
                "victor_s_fine_dining_by_christian_bau": "Victor's Fine Dining by Christian Bau"
            }
            
            for pattern, restaurant_name in special_cases.items():
                if pattern in folder_name.lower():
                    restaurant = Restaurant.objects.filter(name__icontains=restaurant_name).first()
                    if restaurant:
                        return restaurant
            
            return None
            
        except Exception as e:
            logger.error(f"Error matching folder {folder_name}: {e}")
            return None


def integrate_images_from_folders():
    """Integrate images directly from folder names to restaurants."""
    integrator = ImageIntegrator()
    
    # Get all restaurant image folders
    images_dir = integrator.scraped_images_dir
    if not images_dir.exists():
        logger.error(f"Images directory not found: {images_dir}")
        return
    
    total_results = {
        'restaurants_processed': 0,
        'images_integrated': 0,
        'errors': 0,
        'folders_without_match': 0
    }
    
    # Get all folders
    image_folders = [f for f in images_dir.iterdir() if f.is_dir()]
    logger.info(f"Found {len(image_folders)} image folders")
    
    for folder in image_folders:
        try:
            # Match folder name to restaurant
            restaurant = integrator._match_folder_to_restaurant(folder.name)
            
            if not restaurant:
                logger.warning(f"No restaurant match found for folder: {folder.name}")
                total_results['folders_without_match'] += 1
                continue
            
            # Get all images in folder
            image_files = list(folder.glob("*.jpg")) + list(folder.glob("*.jpeg")) + list(folder.glob("*.png"))
            
            if not image_files:
                logger.info(f"No images found in folder: {folder.name}")
                continue
            
            logger.info(f"Processing {len(image_files)} images for {restaurant.name}")
            
            # Process each image
            images_integrated = 0
            for img_file in image_files:
                try:
                    # Create image data dict
                    img_data = {
                        'filename': img_file.name,
                        'local_path': str(img_file),
                        'source_url': f"scraped_from_{folder.name}",
                        'status': 'completed'
                    }
                    
                    # Check if image already exists
                    existing = RestaurantImage.objects.filter(
                        restaurant=restaurant,
                        source_url=img_data['source_url']
                    ).first()
                    
                    if existing:
                        logger.debug(f"Image already exists: {img_file.name}")
                        continue
                    
                    # Create restaurant image
                    restaurant_image = integrator._create_restaurant_image(restaurant, img_data, img_file)
                    
                    if restaurant_image:
                        images_integrated += 1
                        logger.info(f"✅ Integrated: {img_file.name}")
                
                except Exception as e:
                    logger.error(f"Error processing image {img_file.name}: {e}")
                    total_results['errors'] += 1
            
            total_results['restaurants_processed'] += 1
            total_results['images_integrated'] += images_integrated
            
            logger.info(f"Completed {restaurant.name}: {images_integrated} images integrated")
            
        except Exception as e:
            logger.error(f"Error processing folder {folder.name}: {e}")
            total_results['errors'] += 1
    
    logger.info(f"Integration complete: {total_results}")
    return total_results


def integrate_all_comprehensive_images():
    """Integrate all images from comprehensive scraper output."""
    integrator = ImageIntegrator()
    
    # Path to comprehensive data directory
    data_dir = Path(__file__).parent.parent.parent.parent / "comprehensive_scraped_data"
    
    if not data_dir.exists():
        logger.error(f"Comprehensive data directory not found: {data_dir}")
        return
    
    total_results = {
        'restaurants_processed': 0,
        'images_integrated': 0,
        'errors': 0
    }
    
    # Process all JSON files
    for json_file in data_dir.glob("*.json"):
        logger.info(f"Processing {json_file.name}")
        results = integrator.integrate_from_comprehensive_data(json_file)
        
        for key in total_results:
            total_results[key] += results[key]
    
    logger.info(f"Integration complete: {total_results}")
    return total_results


if __name__ == "__main__":
    # Run both integration methods
    print("🖼️  Starting image integration from folders...")
    folder_results = integrate_images_from_folders()
    
    print("\n📁 Starting comprehensive image integration...")
    comprehensive_results = integrate_all_comprehensive_images()
    
    print("\n📊 Final Results:")
    print(f"   Folder integration: {folder_results}")
    print(f"   Comprehensive integration: {comprehensive_results}")