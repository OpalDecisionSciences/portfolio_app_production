"""
Unified Restaurant Scraper - Complete LLM-powered restaurant data extraction
Consolidates all scraping functionality with comprehensive LLM analysis, 
menu parsing, image processing, and database integration.
"""

import os
import time
import random
import logging
import requests
import traceback
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin, urlparse
import concurrent.futures
from urllib.robotparser import RobotFileParser
from datetime import datetime, timedelta
import hashlib
# base64 no longer needed - handled by ImageAI service
from io import BytesIO
import pytz

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# BeautifulSoup for HTML parsing
from bs4 import BeautifulSoup, Comment

# Image processing
from PIL import Image

# Language detection
from langdetect import detect as detect_language

# Django integration - use comprehensive path management
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

from restaurants.models import Restaurant, MenuSection, MenuItem, RestaurantImage

# Import templates and utilities
try:
    from config import setup_portfolio_paths
    setup_portfolio_paths()
    from token_management.token_manager import call_openai_chat, get_token_usage_summary, init_token_manager
except ImportError:
    print("Warning: Token management not available")

try:
    from templates import (
        summary_prompt, structured_menu_prompt, 
        get_summary_prompt, get_structured_menu_user_prompt,
        get_translation_prompt, link_system_prompt,
        get_links_user_prompt, select_english_version_prompt,
        cleaning_prompt, multi_restaurant_check_prompt
    )
except ImportError:
    from .templates import (
        summary_prompt, structured_menu_prompt,
        get_summary_prompt, get_structured_menu_user_prompt, 
        get_translation_prompt, link_system_prompt,
        get_links_user_prompt, select_english_version_prompt,
        cleaning_prompt, multi_restaurant_check_prompt
    )

# Import LLM web scraper for multi-page functionality
try:
    from llm_web_scraper import NewWebsite
except ImportError:
    from .llm_web_scraper import NewWebsite

# OpenAI integration now via ImageAI service
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
# OpenAI client now handled by ImageAI service


class UnifiedRestaurantScraper:
    """
    Unified restaurant scraper with complete LLM analysis and database integration.
    Consolidates all functionality from previous scrapers.
    """
    
    def __init__(self, token_dir: Optional[Path] = None, image_output_dir: Optional[Path] = None):
        """Initialize the unified scraper."""
        self.session = requests.Session()
        self.driver = None
        
        # Configure directories
        if image_output_dir is None:
            image_output_dir = Path(__file__).parent.parent.parent.parent / "comprehensive_scraped_images"
        self.image_output_dir = Path(image_output_dir)
        self.image_output_dir.mkdir(exist_ok=True)
        
        # Initialize token manager
        if token_dir is None:
            token_dir = Path(__file__).parent.parent.parent.parent / "shared" / "token_management"
        
        try:
            init_token_manager(token_dir)
            logger.info("Token manager initialized successfully")
        except Exception as e:
            logger.warning(f"Token manager initialization failed: {e}")
            # Ensure fallback to direct OpenAI works
        
        # Rate limiting
        self.last_request_time = 0
        self.min_delay = 2.0  # Minimum delay between requests
        
        logger.info("Unified restaurant scraper initialized")
    
    def scrape_restaurant_complete(self, url: str, restaurant_name: str, 
                                 max_images: int = 15, save_to_db: bool = True, 
                                 multi_page: bool = True) -> Dict[str, Any]:
        """
        Complete restaurant scraping with LLM analysis and database integration.
        
        Args:
            url: Restaurant website URL
            restaurant_name: Name of the restaurant
            max_images: Maximum number of images to scrape
            save_to_db: Whether to save results to database
            multi_page: Whether to scrape multiple pages (menu, about, etc.)
            
        Returns:
            Complete scraping results dictionary
        """
        results = {
            'restaurant_name': restaurant_name,
            'url': url,
            'scraped_at': datetime.now().isoformat(),
            'scraping_success': False,
            'save_to_db_success': False,
            'database_restaurant_id': None
        }
        
        try:
            logger.info(f"Starting complete scraping for: {restaurant_name}")
            
            # Step 1: Multi-page link filtering and content extraction
            if multi_page:
                filtered_links, landing_page = self._get_filtered_links_and_landing(url)
                if landing_page:
                    all_content = self._scrape_multiple_pages(filtered_links, landing_page)
                else:
                    # Fallback to single page scraping
                    content_result = self._scrape_content(url)
                    all_content = content_result.get('content', '') if content_result else ''
            else:
                # Single page scraping
                content_result = self._scrape_content(url)
                all_content = content_result.get('content', '') if content_result else ''
            
            if not all_content:
                return results
            
            results['content'] = all_content
            results['scraping_success'] = True
            
            # Step 2: LLM Analysis
            llm_analysis = self._comprehensive_llm_analysis(
                all_content, url, restaurant_name
            )
            results['llm_analysis'] = llm_analysis
            
            # Step 3: Image scraping
            image_results = self._scrape_images(url, restaurant_name, max_images)
            results['image_scraping'] = image_results
            
            # Step 3.5: Generate document.txt
            if results.get('llm_analysis'):
                document_content = self._generate_document_txt(results)
                if document_content:
                    results['document_txt'] = document_content
                    # Save document to restaurant_docs directory
                    self._save_document_txt(restaurant_name, document_content)
            
            # Step 4: Database integration
            if save_to_db:
                db_result = self._save_to_database(results)
                results['save_to_db_success'] = db_result['success']
                results['database_restaurant_id'] = db_result.get('restaurant_id')
                results['menu_sections_created'] = db_result.get('menu_sections_created', 0)
                results['menu_items_created'] = db_result.get('menu_items_created', 0)
                results['images_integrated'] = db_result.get('images_integrated', 0)
            
            # Step 5: Trigger embedding updates for RAG
            if results.get('document_txt') or results.get('images_integrated', 0) > 0:
                self._trigger_embedding_updates(restaurant_name, results)
            
            logger.info(f"Complete scraping finished for: {restaurant_name}")
            return results
            
        except Exception as e:
            logger.error(f"Error in complete scraping for {restaurant_name}: {e}")
            results['error'] = str(e)
            return results
        finally:
            self._cleanup()
    
    def _scrape_content(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape basic content from restaurant website."""
        try:
            # Rate limiting
            self._rate_limit()
            
            # Check robots.txt
            if not self._check_robots_txt(url):
                logger.warning(f"Robots.txt disallows scraping: {url}")
                return None
            
            # Try requests first, then Selenium if needed
            content_data = self._get_with_requests(url)
            if not content_data or content_data.get('quality_score', 0) < 0.3:
                content_data = self._get_with_selenium(url)
            
            return content_data
            
        except Exception as e:
            logger.error(f"Content scraping failed for {url}: {e}")
            return None
    
    def _get_with_requests(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape using requests library."""
        try:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            content = self._extract_content(soup)
            
            return {
                'content': content,
                'method_used': 'requests',
                'content_length': len(response.content),
                'word_count': len(content.split()),
                'quality_score': self._calculate_quality_score(content),
                'structured_data': self._extract_structured_data(soup)
            }
            
        except Exception as e:
            logger.error(f"Requests scraping failed: {e}")
            return None
    
    def _get_with_selenium(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape using Selenium for dynamic content."""
        try:
            if not self.driver:
                self._init_selenium_driver()
            
            self.driver.get(url)
            time.sleep(3)  # Allow content to load
            
            # Handle popups and overlays
            self._dismiss_popups()
            
            # Get page content
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            content = self._extract_content(soup)
            
            return {
                'content': content,
                'method_used': 'selenium',
                'content_length': len(self.driver.page_source),
                'word_count': len(content.split()),
                'quality_score': self._calculate_quality_score(content),
                'structured_data': self._extract_structured_data(soup)
            }
            
        except Exception as e:
            logger.error(f"Selenium scraping failed: {e}")
            return None
    
    def _init_selenium_driver(self):
        """Initialize Selenium WebDriver with ARM64 compatibility."""
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--remote-debugging-port=9222")
            
            # Set binary path to use container's chromium
            if os.path.exists("/usr/bin/chromium"):
                options.binary_location = "/usr/bin/chromium"
            
            # Configure Chrome service for production deployment
            # Priority: container chromedriver > webdriver-manager fallback
            chromedriver_paths = [
                "/usr/bin/chromedriver",  # Docker container path (production)
            ]
            
            service = None
            for path in chromedriver_paths:
                if os.path.exists(path):
                    try:
                        service = Service(path)
                        self.driver = webdriver.Chrome(service=service, options=options)
                        logger.info(f"Successfully initialized Chrome driver for image scraping: {path}")
                        break
                    except Exception as e:
                        logger.warning(f"Failed to use chromedriver at {path}: {e}")
                        continue
            
            if self.driver is None:
                # Fallback to webdriver-manager
                try:
                    from webdriver_manager.chrome import ChromeDriverManager
                    service = Service(ChromeDriverManager().install())
                    self.driver = webdriver.Chrome(service=service, options=options)
                    logger.info("Successfully initialized Chrome driver with webdriver-manager for image scraping")
                except Exception as e:
                    logger.error(f"Failed to initialize Chrome driver with all methods for image scraping: {e}")
                    # Don't raise exception - let image scraping fail gracefully
                    self.driver = None
                    return
            
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
        except Exception as e:
            logger.error(f"Failed to initialize Selenium driver: {e}")
            raise
    
    def _comprehensive_llm_analysis(self, content: str, url: str, restaurant_name: str) -> Dict[str, Any]:
        """Perform comprehensive LLM analysis including summarization and menu parsing."""
        logger.info(f"Starting comprehensive LLM analysis for {restaurant_name}")
        analysis_result = {}
        
        try:
            # Step 1: Language detection
            logger.info(f"Detecting language for content of length: {len(content)}")
            detected_lang = self._detect_language(content[:1000])
            logger.info(f"Detected language: {detected_lang}")
            analysis_result['detected_language'] = detected_lang
            
            # Step 2: Translation if needed (GPT-4o for global content)
            working_content = content
            if detected_lang != 'en' and len(content) > 200:
                logger.info(f"Translating content from {detected_lang} to English using GPT-4o")
                translated = self._translate_content(content, detected_lang)
                if translated and translated != content:
                    analysis_result['translated_content'] = translated
                    analysis_result['original_language'] = detected_lang
                    working_content = translated
                    logger.info(f"Translation completed. Original length: {len(content)}, Translated length: {len(translated)}")
            
            # Step 3: Restaurant summary analysis
            logger.info(f"Getting restaurant summary for content length: {len(working_content)}")
            summary = self._get_restaurant_summary(working_content, url)
            logger.info(f"Restaurant summary result: {summary}")
            if summary:
                analysis_result['restaurant_summary'] = summary
            else:
                logger.warning("No restaurant summary returned")
            
            # Step 4: Menu parsing
            menu_sections = self._parse_menu(working_content)
            if menu_sections:
                analysis_result['structured_menu'] = menu_sections
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return {'error': str(e)}
    
    def _get_restaurant_summary(self, content: str, url: str) -> Optional[Dict]:
        """Use templates.py summary_prompt for comprehensive restaurant analysis."""
        try:
            logger.info(f"Building summary prompt for URL: {url}")
            user_prompt = get_summary_prompt(url, content[:3000])
            logger.info(f"User prompt length: {len(user_prompt)}")
            
            logger.info("Calling LLM for restaurant summary...")
            response = self._call_llm(
                system_prompt=summary_prompt,
                user_prompt=user_prompt,
                response_format={"type": "json_object"},
                model="gpt-4o-mini"  # Use gpt-4o-mini for analysis as specified
            )
            
            logger.info(f"LLM response received: {response}")
            
            if response and response.strip():
                # Use existing JSON parsing pattern from scrape_utils.py
                try:
                    result = json.loads(response)
                    logger.info(f"Successfully parsed JSON response: {result}")
                    return result
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing failed for summary: {e}")
                    logger.error(f"Raw response: {response}")
                    # Try to extract JSON from response if malformed
                    cleaned_response = self._extract_json_from_response(response)
                    if cleaned_response:
                        try:
                            result = json.loads(cleaned_response)
                            logger.info(f"Successfully parsed cleaned JSON: {result}")
                            return result
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse cleaned JSON response")
                    return None
            else:
                logger.warning("No response or empty response from LLM")
            
        except Exception as e:
            logger.error(f"Restaurant summary failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        return None
    
    def _parse_menu(self, content: str) -> Optional[List[Dict]]:
        """Use templates.py structured_menu_prompt for menu parsing."""
        try:
            user_prompt = get_structured_menu_user_prompt(content)
            
            response = self._call_llm(
                system_prompt=structured_menu_prompt,
                user_prompt=user_prompt,
                response_format={"type": "json_object"},
                model="gpt-4o-mini"  # Use gpt-4o-mini for menu parsing as specified
            )
            
            if response and response.strip():
                # Use existing JSON parsing pattern from scrape_utils.py
                try:
                    data = json.loads(response)
                    return data.get('sections', [])
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing failed for menu: {e}")
                    # Try to extract JSON from response if malformed
                    cleaned_response = self._extract_json_from_response(response)
                    if cleaned_response:
                        try:
                            data = json.loads(cleaned_response)
                            return data.get('sections', [])
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse cleaned menu JSON response")
                    return None
            
        except Exception as e:
            logger.error(f"Menu parsing failed: {e}")
        
        return None
    
    def _generate_document_txt(self, scraping_results: Dict[str, Any]) -> Optional[str]:
        """Generate document.txt content using existing summarize_and_save functionality."""
        try:
            # Import existing functions
            try:
                from .scrape_utils import summarize_and_save
            except ImportError:
                from scrape_utils import summarize_and_save
            
            llm_analysis = scraping_results.get('llm_analysis', {})
            summary = llm_analysis.get('restaurant_summary', {})
            
            if not summary:
                return None
            
            # Create structured document content
            document_parts = []
            
            # Restaurant name and location
            restaurant_name = scraping_results.get('restaurant_name', 'Unknown Restaurant')
            document_parts.append(f"# {restaurant_name}")
            
            # Add chef information
            if summary.get('chef'):
                document_parts.append(f"\n## Head Chef\n{summary['chef']}")
            
            # Add cuisine and philosophy
            if summary.get('cuisine'):
                document_parts.append(f"\n## Cuisine\n{summary['cuisine']}")
            
            if summary.get('philosophy'):
                document_parts.append(f"\n## Philosophy & Approach\n{summary['philosophy']}")
            
            # Add ambiance
            if summary.get('ambiance'):
                document_parts.append(f"\n## Ambiance & Atmosphere\n{summary['ambiance']}")
            
            # Add location details
            if summary.get('location'):
                document_parts.append(f"\n## Location\n{summary['location']}")
            
            # Add highlights
            if summary.get('highlights'):
                document_parts.append(f"\n## Highlights\n{summary['highlights']}")
            
            # Add timezone and location information
            if llm_analysis.get('original_language'):
                document_parts.append(f"\n## Language\nOriginal website language: {llm_analysis['original_language']}")
            
            # Add timezone information if available
            location = summary.get('location')
            if location:
                timezone_info = self._get_timezone_info(location)
                if timezone_info.get('local_timezone'):
                    document_parts.append(f"\n## Location & Time Zone\n")
                    document_parts.append(f"Country: {timezone_info.get('country', 'Unknown')}")
                    document_parts.append(f"City: {timezone_info.get('city', 'Unknown')}")
                    document_parts.append(f"Timezone: {timezone_info.get('local_timezone')}")
                    document_parts.append(f"Current local time: {timezone_info.get('current_local_time', 'Unknown')}")
            
            # Add timestamp and metadata
            document_parts.append(f"\n## Document Information\n")
            document_parts.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
            document_parts.append(f"Source: {scraping_results.get('url', '')}")
            
            return '\n'.join(document_parts)
            
        except Exception as e:
            logger.error(f"Document generation failed: {e}")
            return None
    
    def _save_document_txt(self, restaurant_name: str, document_content: str):
        """Save document.txt to restaurant_docs directory."""
        try:
            # Use existing restaurant_docs directory structure
            docs_dir = Path(__file__).parent / "restaurant_docs"
            docs_dir.mkdir(exist_ok=True)
            
            # Clean restaurant name for filename
            clean_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in restaurant_name.lower())[:50]
            filename = f"{clean_name}_document.txt"
            
            # Save document
            with open(docs_dir / filename, 'w', encoding='utf-8') as f:
                f.write(document_content)
            
            logger.info(f"Document saved: {filename}")
            
        except Exception as e:
            logger.error(f"Failed to save document: {e}")

    def _trigger_embedding_updates(self, restaurant_name: str, scraping_results: Dict[str, Any]):
        """Trigger embedding updates for RAG after successful scraping."""
        try:
            # Import Celery task locally to avoid circular imports
            from restaurants.tasks import trigger_document_embedding_on_scrape
            
            # Trigger document embedding and enhanced RAG updates
            task_result = trigger_document_embedding_on_scrape.delay(
                restaurant_name=restaurant_name,
                scraping_results=scraping_results
            )
            
            logger.info(f"Triggered embedding updates for {restaurant_name}: task_id={task_result.id}")
            
        except Exception as e:
            logger.warning(f"Failed to trigger embedding updates for {restaurant_name}: {e}")
            # Don't raise exception - embedding updates are supplementary

    def _save_to_database(self, scraping_results: Dict[str, Any]) -> Dict[str, Any]:
        """Save complete scraping results to Django database."""
        db_result = {
            'success': False,
            'restaurant_id': None,
            'menu_sections_created': 0,
            'menu_items_created': 0,
            'images_integrated': 0
        }
        
        try:
            # Create or update restaurant
            restaurant = self._save_restaurant(scraping_results)
            if not restaurant:
                return db_result
            
            db_result['restaurant_id'] = str(restaurant.id)
            
            # Save menu data
            menu_result = self._save_menu_data(restaurant, scraping_results)
            db_result.update(menu_result)
            
            # Save images
            image_result = self._save_images(restaurant, scraping_results)
            db_result['images_integrated'] = image_result.get('images_integrated', 0)
            
            db_result['success'] = True
            return db_result
            
        except Exception as e:
            logger.error(f"Database save failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            db_result['error'] = str(e)
            db_result['traceback'] = traceback.format_exc()
            return db_result
    
    def _save_restaurant(self, scraping_results: Dict[str, Any]) -> Optional[Restaurant]:
        """Save restaurant data to database."""
        try:
            url = scraping_results.get('url', '')
            name = scraping_results.get('restaurant_name', '')
            
            # Try to find existing restaurant
            restaurant = Restaurant.objects.filter(website=url).first()
            if not restaurant:
                restaurant = Restaurant.objects.filter(name=name).first()
            
            # Extract data from LLM analysis
            llm_analysis = scraping_results.get('llm_analysis', {})
            summary = llm_analysis.get('restaurant_summary', {})
            
            # Use timezone-aware datetime for Django
            from django.utils import timezone
            
            restaurant_data = {
                'name': name,
                'website': url,
                'scraped_content': scraping_results.get('content', ''),
                'scraped_at': timezone.now(),
            }
            
            # Add LLM-derived fields
            if summary:
                if summary.get('cuisine'):
                    restaurant_data['cuisine_type'] = summary['cuisine'][:100]
                if summary.get('ambiance'):
                    restaurant_data['atmosphere'] = summary['ambiance'][:100]
                if summary.get('location'):
                    # Parse location and get timezone info
                    location = summary['location']
                    timezone_info = self._get_timezone_info(location)
                    
                    if timezone_info.get('country'):
                        restaurant_data['country'] = timezone_info['country'][:100]
                    if timezone_info.get('city'):
                        restaurant_data['city'] = timezone_info['city'][:100]
                    
                    # Store timezone information in metadata field (if available in model)
                    if timezone_info.get('local_timezone'):
                        try:
                            # Store timezone info directly (Restaurant model already imported at top)
                            restaurant_data['timezone_info'] = timezone_info  # Store as dict, not JSON string
                        except:
                            pass  # Continue without timezone if field doesn't exist
                    
                    # Fallback parsing if timezone extraction fails
                    if not timezone_info.get('country') and ',' in location:
                        parts = location.split(',')
                        restaurant_data['city'] = parts[0].strip()[:100]
                        if len(parts) > 1:
                            restaurant_data['country'] = parts[-1].strip()[:100]
            
            if restaurant:
                # Update existing
                for field, value in restaurant_data.items():
                    setattr(restaurant, field, value)
                restaurant.save()
            else:
                # Create new
                if not restaurant_data.get('city'):
                    restaurant_data['city'] = 'Unknown'
                if not restaurant_data.get('country'):
                    restaurant_data['country'] = 'Unknown'
                if not restaurant_data.get('address'):
                    restaurant_data['address'] = 'Unknown'
                    
                restaurant = Restaurant.objects.create(**restaurant_data)
            
            logger.info(f"Restaurant saved: {restaurant.name}")
            return restaurant
            
        except Exception as e:
            logger.error(f"Error saving restaurant: {e}")
            return None
    
    def _save_menu_data(self, restaurant: Restaurant, scraping_results: Dict[str, Any]) -> Dict[str, int]:
        """Save menu sections and items to database."""
        result = {'menu_sections_created': 0, 'menu_items_created': 0}
        
        try:
            llm_analysis = scraping_results.get('llm_analysis', {})
            menu_sections = llm_analysis.get('structured_menu', [])
            
            if not menu_sections:
                return result
            
            # Clear existing menu data for this restaurant
            MenuSection.objects.filter(restaurant=restaurant).delete()
            
            for order, section_data in enumerate(menu_sections):
                section_name = section_data.get('section', 'Unknown Section')
                
                # Create menu section
                menu_section = MenuSection.objects.create(
                    restaurant=restaurant,
                    name=section_name[:100],
                    description='',
                    order=order
                )
                result['menu_sections_created'] += 1
                
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
                    result['menu_items_created'] += 1
            
            logger.info(f"Menu data saved: {result['menu_sections_created']} sections, {result['menu_items_created']} items")
            return result
            
        except Exception as e:
            logger.error(f"Error saving menu data: {e}")
            return result
    
    def _save_images(self, restaurant: Restaurant, scraping_results: Dict[str, Any]) -> Dict[str, int]:
        """Save scraped images to database."""
        result = {'images_integrated': 0}
        
        try:
            image_data = scraping_results.get('image_scraping', {}).get('images', [])
            if not image_data:
                return result
            
            # Use the image integrator from previous work
            from processors.image_integrator import ImageIntegrator
            integrator = ImageIntegrator()
            
            integrated_count = integrator.integrate_restaurant_images(restaurant, image_data)
            result['images_integrated'] = integrated_count
            
            return result
            
        except Exception as e:
            logger.error(f"Error saving images: {e}")
            return result
    
    def _scrape_images(self, url: str, restaurant_name: str, max_images: int) -> Dict[str, Any]:
        """Scrape and categorize images from restaurant website."""
        try:
            # Use async scraper manager for image scraping to avoid driver conflicts
            from .async_scraper_manager import get_scraper_manager
            
            scraper_manager = get_scraper_manager()
            task_id = scraper_manager.add_task_to_backlog(
                url=url,
                restaurant_name=restaurant_name,
                task_type='images',
                priority=2
            )
            
            logger.info(f"Added image scraping task to backlog: {task_id}")
            
            # For now, return empty result and let background processing handle it
            return {
                'images': [],
                'successful_images': 0,
                'failed_images': 0,
                'task_id': task_id,
                'status': 'queued_for_background_processing'
            }
            
        except Exception as e:
            logger.error(f"Image scraping task queuing failed: {e}")
            return {
                'images': [],
                'successful_images': 0,
                'failed_images': 0,
                'error': str(e),
                'status': 'failed'
            }
    
    # Helper methods (extracted from existing scrapers)
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_request_time = time.time()
    
    def _check_robots_txt(self, url: str) -> bool:
        """Check if robots.txt allows scraping."""
        try:
            parsed_url = urlparse(url)
            robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
            
            rp = RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            
            return rp.can_fetch('*', url)
        except:
            return True  # If robots.txt can't be checked, assume allowed
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract meaningful text content from BeautifulSoup object."""
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        text = soup.get_text(separator=' ', strip=True)
        
        # Clean up text
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s\-\.\,\!\?\:\;\(\)\/\&\@]', '', text)
        
        return text.strip()
    
    def _calculate_quality_score(self, content: str) -> float:
        """Calculate content quality score."""
        if not content:
            return 0.0
        
        word_count = len(content.split())
        if word_count < 10:
            return 0.1
        
        # Basic quality indicators
        has_menu_keywords = any(keyword in content.lower() for keyword in 
                               ['menu', 'dish', 'cuisine', 'chef', 'restaurant'])
        has_reasonable_length = 50 <= word_count <= 5000
        
        base_score = 0.3
        if has_menu_keywords:
            base_score += 0.4
        if has_reasonable_length:
            base_score += 0.3
        
        return min(1.0, base_score)
    
    def _extract_structured_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract structured data from page."""
        structured = {}
        
        # Open Graph data
        og_data = {}
        for tag in soup.find_all('meta', property=lambda x: x and x.startswith('og:')):
            property_name = tag.get('property')[3:]  # Remove 'og:' prefix
            og_data[property_name] = tag.get('content')
        
        if og_data:
            structured['open_graph'] = og_data
        
        # Page title
        title_tag = soup.find('title')
        if title_tag:
            structured['page_title'] = title_tag.get_text(strip=True)
        
        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            structured['meta_description'] = meta_desc.get('content')
        
        return structured
    
    def _detect_language(self, text: str) -> str:
        """Detect language of text."""
        try:
            return detect_language(text)
        except:
            return 'unknown'
    
    def _translate_content(self, content: str, source_lang: str) -> Optional[str]:
        """Translate content to English using GPT-4o for better handling of global languages."""
        try:
            # Use GPT-4o specifically for translation as mentioned in requirements
            translation_prompt = f"""You are a professional translator. Translate the following {source_lang} text to English. 
            Preserve all restaurant-specific information including menu items, prices, chef names, location details, and cuisine descriptions.
            Maintain the structure and formatting of the original text.
            
            Text to translate:
            {content[:4000]}"""  # Increased content limit for better context
            
            response = call_openai_chat(
                system_prompt="You are a professional translator fluent in all languages. Preserve all restaurant-specific details.",
                user_prompt=translation_prompt,
                force_model="gpt-4o"  # Use GPT-4o as specified in requirements
            )
            
            if response:
                logger.info(f"Successfully translated content from {source_lang} to English")
                return response
            else:
                logger.warning(f"Translation failed, using original content")
                return content
            
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return content  # Return original content as fallback
    
    def _call_llm(self, system_prompt: str, user_prompt: str, response_format=None, model="gpt-4o-mini") -> Optional[str]:
        """Call LLM with fallback methods."""
        # Fallback to direct OpenAI client first (more reliable)
        try:
            if openai_client and openai_client.api_key:
                response = openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format=response_format
                )
                return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Direct OpenAI call failed: {e}")
        
        # Try token manager as fallback
        try:
            response = call_openai_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                force_model=model,
                response_format=response_format
            )
            
            if response:
                return response
        except Exception as e:
            logger.debug(f"Token manager call failed: {e}")
        
        return None
    
    def _dismiss_popups(self):
        """Dismiss popups and overlays."""
        try:
            if not self.driver:
                return
                
            # Common popup close selectors
            selectors = [
                "button[aria-label*='close']",
                "button[class*='close']",
                ".modal-close",
                ".popup-close",
                "[data-dismiss='modal']"
            ]
            
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            element.click()
                            time.sleep(0.5)
                except:
                    continue
        except Exception as e:
            logger.debug(f"Popup dismissal failed: {e}")
    
    def _is_relevant_image_url(self, img_url: str) -> bool:
        """Filter out irrelevant images."""
        img_url_lower = img_url.lower()
        
        skip_patterns = [
            'logo', 'icon', 'favicon', 'avatar', 'profile',
            'banner', 'ad', 'advertisement', 'sponsor',
            'social', 'facebook', 'instagram', 'twitter',
            'arrow', 'button', 'nav', 'menu-icon',
            'pixel', 'tracking', 'analytics'
        ]
        
        if any(pattern in img_url_lower for pattern in skip_patterns):
            return False
        
        parsed_url = urlparse(img_url)
        path = parsed_url.path.lower()
        
        return any(path.endswith(fmt) for fmt in SUPPORTED_FORMATS)
    
    def _download_image(self, img_url: str, save_path: Path) -> Optional[Path]:
        """Download and save an image."""
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = self.session.get(img_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Validate image
            image = Image.open(BytesIO(response.content))
            if image.width < 200 or image.height < 200:
                return None
            
            # Convert to RGB and save as JPEG
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
            
            image.save(save_path, 'JPEG', quality=85)
            return save_path
            
        except Exception as e:
            logger.debug(f"Image download failed for {img_url}: {e}")
            return None
    
    # Image categorization is now handled by the ImageIntegrator in processors/
    # This method has been removed as it was dead code - not called in current workflow
    
    def _extract_json_from_response(self, response: str) -> Optional[str]:
        """Extract JSON from LLM response that may contain extra text."""
        try:
            # Find JSON within the response
            start_idx = response.find('{')
            if start_idx == -1:
                return None
            
            # Find the matching closing brace
            brace_count = 0
            end_idx = start_idx
            
            for i, char in enumerate(response[start_idx:], start_idx):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break
            
            if brace_count == 0:
                json_str = response[start_idx:end_idx + 1]
                # Basic cleanup
                json_str = re.sub(r'\\(?!["\\/bfnrt])', r'\\\\', json_str)  # Fix unescaped backslashes
                return json_str
            
            return None
        except Exception as e:
            logger.error(f"JSON extraction failed: {e}")
            return None
    
    def _get_timezone_info(self, location_text: str) -> Dict[str, Any]:
        """Extract timezone information for global restaurants."""
        timezone_info = {
            'local_timezone': None,
            'utc_offset': None,
            'current_local_time': None
        }
        
        try:
            # Use LLM to extract location information
            location_prompt = f"""Extract the country and city from this restaurant location text: {location_text}
            
            Respond with JSON:
            {{
                "country": "country name",
                "city": "city name",
                "region": "state/province if applicable"
            }}"""
            
            response = self._call_llm(
                system_prompt="You are a location extraction expert. Extract country and city information accurately.",
                user_prompt=location_prompt,
                response_format={"type": "json_object"},
                model="gpt-4o-mini"
            )
            
            if response:
                location_data = json.loads(response)
                country = location_data.get('country', '').strip()
                city = location_data.get('city', '').strip()
                
                # Map common countries to their primary timezones
                country_timezones = {
                    'france': 'Europe/Paris',
                    'italy': 'Europe/Rome',
                    'spain': 'Europe/Madrid',
                    'united kingdom': 'Europe/London',
                    'uk': 'Europe/London',
                    'germany': 'Europe/Berlin',
                    'japan': 'Asia/Tokyo',
                    'singapore': 'Asia/Singapore',
                    'australia': 'Australia/Sydney',
                    'united states': 'America/New_York',
                    'usa': 'America/New_York',
                    'canada': 'America/Toronto',
                    'mexico': 'America/Mexico_City',
                    'argentina': 'America/Argentina/Buenos_Aires',
                    'brazil': 'America/Sao_Paulo',
                    'chile': 'America/Santiago',
                    'peru': 'America/Lima',
                    'india': 'Asia/Kolkata',
                    'china': 'Asia/Shanghai',
                    'south korea': 'Asia/Seoul',
                    'thailand': 'Asia/Bangkok',
                    'philippines': 'Asia/Manila',
                    'indonesia': 'Asia/Jakarta',
                    'malaysia': 'Asia/Kuala_Lumpur',
                    'vietnam': 'Asia/Ho_Chi_Minh',
                    'south africa': 'Africa/Johannesburg',
                    'egypt': 'Africa/Cairo',
                    'morocco': 'Africa/Casablanca',
                    'turkey': 'Europe/Istanbul',
                    'russia': 'Europe/Moscow',
                    'israel': 'Asia/Jerusalem',
                    'uae': 'Asia/Dubai',
                    'lebanon': 'Asia/Beirut',
                    'jordan': 'Asia/Amman'
                }
                
                # Try to get timezone
                timezone_name = country_timezones.get(country.lower())
                if timezone_name:
                    try:
                        tz = pytz.timezone(timezone_name)
                        current_time = datetime.now(tz)
                        timezone_info = {
                            'local_timezone': timezone_name,
                            'utc_offset': current_time.strftime('%z'),
                            'current_local_time': current_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                            'country': country,
                            'city': city
                        }
                    except Exception as e:
                        logger.error(f"Timezone processing failed: {e}")
        
        except Exception as e:
            logger.error(f"Timezone extraction failed: {e}")
        
        return timezone_info
    
    def _get_filtered_links_and_landing(self, url: str) -> Tuple[List[Dict], Optional[object]]:
        """Get filtered relevant links and landing page using existing scrape_utils logic."""
        try:
            # Step 1: Check for English version of the website
            original_website = NewWebsite(url)
            original_content = (original_website.text or "").strip()

            if not original_content or original_content.lower().startswith("error"):
                logger.warning(f"Scraped landing page is empty or error for {url}")
                return [], None

            english_url = url  # default fallback
            try:
                english_response = self._call_llm(
                    system_prompt=select_english_version_prompt,
                    user_prompt=original_content[:4000],
                    model="gpt-4o"
                )
                if english_response and english_response.strip().lower() != "no english version":
                    english_url = english_response.strip()
                    logger.info(f"English version detected for {url} → {english_url}")
            except Exception as e:
                logger.warning(f"Failed to detect English version for {url}: {e}")

            # Step 2: Load the appropriate website
            website = NewWebsite(english_url)
            content = (website.text or "").strip()

            if not content or content.lower().startswith("error"):
                logger.warning(f"Scraped landing page is empty or error for {english_url}")
                return [], None

            # Step 2.5: Detect language and translate if needed
            detected_lang = self._detect_language(content)
            if detected_lang != "en":
                logger.info(f"Translating from {detected_lang} to English for {english_url}")
                translated_content = self._translate_content(content, detected_lang)
                if translated_content:
                    website.text = translated_content

            # Step 3: Extract relevant links using LLM
            response_content = self._call_llm(
                system_prompt=link_system_prompt,
                user_prompt=get_links_user_prompt(website),
                response_format={"type": "json_object"},
                model="gpt-4o-mini"
            )

            # Step 4: Parse JSON response
            if response_content:
                try:
                    result = json.loads(response_content)
                except json.JSONDecodeError:
                    # Try to extract JSON from response
                    cleaned_response = self._extract_json_from_response(response_content)
                    if cleaned_response:
                        try:
                            result = json.loads(cleaned_response)
                        except json.JSONDecodeError:
                            logger.error(f"JSON decode error for links from {english_url}")
                            return [], website
                    else:
                        logger.error(f"JSON decode error for links from {english_url}")
                        return [], website

                # Step 5: Filter out irrelevant links by type
                filtered_links = [link for link in result.get("links", []) 
                                if self._is_relevant_link(link.get("type", ""))]
                return filtered_links, website
            
            return [], website

        except Exception as e:
            logger.error(f"Error getting filtered links for {url}: {e}")
            return [], None
    
    def _is_relevant_link(self, link_type: str) -> bool:
        """Filter irrelevant links based on type."""
        irrelevant_sections = [
            "faq", "career", "gallery", "event", "wedding", "spa", "hotel", "press", "media", "newsletter"
        ]
        return not any(bad in link_type.lower() for bad in irrelevant_sections)
    
    def _scrape_multiple_pages(self, filtered_links: List[Dict], landing_page: object) -> str:
        """Scrape multiple pages and combine content."""
        all_content = []
        
        # Add landing page content
        if landing_page and landing_page.text:
            all_content.append(f"=== Landing Page ===\n{landing_page.text}")
        
        # Scrape linked pages with concurrent processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_link = {
                executor.submit(self._scrape_single_link, link): link 
                for link in filtered_links[:10]  # Limit to 10 additional pages
            }
            
            for future in concurrent.futures.as_completed(future_to_link):
                link = future_to_link[future]
                try:
                    page_content = future.result(timeout=30)
                    if page_content:
                        all_content.append(f"=== {link.get('type', 'Page')} ===\n{page_content}")
                except Exception as e:
                    logger.error(f"Error scraping linked page {link.get('url', 'Unknown')}: {e}")
        
        return "\n\n".join(all_content)
    
    def _scrape_single_link(self, link_obj: Dict) -> Optional[str]:
        """Scrape a single linked page."""
        try:
            page = NewWebsite(link_obj["url"])
            text = page.text.strip() if page.text else ""
            
            if not text:
                return None

            # Detect language and translate if needed
            detected_lang = self._detect_language(text)
            if detected_lang != "en":
                logger.info(f"Translating from {detected_lang} to English for {link_obj['url']}")
                translated_text = self._translate_content(text, detected_lang)
                if translated_text:
                    text = translated_text
            
            return text
            
        except Exception as e:
            logger.error(f"Error scraping linked page {link_obj['url']}: {e}")
            return None
    
    def _cleanup(self):
        """Clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


def scrape_restaurants_batch(restaurant_list: List[Dict[str, str]], 
                           batch_size: int = 50, 
                           max_workers: int = 10, 
                           pause_between_batches: int = 30,
                           save_to_db: bool = True,
                           max_images: int = 10) -> Dict[str, Any]:
    """
    Batch process multiple restaurants using existing concurrent patterns from scrape_utils.py.
    
    Args:
        restaurant_list: List of dicts with 'url' and 'name' keys
        batch_size: Number of restaurants per batch (from scrape_utils.py pattern)
        max_workers: Maximum concurrent workers
        pause_between_batches: Seconds to pause between batches
        save_to_db: Whether to save to database
        max_images: Maximum images per restaurant
        
    Returns:
        Summary of batch processing results
    """
    total_restaurants = len(restaurant_list)
    logger.info(f"Starting batch processing of {total_restaurants} restaurants")
    
    # Use existing batch configuration pattern from scrape_utils.py
    results_dir = Path("batch_scraping_results")
    results_dir.mkdir(exist_ok=True)
    
    batch_results = []
    total_processed = 0
    successful_scrapes = 0
    failed_scrapes = 0
    translation_count = 0
    start_time = datetime.now()
    
    try:
        # Process in batches using existing pattern
        for batch_start in range(0, total_restaurants, batch_size):
            batch_end = min(batch_start + batch_size, total_restaurants)
            batch = restaurant_list[batch_start:batch_end]
            batch_num = batch_start // batch_size + 1
            
            logger.info(f"Processing batch {batch_num}: restaurants {batch_start+1}-{batch_end}")
            
            # Use concurrent processing pattern from scrape_utils.py
            batch_result = {
                'batch_number': batch_num,
                'batch_start': batch_start,
                'restaurants': [],
                'timestamp': datetime.now().isoformat()
            }
            
            # Process current batch with ThreadPoolExecutor (like scrape_utils.py)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_restaurant = {
                    executor.submit(_scrape_single_restaurant_wrapper, restaurant, save_to_db, max_images): restaurant 
                    for restaurant in batch
                }
                
                for future in concurrent.futures.as_completed(future_to_restaurant):
                    restaurant = future_to_restaurant[future]
                    try:
                        result = future.result(timeout=300)  # 5 minute timeout
                        batch_result['restaurants'].append(result)
                        
                        # Update counters
                        total_processed += 1
                        if result.get('scraping_success'):
                            successful_scrapes += 1
                        else:
                            failed_scrapes += 1
                        
                        if result.get('llm_analysis', {}).get('original_language'):
                            translation_count += 1
                            
                    except Exception as e:
                        logger.error(f"Failed to process {restaurant.get('name', 'Unknown')}: {e}")
                        batch_result['restaurants'].append({
                            'restaurant_name': restaurant.get('name', 'Unknown'),
                            'url': restaurant.get('url', ''),
                            'error': str(e),
                            'scraping_success': False
                        })
                        failed_scrapes += 1
                        total_processed += 1
            
            batch_results.append(batch_result)
            
            # Save batch results
            batch_file = results_dir / f"batch_{batch_num:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(batch_file, 'w') as f:
                json.dump(batch_result, f, indent=2, default=str)
            
            logger.info(f"Batch {batch_num} completed: {len([r for r in batch_result['restaurants'] if r.get('scraping_success')])} successful")
            
            # Pause between batches (like scrape_utils.py PAUSE_BETWEEN_BATCHES)
            if batch_end < total_restaurants:
                logger.info(f"Pausing {pause_between_batches}s before next batch...")
                time.sleep(pause_between_batches)
    
    except Exception as e:
        logger.error(f"Batch processing interrupted: {e}")
    
    finally:
        # Generate final summary
        end_time = datetime.now()
        processing_time = end_time - start_time
        
        summary = {
            'total_restaurants': total_restaurants,
            'processed_count': total_processed,
            'successful_count': successful_scrapes,
            'failed_count': failed_scrapes,
            'translation_count': translation_count,
            'processing_time': str(processing_time),
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'average_time_per_restaurant': str(processing_time / max(total_processed, 1)),
            'success_rate': successful_scrapes / max(total_processed, 1) * 100
        }
        
        # Save final summary
        summary_file = results_dir / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        logger.info(f"Batch processing completed. {successful_scrapes}/{total_processed} successful. Summary: {summary_file}")
        return summary


def _scrape_single_restaurant_wrapper(restaurant: Dict[str, str], save_to_db: bool, max_images: int) -> Dict[str, Any]:
    """Wrapper function for scraping a single restaurant in batch mode."""
    scraper = UnifiedRestaurantScraper()
    try:
        return scraper.scrape_restaurant_complete(
            url=restaurant['url'],
            restaurant_name=restaurant['name'],
            max_images=max_images,
            save_to_db=save_to_db
        )
    except Exception as e:
        logger.error(f"Error scraping {restaurant['name']}: {e}")
        return {
            'restaurant_name': restaurant['name'],
            'url': restaurant['url'],
            'error': str(e),
            'scraping_success': False
        }
    finally:
        scraper._cleanup()


# Convenience function for easy usage
def scrape_restaurant_unified(url: str, restaurant_name: str, multi_page: bool = True, **kwargs) -> Dict[str, Any]:
    """Convenience function to scrape a restaurant with unified scraper."""
    scraper = UnifiedRestaurantScraper()
    try:
        return scraper.scrape_restaurant_complete(url, restaurant_name, multi_page=multi_page, **kwargs)
    finally:
        scraper._cleanup()


if __name__ == "__main__":
    # Test the unified scraper
    test_url = "https://www.hisafranko.com/"
    test_name = "Hiša Franko"
    
    result = scrape_restaurant_unified(test_url, test_name, max_images=5)
    print(json.dumps(result, indent=2, default=str))