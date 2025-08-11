"""
ImageAI Service Layer - Centralized AI-powered image categorization and labeling.

This service provides a clean interface for AI image processing that can be used
by both Django components and data pipeline scrapers without circular dependencies.
"""

import os
import time
import logging
import base64
import requests
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json

from PIL import Image
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)

class ImageAIService:
    """
    Centralized service for AI-powered image categorization and labeling.
    
    This service encapsulates all OpenAI Vision API interactions and provides
    a clean interface for image analysis without external dependencies.
    """
    
    # Standard restaurant image categories used across the application
    STANDARD_CATEGORIES = [
        'food',
        'interior',
        'exterior',
        'chef',
        'staff',
        'ambiance',
        'presentation',
        'ingredients',
        'bar',
        'menu_item',        # Legacy category for menu/food items
        'scenery_ambiance', # Legacy category for ambiance/interior
        'uncategorized'
    ]
    
    def __init__(self):
        """Initialize the ImageAI service with OpenAI client and S3 support."""
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.max_retries = 3
        self.retry_delay = 2
        
        # S3 Configuration for image processing
        try:
            from services.s3_service import get_s3_service
            self.s3_service = get_s3_service()
            self.s3_enabled = True
            logger.info("ImageAI service initialized with S3 support")
        except ImportError:
            logger.warning("S3 service not available, falling back to URL/local processing only")
            self.s3_service = None
            self.s3_enabled = False
        
    def categorize_image_with_ai(self, image_identifier: str) -> Dict:
        """
        Categorize a restaurant image using OpenAI Vision API.
        
        Args:
            image_identifier: S3 URL, S3 key, HTTP URL, or local path to the image
            
        Returns:
            dict: {
                'category': str,
                'labels': List[str],
                'description': str,
                'category_confidence': float,
                'description_confidence': float
            }
        """
        try:
            # Validate image identifier
            if not image_identifier:
                return self._get_default_result("No image identifier provided")
                
            # Process image based on type (S3 URL, S3 key, HTTP URL, or local path)
            image_data = None
            
            if self.s3_enabled and self._is_s3_url(image_identifier):
                # S3 URL (https://bucket.s3.region.amazonaws.com/key)
                s3_key = self._extract_s3_key_from_url(image_identifier)
                image_data = self._load_s3_image(s3_key)
                logger.info(f"Processing S3 URL: {image_identifier}")
                
            elif self.s3_enabled and self._is_s3_key(image_identifier):
                # S3 key (restaurant-images/name/file.jpg)
                image_data = self._load_s3_image(image_identifier)
                logger.info(f"Processing S3 key: {image_identifier}")
                
            elif image_identifier.startswith(('http://', 'https://')):
                # HTTP/HTTPS URL
                image_data = self._download_image(image_identifier)
                logger.info(f"Processing HTTP URL: {image_identifier}")
                
            else:
                # Local path
                image_data = self._load_local_image(image_identifier)
                logger.info(f"Processing local path: {image_identifier}")
                
            if not image_data:
                return self._get_default_result("Failed to load image")
                
            # Get AI analysis
            ai_result = self._analyze_image_with_openai(image_data)
            
            # Validate and normalize results
            return self._normalize_ai_result(ai_result)
            
        except Exception as e:
            logger.error(f"AI categorization failed for {image_identifier}: {str(e)}")
            return self._get_default_result(f"Error: {str(e)}")
    
    def categorize_multiple_images(self, image_urls: List[str]) -> List[Dict]:
        """
        Categorize multiple images with rate limiting and error handling.
        
        Args:
            image_urls: List of image URLs or paths
            
        Returns:
            List[dict]: Results for each image
        """
        results = []
        
        for i, url in enumerate(image_urls):
            try:
                result = self.categorize_image_with_ai(url)
                results.append({
                    'url': url,
                    'index': i,
                    **result
                })
                
                # Rate limiting - avoid hitting OpenAI API limits
                if i < len(image_urls) - 1:
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Failed to process image {i} ({url}): {str(e)}")
                results.append({
                    'url': url,
                    'index': i,
                    **self._get_default_result(f"Processing error: {str(e)}")
                })
                
        return results
    
    def categorize_s3_images_batch(self, s3_keys: List[str], max_workers: int = 3) -> List[Dict]:
        """
        Batch categorize multiple S3 images with parallel processing.
        
        Args:
            s3_keys: List of S3 keys to process
            max_workers: Number of parallel workers
            
        Returns:
            List[dict]: Results for each S3 image
        """
        if not self.s3_enabled:
            logger.error("S3 batch processing requested but S3 not available")
            return [self._get_default_result("S3 not available") for _ in s3_keys]
        
        results = []
        
        # Process in smaller batches to avoid rate limits
        from concurrent.futures import ThreadPoolExecutor
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_key = {
                executor.submit(self.categorize_image_with_ai, key): key 
                for key in s3_keys
            }
            
            for future in future_to_key:
                s3_key = future_to_key[future]
                try:
                    result = future.result(timeout=60)
                    result['s3_key'] = s3_key
                    results.append(result)
                except Exception as e:
                    logger.error(f"Batch processing failed for {s3_key}: {e}")
                    error_result = self._get_default_result(f"Batch error: {str(e)}")
                    error_result['s3_key'] = s3_key
                    results.append(error_result)
                
                # Rate limiting between requests
                import time
                time.sleep(0.5)
        
        logger.info(f"Batch processed {len(results)} S3 images")
        return results
    
    def get_category_suggestions(self, description: str) -> List[str]:
        """
        Get category suggestions based on image description.
        
        Args:
            description: Text description of the image
            
        Returns:
            List[str]: Suggested categories in order of relevance
        """
        description_lower = description.lower()
        suggestions = []
        
        # Food-related keywords
        food_keywords = ['food', 'dish', 'meal', 'cuisine', 'plate', 'bowl', 'recipe', 'cooking']
        if any(keyword in description_lower for keyword in food_keywords):
            suggestions.append('food')
            
        # Interior keywords
        interior_keywords = ['interior', 'dining', 'table', 'chair', 'decoration', 'lighting']
        if any(keyword in description_lower for keyword in interior_keywords):
            suggestions.append('interior')
            
        # Exterior keywords
        exterior_keywords = ['exterior', 'building', 'facade', 'entrance', 'outdoor', 'terrace']
        if any(keyword in description_lower for keyword in exterior_keywords):
            suggestions.append('exterior')
            
        # Chef/staff keywords
        people_keywords = ['chef', 'staff', 'person', 'people', 'cook', 'waiter', 'server']
        if any(keyword in description_lower for keyword in people_keywords):
            suggestions.extend(['chef', 'staff'])
            
        # Bar keywords
        bar_keywords = ['bar', 'cocktail', 'drink', 'wine', 'bottle', 'glass']
        if any(keyword in description_lower for keyword in bar_keywords):
            suggestions.append('bar')
            
        # Default to uncategorized if no matches
        if not suggestions:
            suggestions.append('uncategorized')
            
        return suggestions
    
    def validate_category(self, category: str) -> str:
        """
        Validate and normalize category name.
        
        Args:
            category: Category name to validate
            
        Returns:
            str: Valid category name
        """
        if not category:
            return 'uncategorized'
            
        category_lower = category.lower().strip()
        
        # Direct match
        if category_lower in self.STANDARD_CATEGORIES:
            return category_lower
            
        # Fuzzy matching for common variations
        category_mappings = {
            'dining': 'interior',
            'kitchen': 'food',
            'restaurant': 'interior',
            'building': 'exterior',
            'cocktails': 'bar',
            'drinks': 'bar',
            'wine': 'bar',
            'team': 'staff',
            'cook': 'chef',
            'atmosphere': 'scenery_ambiance',  # Map to legacy category
            'mood': 'scenery_ambiance',
            'decor': 'scenery_ambiance',
            'menu': 'menu_item',              # Map to legacy category
            'dish': 'menu_item',
            'plate': 'menu_item',
            'meal': 'menu_item'
        }
        
        return category_mappings.get(category_lower, 'uncategorized')
    
    def _download_image(self, image_url: str) -> Optional[bytes]:
        """Download image from URL."""
        try:
            response = requests.get(image_url, timeout=30, stream=True)
            response.raise_for_status()
            
            # Check content type
            content_type = response.headers.get('content-type', '')
            if not content_type.startswith('image/'):
                logger.warning(f"URL does not appear to be an image: {content_type}")
                return None
                
            return response.content
            
        except Exception as e:
            logger.error(f"Failed to download image from {image_url}: {str(e)}")
            return None
    
    def _load_local_image(self, image_path: str) -> Optional[bytes]:
        """Load image from local file system."""
        try:
            path = Path(image_path)
            if not path.exists():
                logger.error(f"Image file not found: {image_path}")
                return None
                
            return path.read_bytes()
            
        except Exception as e:
            logger.error(f"Failed to load local image {image_path}: {str(e)}")
            return None
    
    def _load_s3_image(self, s3_key: str) -> Optional[bytes]:
        """Load image from S3."""
        try:
            if not self.s3_enabled:
                logger.error("S3 not available but S3 image requested")
                return None
                
            image_data = self.s3_service.download_from_s3(s3_key)
            if image_data:
                logger.debug(f"Successfully loaded S3 image: {s3_key}")
                return image_data
            else:
                logger.error(f"Failed to download S3 image: {s3_key}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load S3 image {s3_key}: {str(e)}")
            return None
    
    def _is_s3_url(self, url: str) -> bool:
        """Check if URL is an S3 URL."""
        if not self.s3_enabled:
            return False
        return (url.startswith('https://') and 
                '.s3.' in url and 
                '.amazonaws.com/' in url)
    
    def _is_s3_key(self, identifier: str) -> bool:
        """Check if identifier is an S3 key (not a URL or local path)."""
        if not self.s3_enabled:
            return False
        # S3 keys don't start with http/https and contain forward slashes
        return (not identifier.startswith(('http://', 'https://')) and 
                not identifier.startswith('/') and 
                '/' in identifier and
                any(identifier.startswith(path) for path in self.s3_service.base_paths.values()))
    
    def _extract_s3_key_from_url(self, s3_url: str) -> str:
        """Extract S3 key from S3 URL."""
        # URL format: https://bucket.s3.region.amazonaws.com/key/path/file.jpg
        try:
            from urllib.parse import urlparse
            parsed = urlparse(s3_url)
            # Remove leading slash from path
            s3_key = parsed.path.lstrip('/')
            return s3_key
        except Exception as e:
            logger.error(f"Failed to extract S3 key from URL {s3_url}: {e}")
            return ""
    
    def _analyze_image_with_openai(self, image_data: bytes) -> Dict:
        """Analyze image using OpenAI Vision API."""
        try:
            # Convert image to base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # Prepare prompt for restaurant image analysis
            prompt = f"""
            Analyze this restaurant image and provide:
            1. Category: Choose the most appropriate category from: {', '.join(self.STANDARD_CATEGORIES)}
               Priority mapping: food/dishes → menu_item, interior/atmosphere → scenery_ambiance
            2. Labels: 3-5 descriptive tags (comma-separated)
            3. Description: Brief description (1-2 sentences)
            4. Category confidence: Score 0.0-1.0 for category accuracy
            5. Description confidence: Score 0.0-1.0 for description quality
            
            Focus on restaurant-specific elements. Use menu_item for food/dishes, scenery_ambiance for interior/atmosphere.
            
            Return as JSON:
            {{
                "category": "category_name",
                "labels": ["label1", "label2", "label3"],
                "description": "Brief description",
                "category_confidence": 0.85,
                "description_confidence": 0.90
            }}
            """
            
            # Make API call with retries
            for attempt in range(self.max_retries):
                try:
                    response = self.openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{image_base64}"
                                        }
                                    }
                                ]
                            }
                        ],
                        max_tokens=500,
                        temperature=0.3
                    )
                    
                    # Parse response
                    content = response.choices[0].message.content.strip()
                    
                    # Extract JSON from response
                    if content.startswith('```json'):
                        content = content[7:]
                    if content.endswith('```'):
                        content = content[:-3]
                    
                    result = json.loads(content.strip())
                    logger.info("Successfully analyzed image with OpenAI Vision API")
                    return result
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON response (attempt {attempt + 1}): {e}")
                    if attempt == self.max_retries - 1:
                        # Fallback to text parsing
                        return self._parse_text_response(content)
                        
                except Exception as e:
                    logger.error(f"OpenAI API call failed (attempt {attempt + 1}): {str(e)}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                    else:
                        raise
                        
        except Exception as e:
            logger.error(f"Image analysis failed: {str(e)}")
            raise
    
    def _parse_text_response(self, content: str) -> Dict:
        """Parse non-JSON response as fallback."""
        try:
            # Simple text parsing fallback
            result = {
                'category': 'uncategorized',
                'labels': [],
                'description': content[:200] if content else 'No description available',
                'category_confidence': 0.5,
                'description_confidence': 0.5
            }
            
            # Try to extract category from text
            content_lower = content.lower()
            for category in self.STANDARD_CATEGORIES:
                if category in content_lower:
                    result['category'] = category
                    result['category_confidence'] = 0.7
                    break
                    
            return result
            
        except Exception:
            return self._get_default_result("Failed to parse response")
    
    def _normalize_ai_result(self, ai_result: Dict) -> Dict:
        """Normalize and validate AI analysis result."""
        try:
            # Validate category
            category = self.validate_category(ai_result.get('category', ''))
            
            # Validate labels
            labels = ai_result.get('labels', [])
            if isinstance(labels, str):
                labels = [label.strip() for label in labels.split(',')]
            labels = [label for label in labels if label and len(label) > 0][:5]  # Max 5 labels
            
            # Validate description
            description = ai_result.get('description', '').strip()
            if len(description) > 500:
                description = description[:500] + "..."
                
            # Validate confidence scores
            category_confidence = float(ai_result.get('category_confidence', 0.8))
            category_confidence = max(0.0, min(1.0, category_confidence))
            
            description_confidence = float(ai_result.get('description_confidence', 0.8))
            description_confidence = max(0.0, min(1.0, description_confidence))
            
            return {
                'category': category,
                'labels': labels,
                'description': description,
                'category_confidence': category_confidence,
                'description_confidence': description_confidence
            }
            
        except Exception as e:
            logger.error(f"Failed to normalize AI result: {str(e)}")
            return self._get_default_result("Normalization error")
    
    def _get_default_result(self, error_message: str = "") -> Dict:
        """Get default result for failed analysis."""
        return {
            'category': 'uncategorized',
            'labels': [],
            'description': error_message or 'Unable to analyze image',
            'category_confidence': 0.0,
            'description_confidence': 0.0
        }


# Singleton instance for global use
_image_ai_service = None

def get_image_ai_service() -> ImageAIService:
    """
    Get singleton instance of ImageAI service.
    
    Returns:
        ImageAIService: Singleton service instance
    """
    global _image_ai_service
    if _image_ai_service is None:
        _image_ai_service = ImageAIService()
    return _image_ai_service