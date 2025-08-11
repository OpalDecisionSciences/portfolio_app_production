"""
S3-Enabled Restaurant Image Scraper with AI-powered categorization and labeling.

This module provides functionality to:
1. Scrape images from restaurant websites
2. Upload images directly to S3 (michelin-media-files bucket)
3. Use OpenAI Vision API to categorize and label images
4. Store S3 URLs in the database instead of local paths
"""

import os
import time
import logging
import requests
import traceback
import hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Tuple, Optional
import json
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from PIL import Image
from selenium.webdriver.common.by import By

# Import existing scraper components
try:
    from .llm_web_scraper import NewWebsite
except ImportError:
    from llm_web_scraper import NewWebsite

# Setup portfolio paths for cross-component imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Django setup for database access
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

from restaurants.models import Restaurant, RestaurantImage
from django.conf import settings
from token_management.token_manager import call_openai_chat
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
MIN_IMAGE_SIZE = 200  # Minimum width/height in pixels
MAX_IMAGE_SIZE = 2048  # Maximum width/height for processing
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB max file size
IMAGE_QUALITY = 85  # JPEG quality for saved images

# S3 Configuration
S3_BUCKET_NAME = os.getenv('AWS_MEDIA_BUCKET_NAME', 'michelin-media-files')
S3_REGION = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')
S3_BASE_PATH = 'restaurant-images'

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class S3RestaurantImageScraper:
    """
    S3-enabled scraper for extracting and categorizing restaurant images.
    Images are uploaded directly to S3 instead of saving locally.
    """
    
    def __init__(self):
        """
        Initialize the S3 image scraper.
        """
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=S3_REGION
        )
        
        # Test S3 connection
        try:
            self.s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
            logger.info(f"Successfully connected to S3 bucket: {S3_BUCKET_NAME}")
        except ClientError as e:
            logger.error(f"Failed to connect to S3 bucket: {e}")
            raise
    
    def get_image_urls_from_website(self, url: str, max_images: int = 20) -> List[str]:
        """
        Extract image URLs from a restaurant website.
        
        Args:
            url: Website URL to scrape
            max_images: Maximum number of images to extract
            
        Returns:
            List of image URLs found on the website
        """
        try:
            website = NewWebsite(url)
            driver = website.driver
            
            # Find all image elements
            img_elements = driver.find_elements(By.TAG_NAME, "img")
            
            image_urls = set()
            
            for img in img_elements:
                # Get various image attributes
                src = img.get_attribute('src')
                srcset = img.get_attribute('srcset')
                data_src = img.get_attribute('data-src')
                data_lazy = img.get_attribute('data-lazy-src')
                
                # Collect all possible image URLs
                if src:
                    image_urls.add(urljoin(url, src))
                if data_src:
                    image_urls.add(urljoin(url, data_src))
                if data_lazy:
                    image_urls.add(urljoin(url, data_lazy))
                    
                # Handle srcset (responsive images)
                if srcset:
                    srcset_parts = srcset.split(',')
                    for part in srcset_parts:
                        img_url = part.strip().split(' ')[0]
                        if img_url:
                            image_urls.add(urljoin(url, img_url))
                
                if len(image_urls) >= max_images:
                    break
            
            # Clean up
            website.quit()
            
            # Filter out non-image URLs
            valid_urls = []
            for img_url in image_urls:
                if any(fmt in img_url.lower() for fmt in SUPPORTED_FORMATS):
                    valid_urls.append(img_url)
                    if len(valid_urls) >= max_images:
                        break
            
            logger.info(f"Found {len(valid_urls)} valid image URLs from {url}")
            return valid_urls
            
        except Exception as e:
            logger.error(f"Error extracting image URLs from {url}: {e}")
            return []
    
    def validate_image(self, img_data: bytes) -> bool:
        """
        Validate that the downloaded data is a valid image.
        
        Args:
            img_data: Raw image data
            
        Returns:
            True if the image is valid, False otherwise
        """
        try:
            img = Image.open(BytesIO(img_data))
            
            # Check minimum dimensions
            width, height = img.size
            if width < MIN_IMAGE_SIZE or height < MIN_IMAGE_SIZE:
                logger.debug(f"Image too small: {width}x{height}")
                return False
            
            # Check file size
            if len(img_data) > MAX_FILE_SIZE:
                logger.debug(f"Image file too large: {len(img_data)} bytes")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Invalid image data: {e}")
            return False
    
    def generate_s3_key(self, restaurant_name: str, img_url: str, index: int) -> str:
        """
        Generate a unique S3 key for the image.
        
        Args:
            restaurant_name: Name of the restaurant
            img_url: Original URL of the image
            index: Index of the image
            
        Returns:
            S3 key for the image
        """
        # Clean restaurant name
        clean_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '' 
                            for c in restaurant_name)
        clean_name = clean_name.replace(' ', '_').lower()
        
        # Generate hash from URL for uniqueness
        url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
        
        # Get file extension
        parsed_url = urlparse(img_url)
        path = parsed_url.path
        ext = '.jpg'  # Default extension
        for fmt in SUPPORTED_FORMATS:
            if fmt in path.lower():
                ext = fmt
                break
        
        # Generate timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Construct S3 key
        s3_key = f"{S3_BASE_PATH}/{clean_name}/{timestamp}_{index:03d}_{url_hash}{ext}"
        
        return s3_key
    
    def upload_image_to_s3(self, img_data: bytes, s3_key: str, content_type: str = 'image/jpeg') -> Optional[str]:
        """
        Upload image data directly to S3.
        
        Args:
            img_data: Raw image data
            s3_key: S3 key for the image
            content_type: MIME type of the image
            
        Returns:
            S3 URL of the uploaded image, or None if upload failed
        """
        try:
            # Upload to S3
            self.s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=img_data,
                ContentType=content_type,
                ACL='public-read',
                CacheControl='max-age=86400'
            )
            
            # Generate public URL
            s3_url = f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{s3_key}"
            
            logger.info(f"Successfully uploaded image to S3: {s3_key}")
            return s3_url
            
        except ClientError as e:
            logger.error(f"Failed to upload image to S3: {e}")
            return None
    
    def download_and_upload_image(self, img_url: str, restaurant_name: str, index: int) -> Optional[Dict]:
        """
        Download an image from URL and upload it to S3.
        
        Args:
            img_url: URL of the image to download
            restaurant_name: Name of the restaurant
            index: Index of the image
            
        Returns:
            Dictionary with image metadata including S3 URL, or None if failed
        """
        try:
            # Download the image
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(img_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            img_data = response.content
            
            # Validate the image
            if not self.validate_image(img_data):
                logger.warning(f"Invalid image from {img_url}")
                return None
            
            # Process image if needed (resize, compress)
            img = Image.open(BytesIO(img_data))
            
            # Resize if too large
            if img.width > MAX_IMAGE_SIZE or img.height > MAX_IMAGE_SIZE:
                img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.Resampling.LANCZOS)
            
            # Convert to RGB if necessary (for JPEG saving)
            if img.mode in ('RGBA', 'P', 'LA'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            
            # Save to BytesIO
            output_buffer = BytesIO()
            img.save(output_buffer, format='JPEG', quality=IMAGE_QUALITY, optimize=True)
            processed_img_data = output_buffer.getvalue()
            
            # Generate S3 key
            s3_key = self.generate_s3_key(restaurant_name, img_url, index)
            
            # Upload to S3
            s3_url = self.upload_image_to_s3(processed_img_data, s3_key, 'image/jpeg')
            
            if not s3_url:
                return None
            
            # Calculate hashes for duplicate detection
            content_hash = hashlib.sha256(processed_img_data).hexdigest()
            source_url_hash = hashlib.sha256(img_url.encode()).hexdigest()
            
            return {
                'source_url': img_url,
                's3_url': s3_url,
                's3_key': s3_key,
                'content_hash': content_hash,
                'source_url_hash': source_url_hash,
                'width': img.width,
                'height': img.height,
                'file_size': len(processed_img_data),
                'status': 'completed'
            }
            
        except requests.RequestException as e:
            logger.error(f"Error downloading image from {img_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error processing image from {img_url}: {e}")
            traceback.print_exc()
            return None
    
    def categorize_image_with_ai(self, s3_url: str) -> Dict:
        """
        Use OpenAI Vision API to categorize and describe the image.
        
        Args:
            s3_url: S3 URL of the image
            
        Returns:
            Dictionary containing AI analysis results
        """
        try:
            # Download image from S3 for AI analysis
            response = requests.get(s3_url)
            img_data = response.content
            
            # Encode image for OpenAI
            base64_image = base64.b64encode(img_data).decode('utf-8')
            
            # AI categorization prompt
            system_prompt = """You are an expert at analyzing restaurant images. 
            Categorize the image and provide a brief description.
            
            Categories: exterior, interior, food, drink, menu, staff, ambiance, other
            
            Return a JSON object with:
            - category: the main category
            - description: a brief description (max 100 words)
            - tags: array of relevant tags (max 5)
            - is_primary: boolean indicating if this could be a primary restaurant image
            """
            
            user_prompt = f"Analyze this restaurant image: data:image/jpeg;base64,{base64_image}"
            
            # Call OpenAI
            response = call_openai_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                force_model="gpt-4o-mini"
            )
            
            if response:
                return json.loads(response)
            
            return {
                'category': 'other',
                'description': 'Restaurant image',
                'tags': [],
                'is_primary': False
            }
            
        except Exception as e:
            logger.error(f"Error categorizing image with AI: {e}")
            return {
                'category': 'other',
                'description': 'Restaurant image',
                'tags': [],
                'is_primary': False
            }
    
    def scrape_restaurant_images(self, 
                                restaurant_name: str,
                                website_url: str,
                                max_images: int = 10,
                                save_to_db: bool = True) -> List[Dict]:
        """
        Complete image scraping pipeline for a restaurant.
        
        Args:
            restaurant_name: Name of the restaurant
            website_url: Restaurant website URL
            max_images: Maximum number of images to scrape
            save_to_db: Whether to save to database
            
        Returns:
            List of scraped image metadata dictionaries
        """
        logger.info(f"Starting image scraping for {restaurant_name}")
        
        # Get image URLs from website
        image_urls = self.get_image_urls_from_website(website_url, max_images)
        
        if not image_urls:
            logger.warning(f"No images found for {restaurant_name}")
            return []
        
        scraped_images = []
        
        for idx, img_url in enumerate(image_urls):
            logger.info(f"Processing image {idx + 1}/{len(image_urls)} for {restaurant_name}")
            
            # Download and upload to S3
            image_data = self.download_and_upload_image(img_url, restaurant_name, idx)
            
            if not image_data:
                continue
            
            # Categorize with AI
            ai_analysis = self.categorize_image_with_ai(image_data['s3_url'])
            image_data.update(ai_analysis)
            
            # Save to database if requested
            if save_to_db:
                try:
                    # Find restaurant in database
                    restaurant = Restaurant.objects.filter(
                        name__icontains=restaurant_name
                    ).first()
                    
                    if restaurant:
                        # Check for duplicate
                        existing = RestaurantImage.objects.filter(
                            restaurant=restaurant,
                            content_hash=image_data['content_hash']
                        ).exists()
                        
                        if not existing:
                            RestaurantImage.objects.create(
                                restaurant=restaurant,
                                image_url=image_data['s3_url'],
                                source_url=image_data['source_url'],
                                caption=image_data.get('description', ''),
                                ai_category=image_data.get('category', 'other'),
                                ai_description=image_data.get('description', ''),
                                ai_tags=image_data.get('tags', []),
                                is_primary=image_data.get('is_primary', False),
                                content_hash=image_data['content_hash'],
                                source_url_hash=image_data['source_url_hash'],
                                ai_processed=True,
                                display_order=idx
                            )
                            logger.info(f"Saved image to database for {restaurant_name}")
                        else:
                            logger.info(f"Skipping duplicate image for {restaurant_name}")
                    else:
                        logger.warning(f"Restaurant {restaurant_name} not found in database")
                        
                except Exception as e:
                    logger.error(f"Error saving image to database: {e}")
            
            scraped_images.append(image_data)
            
            # Add small delay to be respectful
            time.sleep(0.5)
        
        logger.info(f"Completed scraping {len(scraped_images)} images for {restaurant_name}")
        return scraped_images


def test_s3_scraper():
    """
    Test function for the S3 image scraper.
    """
    scraper = S3RestaurantImageScraper()
    
    # Test with a sample restaurant
    test_restaurant = {
        'name': 'Le Bernardin',
        'url': 'https://www.le-bernardin.com'
    }
    
    results = scraper.scrape_restaurant_images(
        restaurant_name=test_restaurant['name'],
        website_url=test_restaurant['url'],
        max_images=3,
        save_to_db=False  # Don't save to DB for testing
    )
    
    print(f"Scraped {len(results)} images")
    for img in results:
        print(f"- S3 URL: {img['s3_url']}")
        print(f"  Category: {img.get('category')}")
        print(f"  Description: {img.get('description')}")
        print()


if __name__ == "__main__":
    test_s3_scraper()