"""
Enhanced Restaurant Scraper with Ethical Scraping Techniques

This module implements advanced but ethical scraping techniques to handle
websites with access restrictions while respecting robots.txt and rate limits.
"""

import time
import random
import logging
import requests
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import json
import re
from datetime import datetime, timedelta
import hashlib

# Selenium imports for JavaScript handling
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains

# BeautifulSoup for HTML parsing
from bs4 import BeautifulSoup, Comment

# Setup portfolio paths for cross-component imports
import sys
from pathlib import Path
# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline'])

from token_management.token_manager import call_openai_chat, get_token_usage_summary, init_token_manager

logger = logging.getLogger(__name__)

class EthicalScrapingError(Exception):
    """Custom exception for ethical scraping violations."""
    pass

class EnhancedRestaurantScraper:
    """
    Enhanced restaurant scraper with ethical techniques for handling access restrictions.
    """
    
    def __init__(self, token_dir: Optional[Path] = None):
        """
        Initialize the enhanced scraper with ethical configurations.
        
        Args:
            token_dir: Directory for token management
        """
        # Initialize token manager
        if token_dir is None:
            token_dir = Path(__file__).parent.parent.parent.parent / "shared" / "token_management"
        
        try:
            init_token_manager(token_dir)
            logger.info(f"Token manager initialized with directory: {token_dir}")
        except Exception as e:
            logger.warning(f"Token manager initialization failed: {e}")
        
        self.session = requests.Session()
        self.robots_cache = {}
        self.rate_limits = {}
        self.failed_attempts = {}
        
        # User agent rotation for ethical diversity
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
        ]
        
        # Configure session with ethical defaults
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Chrome options for JavaScript rendering
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)
        self.chrome_options.add_argument('--window-size=1920,1080')
        
        logger.info("Enhanced restaurant scraper initialized with ethical configurations")
    
    def check_robots_txt(self, base_url: str, path: str = '/') -> bool:
        """
        Check if scraping is allowed by robots.txt.
        
        Args:
            base_url: Base URL of the website
            path: Specific path to check (default: '/')
            
        Returns:
            True if scraping is allowed, False otherwise
        """
        try:
            parsed_url = urlparse(base_url)
            base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            if base_domain in self.robots_cache:
                robot_parser = self.robots_cache[base_domain]
            else:
                robot_parser = RobotFileParser()
                robot_parser.set_url(urljoin(base_domain, '/robots.txt'))
                try:
                    robot_parser.read()
                    self.robots_cache[base_domain] = robot_parser
                except Exception as e:
                    logger.warning(f"Could not read robots.txt for {base_domain}: {e}")
                    # If robots.txt is inaccessible, assume scraping is allowed
                    return True
            
            # Check for our user agent and '*'
            user_agent = self.session.headers.get('User-Agent', '*')
            can_fetch = robot_parser.can_fetch(user_agent, path)
            
            if not can_fetch:
                logger.info(f"Robots.txt disallows scraping {path} on {base_domain}")
            
            return can_fetch
            
        except Exception as e:
            logger.warning(f"Error checking robots.txt: {e}")
            # If there's an error, err on the side of caution and allow
            return True
    
    def respect_rate_limit(self, domain: str, min_delay: float = 1.0, max_delay: float = 3.0):
        """
        Implement respectful rate limiting between requests to the same domain.
        
        Args:
            domain: Domain to apply rate limiting to
            min_delay: Minimum delay in seconds
            max_delay: Maximum delay in seconds
        """
        current_time = time.time()
        
        if domain in self.rate_limits:
            last_request_time = self.rate_limits[domain]
            time_since_last = current_time - last_request_time
            
            # Add extra delay if we've had recent failures
            failure_count = self.failed_attempts.get(domain, 0)
            extra_delay = min(failure_count * 2, 10)  # Max 10 seconds extra delay
            
            required_delay = random.uniform(min_delay, max_delay) + extra_delay
            
            if time_since_last < required_delay:
                sleep_time = required_delay - time_since_last
                logger.info(f"Rate limiting: sleeping {sleep_time:.2f}s for {domain}")
                time.sleep(sleep_time)
        
        self.rate_limits[domain] = current_time
    
    def get_with_retry(self, url: str, max_retries: int = 3) -> Optional[requests.Response]:
        """
        Make HTTP request with intelligent retry logic.
        
        Args:
            url: URL to request
            max_retries: Maximum number of retry attempts
            
        Returns:
            Response object or None if all attempts failed
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        # Respect rate limits
        self.respect_rate_limit(domain)
        
        for attempt in range(max_retries + 1):
            try:
                # Rotate user agent
                self.session.headers['User-Agent'] = random.choice(self.user_agents)
                
                # Add randomized delay between attempts
                if attempt > 0:
                    delay = random.uniform(2, 5) * attempt
                    logger.info(f"Retry attempt {attempt} for {url} after {delay:.1f}s delay")
                    time.sleep(delay)
                
                response = self.session.get(url, timeout=30, allow_redirects=True)
                
                if response.status_code == 200:
                    # Reset failure count on success
                    if domain in self.failed_attempts:
                        del self.failed_attempts[domain]
                    return response
                elif response.status_code == 429:
                    # Rate limited - wait longer
                    wait_time = 60 + random.uniform(10, 30)
                    logger.warning(f"Rate limited by {domain}, waiting {wait_time:.1f}s")
                    time.sleep(wait_time)
                elif response.status_code in [403, 406, 503]:
                    # Potential bot detection - try different approach
                    logger.warning(f"Potential bot detection ({response.status_code}) for {url}")
                    break
                else:
                    logger.warning(f"HTTP {response.status_code} for {url}")
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed for {url}: {e}")
                
                # Increment failure count
                self.failed_attempts[domain] = self.failed_attempts.get(domain, 0) + 1
        
        return None
    
    def get_with_selenium(self, url: str, wait_time: int = 10) -> Optional[str]:
        """
        Use Selenium WebDriver to handle JavaScript-heavy sites.
        
        Args:
            url: URL to scrape
            wait_time: Maximum time to wait for page load
            
        Returns:
            Page source HTML or None if failed
        """
        driver = None
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            
            # Respect rate limits for Selenium requests too
            self.respect_rate_limit(domain, min_delay=2.0, max_delay=5.0)
            
            # Configure Chrome service for container deployment
            # Use environment variables set in Docker container
            chromedriver_path = os.getenv('CHROMEDRIVER_PATH', '/usr/bin/chromedriver')
            chrome_bin = os.getenv('CHROME_BIN', '/usr/bin/chromium')
            
            # Set Chrome binary location
            if os.path.exists(chrome_bin):
                self.chrome_options.binary_location = chrome_bin
            
            # Initialize Chrome driver
            if os.path.exists(chromedriver_path):
                try:
                    service = Service(chromedriver_path)
                    driver = webdriver.Chrome(service=service, options=self.chrome_options)
                    logger.info(f"Successfully initialized Chrome driver: {chromedriver_path}")
                except Exception as e:
                    logger.error(f"Failed to initialize Chrome driver: {e}")
                    # Don't raise exception - let image scraping fail gracefully
                    return None
            else:
                logger.error(f"Chrome driver not found at {chromedriver_path}")
                return None
            
            # Set a random user agent
            user_agent = random.choice(self.user_agents)
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": user_agent})
            
            # Navigate to the page
            driver.get(url)
            
            # Wait for initial page load
            WebDriverWait(driver, wait_time).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Wait a bit more for dynamic content
            time.sleep(random.uniform(2, 4))
            
            # Try to detect and handle common loading indicators
            try:
                # Wait for common loading elements to disappear
                WebDriverWait(driver, 5).until_not(
                    EC.presence_of_element_located((By.CLASS_NAME, "loading"))
                )
            except TimeoutException:
                pass  # No loading indicators found, continue
            
            # Scroll down to trigger any lazy loading
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(1)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            page_source = driver.page_source
            logger.info(f"Successfully loaded {url} with Selenium ({len(page_source)} chars)")
            return page_source
            
        except Exception as e:
            logger.error(f"Selenium failed for {url}: {e}")
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.warning(f"Error closing driver: {e}")
    
    def extract_structured_data(self, html: str, url: str) -> Dict[str, Any]:
        """
        Extract structured data from HTML (JSON-LD, microdata, etc.).
        
        Args:
            html: HTML content
            url: Source URL
            
        Returns:
            Dictionary with extracted structured data
        """
        structured_data = {}
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract JSON-LD structured data
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') in ['Restaurant', 'LocalBusiness', 'FoodEstablishment']:
                        structured_data.update({
                            'name': data.get('name', ''),
                            'description': data.get('description', ''),
                            'address': data.get('address', {}),
                            'telephone': data.get('telephone', ''),
                            'opening_hours': data.get('openingHours', []),
                            'price_range': data.get('priceRange', ''),
                            'cuisine': data.get('servesCuisine', []),
                            'rating': data.get('aggregateRating', {}),
                        })
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.debug(f"Could not parse JSON-LD: {e}")
            
            # Extract Open Graph metadata
            og_data = {}
            for og_tag in soup.find_all('meta', property=lambda x: x and x.startswith('og:')):
                property_name = og_tag.get('property', '').replace('og:', '')
                content = og_tag.get('content', '')
                if property_name and content:
                    og_data[property_name] = content
            
            if og_data:
                structured_data['open_graph'] = og_data
            
            # Extract basic meta information
            title_tag = soup.find('title')
            if title_tag:
                structured_data['page_title'] = title_tag.get_text().strip()
            
            description_meta = soup.find('meta', attrs={'name': 'description'})
            if description_meta:
                structured_data['meta_description'] = description_meta.get('content', '').strip()
            
        except Exception as e:
            logger.warning(f"Error extracting structured data from {url}: {e}")
        
        return structured_data
    
    def clean_and_extract_content(self, html: str, url: str) -> Dict[str, Any]:
        """
        Clean HTML and extract meaningful restaurant content.
        
        Args:
            html: Raw HTML content
            url: Source URL
            
        Returns:
            Dictionary with cleaned and extracted content
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
                element.decompose()
            
            # Remove comments
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()
            
            # Extract main content areas
            content_selectors = [
                'main', '[role="main"]', '.main-content', '#main-content',
                '.content', '#content', '.page-content', '.restaurant-info',
                '.about', '.description', '.menu', '.story'
            ]
            
            main_content = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    main_content = ' '.join([elem.get_text(strip=True) for elem in elements])
                    break
            
            # If no main content found, use body
            if not main_content:
                body = soup.find('body')
                if body:
                    main_content = body.get_text(separator=' ', strip=True)
            
            # Extract specific restaurant information
            restaurant_info = {
                'content': main_content,
                'headings': [h.get_text().strip() for h in soup.find_all(['h1', 'h2', 'h3'])],
                'contact_info': self._extract_contact_info(soup),
                'menu_items': self._extract_menu_content(soup),
                'opening_hours': self._extract_hours(soup),
            }
            
            # Get word count for quality assessment
            word_count = len(main_content.split())
            restaurant_info['word_count'] = word_count
            restaurant_info['quality_score'] = min(word_count / 100, 1.0)  # Quality score 0-1
            
            return restaurant_info
            
        except Exception as e:
            logger.error(f"Error cleaning content from {url}: {e}")
            return {'content': '', 'word_count': 0, 'quality_score': 0.0}
    
    def _extract_contact_info(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract contact information from soup."""
        contact_info = {}
        
        # Look for phone numbers
        phone_patterns = [
            r'\+?[\d\s\-\(\)]{10,}',
            r'tel:[\+\d\-\(\)\s]+',
        ]
        
        text = soup.get_text()
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            if matches:
                contact_info['phone'] = matches[0].strip()
                break
        
        # Look for email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        if emails:
            contact_info['email'] = emails[0]
        
        return contact_info
    
    def _extract_menu_content(self, soup: BeautifulSoup) -> List[str]:
        """Extract menu-related content."""
        menu_items = []
        
        # Look for menu sections
        menu_selectors = ['.menu', '#menu', '.dishes', '.food-items', '.menu-item']
        
        for selector in menu_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text(strip=True)
                if len(text) > 10:  # Only meaningful menu content
                    menu_items.append(text)
        
        return menu_items[:20]  # Limit to 20 items
    
    def _extract_hours(self, soup: BeautifulSoup) -> str:
        """Extract opening hours information."""
        hours_keywords = ['hours', 'opening', 'schedule', 'horaires', 'ouvert']
        
        for keyword in hours_keywords:
            for element in soup.find_all(string=re.compile(keyword, re.I)):
                parent = element.parent
                if parent:
                    text = parent.get_text(strip=True)
                    if len(text) > 20 and len(text) < 200:
                        return text
        
        return ""
    
    def scrape_restaurant(self, url: str, use_selenium: bool = True) -> Optional[Dict[str, Any]]:
        """
        Main scraping method with fallback strategies.
        
        Args:
            url: Restaurant website URL
            use_selenium: Whether to try Selenium if requests fail
            
        Returns:
            Dictionary with scraped restaurant data
        """
        try:
            logger.info(f"Starting enhanced scraping for: {url}")
            
            # Check robots.txt compliance
            if not self.check_robots_txt(url):
                raise EthicalScrapingError(f"Robots.txt disallows scraping for {url}")
            
            html_content = None
            method_used = "unknown"
            
            # First attempt: Regular HTTP request
            response = self.get_with_retry(url)
            if response and response.text:
                html_content = response.text
                method_used = "requests"
                logger.info(f"Successfully scraped {url} using requests")
            
            # Second attempt: Selenium for JavaScript-heavy sites
            elif use_selenium:
                html_content = self.get_with_selenium(url)
                if html_content:
                    method_used = "selenium"
                    logger.info(f"Successfully scraped {url} using Selenium")
            
            if not html_content:
                logger.warning(f"Failed to get content from {url}")
                return None
            
            # Extract structured data
            structured_data = self.extract_structured_data(html_content, url)
            
            # Clean and extract content
            content_data = self.clean_and_extract_content(html_content, url)
            
            # Combine results
            result = {
                'url': url,
                'scraped_at': datetime.now().isoformat(),
                'method_used': method_used,
                'content_length': len(html_content),
                'structured_data': structured_data,
                **content_data
            }
            
            # Use AI to enhance content if quality is good enough
            if result.get('quality_score', 0) > 0.3:
                enhanced_data = self._enhance_with_ai(result)
                result.update(enhanced_data)
            
            logger.info(f"Completed scraping {url} - Quality: {result.get('quality_score', 0):.2f}")
            return result
            
        except EthicalScrapingError as e:
            logger.warning(f"Ethical scraping violation: {e}")
            return None
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    def _enhance_with_ai(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use AI to enhance and structure the scraped content.
        
        Args:
            scraped_data: Raw scraped data
            
        Returns:
            Enhanced data dictionary
        """
        try:
            content = scraped_data.get('content', '')
            if len(content) < 100:
                return {}
            
            # Check token availability
            token_summary = get_token_usage_summary()
            if not token_summary.get('current_model'):
                logger.warning("No tokens available for AI enhancement")
                return {}
            
            prompt = f"""
            Analyze this restaurant website content and extract key information:
            
            Content: {content[:2000]}  # Limit content to avoid token overflow
            
            Please provide a JSON response with:
            {{
                "restaurant_name": "extracted name",
                "cuisine_type": "type of cuisine",
                "description": "concise description (2-3 sentences)",
                "atmosphere": "description of atmosphere/ambiance",
                "specialties": ["dish1", "dish2", "dish3"],
                "price_range": "$ | $$ | $$$ | $$$$",
                "key_features": ["feature1", "feature2"]
            }}
            
            Only include information that is clearly stated in the content.
            """
            
            response = call_openai_chat(
                messages=[{"role": "user", "content": prompt}],
                force_model="gpt-4o-mini",  # Use mini for cost efficiency
                response_format={"type": "json_object"}
            )
            
            if response:
                enhanced_data = json.loads(response)
                logger.info(f"AI enhanced data for {scraped_data.get('url', 'unknown')}")
                return {'ai_enhanced': enhanced_data}
            
        except Exception as e:
            logger.warning(f"AI enhancement failed: {e}")
        
        return {}


def scrape_failed_sites_batch(csv_file: str, max_sites: int = 100, use_selenium: bool = True) -> Dict[str, Any]:
    """
    Batch scrape the sites that previously failed.
    
    Args:
        csv_file: Path to the failed sites CSV
        max_sites: Maximum number of sites to process
        use_selenium: Whether to use Selenium for JavaScript sites
        
    Returns:
        Dictionary with scraping results
    """
    import csv
    import pandas as pd
    
    try:
        # Load failed sites
        df = pd.read_csv(csv_file)
        
        if max_sites:
            df = df.head(max_sites)
        
        # Initialize enhanced scraper
        scraper = EnhancedRestaurantScraper()
        
        results = {
            'total_attempted': len(df),
            'successful': 0,
            'failed': 0,
            'successful_sites': [],
            'still_failed_sites': [],
            'errors': []
        }
        
        for idx, row in df.iterrows():
            restaurant_name = row.get('name', f'Restaurant_{idx}')
            website = row.get('website', '')
            
            if not website:
                continue
            
            try:
                logger.info(f"Processing {idx+1}/{len(df)}: {restaurant_name}")
                
                scraped_data = scraper.scrape_restaurant(website, use_selenium=use_selenium)
                
                if scraped_data and scraped_data.get('quality_score', 0) > 0.2:
                    results['successful'] += 1
                    results['successful_sites'].append({
                        'name': restaurant_name,
                        'website': website,
                        'quality_score': scraped_data.get('quality_score', 0),
                        'word_count': scraped_data.get('word_count', 0),
                        'method': scraped_data.get('method_used', 'unknown')
                    })
                    logger.info(f"✅ Successfully scraped {restaurant_name}")
                else:
                    results['failed'] += 1
                    results['still_failed_sites'].append({
                        'name': restaurant_name,
                        'website': website,
                        'error': 'Low quality content or no content extracted'
                    })
                    logger.warning(f"❌ Still failed: {restaurant_name}")
                
            except Exception as e:
                error_msg = f"Error processing {restaurant_name}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)
                results['failed'] += 1
                results['still_failed_sites'].append({
                    'name': restaurant_name,
                    'website': website,
                    'error': str(e)
                })
        
        # Calculate success rate
        if results['total_attempted'] > 0:
            success_rate = (results['successful'] / results['total_attempted']) * 100
            results['success_rate'] = success_rate
        
        logger.info(f"Batch scraping completed: {results['successful']}/{results['total_attempted']} successful ({results.get('success_rate', 0):.1f}%)")
        return results
        
    except Exception as e:
        logger.error(f"Error in batch scraping: {e}")
        raise


if __name__ == "__main__":
    # Test the enhanced scraper
    scraper = EnhancedRestaurantScraper()
    
    # Test with a sample URL
    test_url = "https://www.example-restaurant.com"
    result = scraper.scrape_restaurant(test_url)
    
    if result:
        print(f"Successfully scraped: Quality {result.get('quality_score', 0):.2f}")
        print(f"Content length: {result.get('word_count', 0)} words")
        print(f"Method used: {result.get('method_used', 'unknown')}")
    else:
        print("Scraping failed")