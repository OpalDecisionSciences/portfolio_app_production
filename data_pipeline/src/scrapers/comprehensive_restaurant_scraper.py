#!/usr/bin/env python3
"""
Comprehensive Restaurant Scraper with Async Processing

This module provides comprehensive restaurant scraping functionality that integrates:
- Ethical async web scraping with shared browser instances
- Multi-restaurant detection and separation
- Translation using GPT-4o and token management
- Restaurant summarization using templates.py prompts
- Menu parsing and pricing extraction
- Image scraping with ImageAI service integration
- PostgreSQL/pgvector database integration
- Graceful shutdown with progress tracking

Built on LLM Engineering Week 1 patterns with production enhancements.
"""

import os
import sys
import json
import time
import asyncio
import logging
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
import pandas as pd

# Django setup for database integration
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "django_app" / "src"))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

from asgiref.sync import sync_to_async
from restaurants.models import Restaurant, RestaurantImage

# Import scraping components
from enhanced_restaurant_scraper import EnhancedRestaurantScraper
from image_scraper import RestaurantImageScraper
import templates

# Setup portfolio paths for dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

from token_management.token_manager import (
    call_openai_chat, get_token_usage_summary, update_last_completed_row, 
    get_last_completed_row, init_token_manager
)
from services.image_ai_service import get_image_ai_service

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class RestaurantData:
    """Data structure for restaurant information"""
    name: str
    url: str
    website_url: str
    michelin_stars: str
    cuisine: str
    location: str
    description: str = ""
    summary: str = ""
    menu_items: List[Dict] = None
    images: List[Dict] = None
    quality_score: float = 0.0
    processing_status: str = "pending"
    error_message: str = ""
    
    def __post_init__(self):
        if self.menu_items is None:
            self.menu_items = []
        if self.images is None:
            self.images = []

class ComprehensiveRestaurantScraper:
    """
    Comprehensive restaurant scraper with async processing and database integration.
    
    Features:
    - Async web scraping with ethical patterns
    - Multi-restaurant detection and handling
    - Translation and summarization
    - Menu parsing and image processing
    - Database integration with progress tracking
    - Token management and graceful shutdown
    """
    
    def __init__(self, 
                 output_dir: str = "comprehensive_scraping_results",
                 max_concurrent: int = 3,
                 max_images_per_restaurant: int = 15):
        """
        Initialize the comprehensive scraper.
        
        Args:
            output_dir: Directory for output files
            max_concurrent: Maximum concurrent scraping operations
            max_images_per_restaurant: Maximum images to scrape per restaurant
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Create subdirectories
        (self.output_dir / "summaries").mkdir(exist_ok=True)
        (self.output_dir / "images").mkdir(exist_ok=True)
        (self.output_dir / "progress").mkdir(exist_ok=True)
        
        self.max_concurrent = max_concurrent
        self.max_images_per_restaurant = max_images_per_restaurant
        
        # Initialize components
        self.text_scraper = EnhancedRestaurantScraper()
        self.image_scraper = RestaurantImageScraper(str(self.output_dir / "images"))
        self.image_ai_service = get_image_ai_service()
        
        # Initialize token manager
        token_dir = Path(__file__).parent.parent.parent.parent / "shared" / "token_management"
        init_token_manager(token_dir)
        
        # Progress tracking
        self.processed_count = 0
        self.error_count = 0
        self.shutdown_requested = False
        
        logger.info(f"Comprehensive restaurant scraper initialized - Output: {self.output_dir}")
    
    async def detect_language(self, text: str) -> str:
        """Detect the language of the given text using OpenAI with cost optimization."""
        try:
            # Cost optimization: Use smaller text sample and simple detection
            sample_text = text[:300]  # Reduced from 500 to save tokens
            
            # Quick heuristic check before using API
            english_words = ['the', 'and', 'or', 'of', 'to', 'in', 'for', 'is', 'are', 'was', 'were', 'menu', 'restaurant', 'food']
            english_count = sum(1 for word in english_words if word.lower() in sample_text.lower())
            
            if english_count >= 3:  # If multiple English indicators, likely English
                logger.info("Language detected as English via heuristics (token-saving)")
                return "en"
            
            # Use API for non-obvious cases
            prompt = f"Language code only (en/fr/de/es/it/ja/etc): {sample_text}"
            
            response = call_openai_chat(
                system_prompt="Respond only with 2-letter language code.",
                user_prompt=prompt,
                force_model="gpt-4o-mini"  # Use cheapest model for simple task
            )
            
            if response:
                return response.strip().lower()[:2]  # Ensure 2-letter code
            return "unknown"
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
            return "unknown"
    
    async def translate_to_english(self, text: str, source_lang: str) -> str:
        """Translate text to English using GPT-4o via token manager with cost optimization."""
        try:
            if source_lang == "en" or source_lang == "unknown":
                return text
            
            # Cost optimization: Limit text length for translation
            max_translation_length = 3000  # Limit to control token costs
            if len(text) > max_translation_length:
                # Prioritize important sections (first part usually has key info)
                text = text[:max_translation_length]
                logger.info(f"Text truncated to {max_translation_length} chars for cost-effective translation")
            
            prompt = templates.get_translation_prompt(source_lang, "en", text)
            
            response = call_openai_chat(
                system_prompt="You are a professional translator. Translate the text accurately while preserving restaurant-specific terminology.",
                user_prompt=prompt,
                force_model="gpt-4o"  # Use GPT-4o for better translation quality
            )
            
            if response:
                logger.info(f"Translated text from {source_lang} to English ({len(text)} chars)")
                return response
            else:
                logger.warning(f"Translation failed for {source_lang} text")
                return text  # Return original if translation fails
                
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return text
    
    async def check_multi_restaurant(self, text: str) -> bool:
        """Check if the website contains multiple restaurants with cost optimization."""
        try:
            # Cost optimization: Quick heuristic check first
            multi_indicators = ['restaurants', 'locations', 'venues', 'brands', 'concepts', 'establishments']
            text_lower = text[:1000].lower()  # Check first 1000 chars only
            indicator_count = sum(1 for indicator in multi_indicators if indicator in text_lower)
            
            if indicator_count == 0:
                logger.info("Single restaurant detected via heuristics (token-saving)")
                return False
            
            # Use API for ambiguous cases
            sample_text = text[:1500]  # Reduced from 2000 to save tokens
            response = call_openai_chat(
                system_prompt=templates.multi_restaurant_check_prompt,
                user_prompt=sample_text,
                force_model="gpt-4o-mini"
            )
            
            if response and "yes" in response.lower():
                logger.info("Multi-restaurant site detected")
                return True
            return False
        except Exception as e:
            logger.warning(f"Multi-restaurant check failed: {e}")
            return False
    
    async def summarize_single_restaurant(self, url: str, text: str) -> str:
        """Create a summary for a single restaurant using templates - preserving all information."""
        try:
            # Use full text as designed - this comprehensive information is what makes the app shine
            user_prompt = templates.get_summary_prompt(url, text)
            
            response = call_openai_chat(
                system_prompt=templates.summary_prompt,
                user_prompt=user_prompt,
                response_format="json",
                force_model="gpt-4o-mini"  # Let token_manager.py handle model switching for cost optimization
            )
            
            if response:
                logger.info(f"Generated comprehensive restaurant summary for {url}")
                return response
            return "{}"
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return "{}"
    
    async def parse_individual_restaurants(self, title: str, text: str, source_url: str) -> List[Dict[str, Any]]:
        """Parse individual restaurants from multi-restaurant content with URL mapping."""
        try:
            # Use enhanced prompt for structured restaurant extraction
            parsing_prompt = f"""
            Analyze this hospitality group website content and extract each individual restaurant as a separate entity.
            
            Website: {title}
            Source URL: {source_url}
            
            For each distinct restaurant/venue found, extract:
            - name: Restaurant name (clean, URL-friendly, not the group name)
            - cuisine: Cuisine type
            - description: Brief description of the restaurant
            - menu_text: Any menu content specific to this restaurant
            - location: Location/address if different from main location
            - specialties: Key dishes or features
            - atmosphere: Dining style/ambiance
            
            Ensure restaurant names are clean and suitable for URL generation.
            
            Return a JSON array of restaurants:
            [
              {{
                "name": "Restaurant Name",
                "cuisine": "Cuisine Type", 
                "description": "Description",
                "menu_text": "Menu content for this restaurant",
                "location": "Location if available",
                "specialties": ["specialty1", "specialty2"],
                "atmosphere": "Dining atmosphere"
              }}
            ]
            
            Content to analyze:
            {text[:4000]}
            """
            
            response = call_openai_chat(
                system_prompt="You are an expert at extracting individual restaurant information from hospitality group websites. Ensure names are clean and URL-friendly. Return only valid JSON.",
                user_prompt=parsing_prompt,
                force_model="gpt-4o-mini",
                response_format="json"
            )
            
            if response:
                try:
                    restaurants_data = json.loads(response)
                    if isinstance(restaurants_data, list):
                        # Generate unique URLs for each restaurant
                        for i, restaurant in enumerate(restaurants_data, 1):
                            clean_name = self._clean_restaurant_name(restaurant.get('name', f'restaurant_{i}'))
                            restaurant['individual_url'] = f"{source_url.rstrip('/')}/{clean_name}"
                            restaurant['source_url'] = source_url
                            restaurant['restaurant_index'] = i
                            
                        logger.info(f"Successfully parsed {len(restaurants_data)} individual restaurants with URLs from {title}")
                        return restaurants_data
                    else:
                        logger.warning(f"Expected array but got: {type(restaurants_data)}")
                        return []
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing failed for multi-restaurant data: {e}")
                    return []
            return []
        except Exception as e:
            logger.error(f"Multi-restaurant parsing failed: {e}")
            return []
    
    def _clean_restaurant_name(self, name: str) -> str:
        """Clean restaurant name for URL generation."""
        import re
        if not name:
            return "restaurant"
        # Remove special characters, convert to lowercase, replace spaces with hyphens
        clean = re.sub(r'[^\w\s-]', '', name.lower())
        clean = re.sub(r'\s+', '-', clean.strip())
        clean = re.sub(r'-+', '-', clean)  # Remove multiple consecutive hyphens
        return clean[:50].strip('-')  # Limit length and remove trailing hyphens

    async def summarize_multi_restaurant(self, title: str, text: str) -> str:
        """Create summaries for multiple restaurants on the same site."""
        try:
            prompt = templates.get_multi_restaurant_summary_prompt(title, text)
            
            response = call_openai_chat(
                system_prompt="You are a helpful assistant that creates structured summaries for multiple restaurants.",
                user_prompt=prompt,
                force_model="gpt-4o-mini"
            )
            
            if response:
                return response
            return ""
        except Exception as e:
            logger.error(f"Multi-restaurant summarization failed: {e}")
            return ""
    
    async def parse_menu_items(self, text: str) -> List[Dict]:
        """Parse menu items and pricing from restaurant text."""
        try:
            user_prompt = templates.get_structured_menu_user_prompt(text)
            
            response = call_openai_chat(
                system_prompt=templates.structured_menu_prompt,
                user_prompt=user_prompt,
                response_format="json",
                force_model="gpt-4o-mini"
            )
            
            if response:
                menu_data = json.loads(response)
                return menu_data if isinstance(menu_data, list) else []
            return []
        except Exception as e:
            logger.error(f"Menu parsing failed: {e}")
            return []
    
    async def save_restaurant_summary(self, restaurant_name: str, summary: str) -> Path:
        """Save restaurant summary to document.txt file."""
        try:
            safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in restaurant_name.lower())[:50]
            summary_dir = self.output_dir / "summaries" / safe_name
            summary_dir.mkdir(exist_ok=True)
            
            summary_file = summary_dir / "document.txt"
            
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary)
            
            logger.info(f"Saved summary for {restaurant_name} to {summary_file}")
            return summary_file
        except Exception as e:
            logger.error(f"Failed to save summary for {restaurant_name}: {e}")
            return None
    
    async def process_restaurant_images(self, restaurant_data: RestaurantData) -> List[Dict]:
        """Process restaurant images with AI categorization."""
        try:
            if self.shutdown_requested:
                return []
            
            logger.info(f"Processing images for {restaurant_data.name}")
            
            # Scrape images
            image_results = self.image_scraper.scrape_restaurant_images(
                restaurant_url=restaurant_data.website_url,
                restaurant_name=restaurant_data.name,
                max_images=self.max_images_per_restaurant,
                enable_ai_categorization=True  # Uses ImageAI service
            )
            
            logger.info(f"Scraped {len(image_results)} images for {restaurant_data.name}")
            return image_results
            
        except Exception as e:
            logger.error(f"Image processing failed for {restaurant_data.name}: {e}")
            return []
    
    async def save_to_database(self, restaurant_data: RestaurantData) -> Optional[Restaurant]:
        """Save restaurant data to PostgreSQL database with CASCADE delete protection."""
        try:
            # Wrap Django ORM calls with sync_to_async for proper async context handling
            restaurant = await sync_to_async(self._get_or_create_restaurant)(restaurant_data)
            
            # Save restaurant images to database (with CASCADE delete protection)
            if restaurant and restaurant_data.images:
                await self.save_restaurant_images_to_db(restaurant, restaurant_data.images)
            
            return restaurant
            
        except Exception as e:
            logger.error(f"Database save failed for {restaurant_data.name}: {e}")
            return None
    
    def _get_or_create_restaurant(self, restaurant_data: RestaurantData) -> Optional[Restaurant]:
        """Synchronous helper method for database operations."""
        try:
            # Check if restaurant already exists (prevent CASCADE delete issues)
            restaurant = Restaurant.objects.filter(
                name=restaurant_data.name,
                website=restaurant_data.website_url
            ).first()
            
            if restaurant:
                # Update existing restaurant (preserves related data)
                restaurant.summary = restaurant_data.summary
                restaurant.menu_items = restaurant_data.menu_items
                restaurant.quality_score = restaurant_data.quality_score
                restaurant.last_scraped = datetime.now()
                # Only update description if we have new content
                if restaurant_data.description and len(restaurant_data.description) > len(restaurant.description or ""):
                    restaurant.description = restaurant_data.description
                restaurant.save()
                logger.info(f"Updated existing restaurant in database: {restaurant_data.name}")
            else:
                # Create new restaurant
                restaurant = Restaurant.objects.create(
                    name=restaurant_data.name,
                    website=restaurant_data.website_url,
                    michelin_guide_url=restaurant_data.url,
                    michelin_stars=restaurant_data.michelin_stars,
                    cuisine_type=restaurant_data.cuisine,
                    location=restaurant_data.location,
                    description=restaurant_data.description,
                    summary=restaurant_data.summary,
                    menu_items=restaurant_data.menu_items,
                    quality_score=restaurant_data.quality_score,
                    last_scraped=datetime.now()
                )
                logger.info(f"Created new restaurant in database: {restaurant_data.name}")
            
            return restaurant
            
        except Exception as e:
            logger.error(f"Synchronous database operation failed for {restaurant_data.name}: {e}")
            return None
    
    async def save_restaurant_images_to_db(self, restaurant: Restaurant, image_data: List[Dict]):
        """Save scraped images to RestaurantImage model with CASCADE delete protection."""
        try:
            saved_count = 0
            for img_info in image_data:
                if img_info.get('status') != 'completed':
                    continue
                
                # Check if image already exists (prevent duplicates and CASCADE issues)
                source_url = img_info.get('source_url', '')
                existing_image = RestaurantImage.objects.filter(
                    restaurant=restaurant,
                    source_url=source_url
                ).first()
                
                if existing_image:
                    # Update existing image with new AI analysis if available
                    if img_info.get('ai_category') and img_info.get('ai_category') != 'uncategorized':
                        existing_image.ai_category = img_info.get('ai_category')
                        existing_image.ai_labels = img_info.get('ai_labels', [])
                        existing_image.ai_description = img_info.get('ai_description', '')
                        existing_image.category_confidence = img_info.get('category_confidence', 0.0)
                        existing_image.description_confidence = img_info.get('description_confidence', 0.0)
                        existing_image.processed_at = datetime.now()
                        existing_image.save()
                    continue
                
                # Create new restaurant image with CASCADE delete protection
                restaurant_image = RestaurantImage(
                    restaurant=restaurant,  # ForeignKey with proper CASCADE protection
                    source_url=source_url,
                    ai_category=img_info.get('ai_category', 'uncategorized'),
                    ai_labels=img_info.get('ai_labels', []),
                    ai_description=img_info.get('ai_description', ''),
                    category_confidence=img_info.get('category_confidence', 0.0),
                    description_confidence=img_info.get('description_confidence', 0.0),
                    width=img_info.get('width', 0),
                    height=img_info.get('height', 0),
                    file_size=img_info.get('file_size', 0),
                    processing_status='completed',
                    processed_at=datetime.now()
                )
                
                # Save image file if local path exists
                local_path = img_info.get('local_path')
                if local_path and Path(local_path).exists():
                    try:
                        with open(local_path, 'rb') as img_file:
                            from django.core.files.base import ContentFile
                            django_file = ContentFile(img_file.read(), name=img_info.get('filename', 'image.jpg'))
                            restaurant_image.image.save(img_info.get('filename', 'image.jpg'), django_file, save=False)
                    except Exception as e:
                        logger.warning(f"Failed to save image file for {restaurant.name}: {e}")
                
                # Save to database with error handling to prevent CASCADE issues
                try:
                    restaurant_image.save()
                    saved_count += 1
                    logger.debug(f"Saved image for {restaurant.name}: {img_info.get('filename')}")
                except Exception as e:
                    logger.warning(f"Failed to save image to database for {restaurant.name}: {e}")
                    
            if saved_count > 0:
                logger.info(f"Successfully saved {saved_count} images for {restaurant.name}")
                
        except Exception as e:
            logger.error(f"Error saving images for {restaurant.name}: {e}")
    
    async def process_single_restaurant(self, row: pd.Series, row_index: int) -> RestaurantData:
        """Process a single restaurant from the CSV data."""
        restaurant_name = row.get('Name', f'Restaurant_{row_index}')
        website_url = row.get('WebsiteUrl', '')
        michelin_url = row.get('Url', '')
        
        logger.info(f"[{row_index}] Processing: {restaurant_name}")
        
        restaurant_data = RestaurantData(
            name=restaurant_name,
            url=michelin_url,
            website_url=website_url,
            michelin_stars=row.get('Award', ''),
            cuisine=row.get('Cuisine', ''),
            location=row.get('Location', ''),
            description=row.get('Description', '')
        )
        
        try:
            if not website_url:
                restaurant_data.error_message = "No website URL provided"
                restaurant_data.processing_status = "failed"
                return restaurant_data
            
            # Check for shutdown request
            if self.shutdown_requested:
                restaurant_data.processing_status = "cancelled"
                return restaurant_data
            
            # Step 1: Scrape website content
            logger.info(f"[{row_index}] Scraping website content...")
            scraped_data = self.text_scraper.scrape_restaurant(website_url, use_selenium=True)
            
            if not scraped_data or scraped_data.get('quality_score', 0) < 0.2:
                restaurant_data.error_message = "Low quality or no content extracted"
                restaurant_data.processing_status = "failed"
                return restaurant_data
            
            restaurant_data.quality_score = scraped_data.get('quality_score', 0)
            content = scraped_data.get('content', '')
            
            # Step 2: Language detection and translation
            logger.info(f"[{row_index}] Detecting language and translating...")
            detected_lang = await self.detect_language(content)
            translated_content = await self.translate_to_english(content, detected_lang)
            
            # Step 3: Check for multi-restaurant sites
            is_multi_restaurant = await self.check_multi_restaurant(translated_content)
            
            # Step 4: Generate summary
            logger.info(f"[{row_index}] Generating summary...")
            if is_multi_restaurant:
                summary_text = await self.summarize_multi_restaurant(restaurant_name, translated_content)
            else:
                summary_json = await self.summarize_single_restaurant(website_url, translated_content)
                summary_text = json.dumps(json.loads(summary_json), indent=2) if summary_json != "{}" else ""
            
            restaurant_data.summary = summary_text
            
            # Step 5: Save summary to file
            if summary_text:
                await self.save_restaurant_summary(restaurant_name, summary_text)
            
            # Step 6: Parse menu items
            logger.info(f"[{row_index}] Parsing menu items...")
            restaurant_data.menu_items = await self.parse_menu_items(translated_content)
            
            # Step 7: Process images
            logger.info(f"[{row_index}] Processing images...")
            restaurant_data.images = await self.process_restaurant_images(restaurant_data)
            
            # Step 8: Save to database
            logger.info(f"[{row_index}] Saving to database...")
            db_restaurant = await self.save_to_database(restaurant_data)
            
            if db_restaurant:
                restaurant_data.processing_status = "completed"
                logger.info(f"[{row_index}] ✅ Successfully processed: {restaurant_name}")
            else:
                restaurant_data.processing_status = "partial"  # Content processed but DB save failed
                
        except Exception as e:
            logger.error(f"[{row_index}] Error processing {restaurant_name}: {e}")
            restaurant_data.error_message = str(e)
            restaurant_data.processing_status = "failed"
        
        return restaurant_data
    
    async def check_token_availability(self) -> bool:
        """Check if tokens are available for processing."""
        try:
            token_summary = get_token_usage_summary()
            if not token_summary.get('current_model'):
                logger.warning("No model available for processing")
                return False
            return True
        except Exception as e:
            logger.error(f"Token availability check failed: {e}")
            return False
    
    async def save_progress(self, results: List[RestaurantData], batch_info: Dict):
        """Save processing progress to file."""
        try:
            progress_file = self.output_dir / "progress" / f"progress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            progress_data = {
                'batch_info': batch_info,
                'results': [asdict(result) for result in results],
                'summary': {
                    'total_processed': len(results),
                    'successful': len([r for r in results if r.processing_status == 'completed']),
                    'failed': len([r for r in results if r.processing_status == 'failed']),
                    'partial': len([r for r in results if r.processing_status == 'partial'])
                }
            }
            
            with open(progress_file, 'w') as f:
                f.write(json.dumps(progress_data, indent=2, default=str))
            
            logger.info(f"Progress saved to {progress_file}")
            
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")
    
    def request_shutdown(self):
        """Request graceful shutdown."""
        logger.info("Shutdown requested - will complete current operations and stop")
        self.shutdown_requested = True
    
    async def process_restaurants_batch(self, 
                                      csv_file: str, 
                                      start_row: int = 0,
                                      max_restaurants: int = None,
                                      resume: bool = True) -> Dict[str, Any]:
        """
        Process restaurants from CSV file with async processing and graceful shutdown.
        
        Args:
            csv_file: Path to Michelin CSV file
            start_row: Row to start processing from
            max_restaurants: Maximum number of restaurants to process
            resume: Whether to resume from last completed row
            
        Returns:
            Dictionary with processing results and statistics
        """
        logger.info(f"Starting comprehensive restaurant processing from {csv_file}")
        
        # Load CSV data
        try:
            df = pd.read_csv(csv_file)
            logger.info(f"Loaded {len(df)} restaurants from CSV")
        except Exception as e:
            logger.error(f"Failed to load CSV file: {e}")
            return {"error": f"Failed to load CSV: {e}"}
        
        # Resume from last completed row if requested
        if resume:
            last_completed = get_last_completed_row()
            if last_completed >= 0:
                start_row = last_completed + 1
                logger.info(f"Resuming from row {start_row}")
        
        # Filter data based on start_row and max_restaurants
        if start_row > 0:
            df = df.iloc[start_row:]
        if max_restaurants:
            df = df.head(max_restaurants)
        
        # Filter to only restaurants with websites
        df_with_websites = df[df['WebsiteUrl'].notna()]
        logger.info(f"Processing {len(df_with_websites)} restaurants with websites")
        
        batch_info = {
            'csv_file': csv_file,
            'start_row': start_row,
            'total_in_csv': len(df),
            'processing_count': len(df_with_websites),
            'started_at': datetime.now().isoformat(),
            'max_concurrent': self.max_concurrent
        }
        
        results = []
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def process_with_semaphore(row_data, row_idx):
            async with semaphore:
                # Check for shutdown before processing
                if self.shutdown_requested:
                    return None
                
                # Check token availability
                if not await self.check_token_availability():
                    logger.warning("No tokens available - stopping processing")
                    self.request_shutdown()
                    return None
                
                result = await self.process_single_restaurant(row_data[1], start_row + row_data[0])
                
                # Update progress tracking
                update_last_completed_row(start_row + row_data[0])
                
                return result
        
        # Process restaurants with controlled concurrency
        tasks = []
        for idx, (_, row) in enumerate(df_with_websites.iterrows()):
            if self.shutdown_requested:
                break
                
            task = asyncio.create_task(process_with_semaphore((idx, row), idx))
            tasks.append(task)
            
            # Save progress periodically
            if len(tasks) % 10 == 0:
                logger.info(f"Created {len(tasks)} processing tasks...")
        
        # Wait for all tasks to complete
        logger.info(f"Waiting for {len(tasks)} tasks to complete...")
        
        try:
            for task in asyncio.as_completed(tasks):
                result = await task
                if result:
                    results.append(result)
                    
                    # Log progress
                    if len(results) % 5 == 0:
                        successful = len([r for r in results if r.processing_status == 'completed'])
                        logger.info(f"Progress: {len(results)}/{len(tasks)} - {successful} successful")
                        
                        # Save progress periodically
                        await self.save_progress(results, batch_info)
                
                # Check for shutdown
                if self.shutdown_requested:
                    logger.info("Shutdown requested - cancelling remaining tasks")
                    for remaining_task in tasks:
                        if not remaining_task.done():
                            remaining_task.cancel()
                    break
        
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received - initiating graceful shutdown")
            self.request_shutdown()
            
            # Cancel remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
        
        # Final statistics
        batch_info['completed_at'] = datetime.now().isoformat()
        batch_info['shutdown_requested'] = self.shutdown_requested
        
        successful = len([r for r in results if r.processing_status == 'completed'])
        failed = len([r for r in results if r.processing_status == 'failed'])
        partial = len([r for r in results if r.processing_status == 'partial'])
        
        final_results = {
            'batch_info': batch_info,
            'results': results,
            'summary': {
                'total_processed': len(results),
                'successful': successful,
                'failed': failed,
                'partial': partial,
                'success_rate': (successful / len(results) * 100) if results else 0
            }
        }
        
        # Save final results
        await self.save_progress(results, batch_info)
        
        logger.info(f"Processing complete: {successful}/{len(results)} successful ({final_results['summary']['success_rate']:.1f}%)")
        
        return final_results

# Async main function for running the scraper
async def main():
    """Main function for running comprehensive restaurant scraping."""
    import signal
    
    # Create scraper instance
    scraper = ComprehensiveRestaurantScraper(
        output_dir="comprehensive_scraping_results",
        max_concurrent=3,  # Conservative for production
        max_images_per_restaurant=15
    )
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum} - requesting graceful shutdown")
        scraper.request_shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Process restaurants
    csv_file = "data_pipeline/src/ingestion/michelin_my_maps.csv"
    
    results = await scraper.process_restaurants_batch(
        csv_file=csv_file,
        max_restaurants=50,  # Start with smaller batch for testing
        resume=True
    )
    
    print("\n" + "="*50)
    print("COMPREHENSIVE SCRAPING COMPLETE")
    print("="*50)
    print(f"Total processed: {results['summary']['total_processed']}")
    print(f"Successful: {results['summary']['successful']}")
    print(f"Failed: {results['summary']['failed']}")
    print(f"Success rate: {results['summary']['success_rate']:.1f}%")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())