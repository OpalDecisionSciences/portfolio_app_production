# S3 Integration Plan for Portfolio Application

## Overview
Complete migration from local image storage to AWS S3 for all restaurant images, with backward compatibility and improved performance.

## Current Architecture Issues
1. **Mixed Storage**: Images stored both locally (ImageField) and as URLs (source_url)
2. **Performance**: Local image serving through Django is slower than CDN
3. **Scalability**: Local storage doesn't scale across containers
4. **Backup**: S3 provides better durability and backup

## S3 Integration Strategy

### Phase 1: Infrastructure Setup ✅
- [x] Created `shared/src/services/s3_service.py` - Centralized S3 operations
- [x] Created `data_pipeline/src/scrapers/s3_image_scraper.py` - Direct S3 upload scraper

### Phase 2: Core Module Updates

#### 2.1 ImageAI Service Updates
**File**: `shared/src/services/image_ai_service.py`

**Changes Needed**:
```python
# Add S3 integration
from services.s3_service import get_s3_service

class ImageAIService:
    def __init__(self):
        self.s3_service = get_s3_service()
    
    def categorize_image_with_ai(self, image_identifier):
        """
        Updated to handle:
        1. S3 URLs (https://bucket.s3.region.amazonaws.com/key)
        2. S3 keys (restaurant-images/name/file.jpg)
        3. Local paths (backward compatibility)
        4. HTTP URLs (external images)
        """
        
    def _load_s3_image(self, s3_key_or_url):
        """New method to load images from S3"""
        
    def categorize_s3_images_batch(self, s3_keys):
        """Batch process S3 images for efficiency"""
```

#### 2.2 Django Tasks Updates
**File**: `django_app/src/restaurants/tasks.py`

**Changes Needed**:
```python
from services.s3_service import get_s3_service

@shared_task
def process_image_ai_categorization(image_id):
    """
    Updated to work with S3 URLs:
    - Check if image.s3_url exists first
    - Fall back to image.source_url
    - Fall back to image.image.url (local)
    """

@shared_task  
def scrape_restaurant_images_s3_task(restaurant_id, max_images=15):
    """
    New task using S3 image scraper:
    - Uses s3_image_scraper instead of local scraper
    - Saves S3 URLs directly to RestaurantImage
    """
```

#### 2.3 Unified Restaurant Scraper Updates  
**File**: `data_pipeline/src/scrapers/unified_restaurant_scraper.py`

**Changes Needed**:
```python
from services.s3_service import get_s3_service

class UnifiedRestaurantScraper:
    def __init__(self):
        self.s3_service = get_s3_service()
        # Remove local image_output_dir
    
    def _scrape_images(self, url, restaurant_name, max_images):
        """
        Replace local image scraping with S3 direct upload:
        1. Download image to memory
        2. Upload directly to S3
        3. Return S3 URLs instead of local paths
        """
    
    def _save_images(self, restaurant, scraping_results):
        """
        Updated to save S3 URLs:
        - Save s3_url instead of local image field
        - Save s3_key for management operations
        - Update content_hash and metadata
        """
```

#### 2.4 Comprehensive Restaurant Scraper Updates
**File**: `data_pipeline/src/scrapers/comprehensive_restaurant_scraper.py`

**Changes Needed**:
```python
from services.s3_service import get_s3_service

class ComprehensiveRestaurantScraper:
    async def save_restaurant_images_to_db(self, restaurant, image_data):
        """
        Major update:
        1. Remove local_path handling
        2. Use S3 URLs for all images  
        3. Store S3 metadata in database
        4. Remove Django ImageField usage
        """
```

#### 2.5 Django Model Updates
**File**: `django_app/src/restaurants/models.py`

**Changes Needed**:
```python
class RestaurantImage(models.Model):
    # Keep existing fields for backward compatibility
    image = models.ImageField(upload_to='restaurants/', blank=True)  # Deprecated
    source_url = models.URLField(blank=True)  # Keep for external URLs
    
    # Add new S3 fields
    s3_url = models.URLField(blank=True, help_text="Primary S3 URL for the image")
    s3_key = models.CharField(max_length=500, blank=True, help_text="S3 key for management")
    
    @property
    def get_image_url(self):
        """Smart URL getter - S3 first, then fallbacks"""
        return self.s3_url or self.source_url or (self.image.url if self.image else None)
        
    def migrate_to_s3(self):
        """Method to migrate existing local images to S3"""
```

#### 2.6 Django Views Updates  
**File**: `django_app/src/restaurants/views.py`

**Changes Needed**:
```python
def get_featured_image(restaurant):
    """Update to use get_image_url property"""
    image = restaurant.images.first()
    if image:
        return {
            'id': str(image.id),
            'url': image.get_image_url,  # Uses smart S3-first logic
            'alt': image.alt_text,
            'category': image.ai_category
        }
```

#### 2.7 Management Command Updates
**File**: `django_app/src/restaurants/management/commands/scrape_images.py`

**Changes Needed**:
```python
# Add option to use S3 scraper
def add_arguments(self, parser):
    parser.add_argument('--use-s3', action='store_true', 
                       help='Use S3 direct upload instead of local storage')

def handle_test_url(self, options):
    if options['use_s3']:
        from scrapers.s3_image_scraper import S3RestaurantImageScraper
        scraper = S3RestaurantImageScraper()
    else:
        from scrapers.image_scraper import RestaurantImageScraper  
        scraper = RestaurantImageScraper()
```

### Phase 3: Token Manager S3 Integration

#### 3.1 Token Manager Updates
**File**: `shared/src/token_management/token_manager.py`

**Token manager doesn't directly handle images, but needs S3 for:**

```python
def init_token_manager(project_dir: Path):
    """
    Update S3 logging to also handle image operation logging:
    1. Log S3 upload operations  
    2. Log AI processing operations on S3 images
    3. Store processing state in S3 for distributed systems
    """
    
    # Add S3 state management for distributed token tracking
    if log_storage == 'S3':
        # Store token state in S3 for multi-container deployment
        s3_token_state = S3TokenStateManager()
```

### Phase 4: Migration Strategy

#### 4.1 Data Migration Script
**File**: `django_app/src/restaurants/management/commands/migrate_images_to_s3.py`

```python
class Command(BaseCommand):
    def handle(self, *args, **options):
        """
        Migrate existing local images to S3:
        1. Find all RestaurantImage objects with local files
        2. Upload each to S3 using s3_service
        3. Update database records with S3 URLs
        4. Optionally remove local files
        """
```

#### 4.2 Template Updates
**Files**: All Django templates using restaurant images

```html
<!-- Before -->
{% if restaurant.images.first.image %}
    <img src="{{ restaurant.images.first.image.url }}" />
{% endif %}

<!-- After -->
{% if restaurant.images.first.get_image_url %}
    <img src="{{ restaurant.images.first.get_image_url }}" />
{% endif %}
```

### Phase 5: Performance Optimizations

#### 5.1 CDN Integration
```python
# In settings.py
AWS_S3_CUSTOM_DOMAIN = 'your-cloudfront-domain.cloudfront.net'
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
```

#### 5.2 Image Optimization Pipeline
```python
# Automatic image optimization in s3_service.py
def optimize_for_web(self, image_data):
    """
    1. WebP conversion for modern browsers
    2. Multiple sizes (thumbnail, medium, large)  
    3. Progressive JPEG for better loading
    """
```

## Implementation Order

### Week 1: Core Infrastructure
1. ✅ S3Service creation
2. ✅ S3ImageScraper creation  
3. Update ImageAIService for S3
4. Update Django models with S3 fields

### Week 2: Scraper Updates  
1. Update unified_restaurant_scraper
2. Update comprehensive_restaurant_scraper  
3. Update Django tasks
4. Create migration command

### Week 3: Frontend & Migration
1. Update Django views
2. Update templates
3. Run data migration
4. Test complete pipeline

### Week 4: Optimization & Cleanup
1. Performance testing
2. CDN setup
3. Remove deprecated local image code
4. Documentation updates

## Backward Compatibility Strategy

1. **Dual Support**: Keep both local ImageField AND S3 URL fields
2. **Smart Getters**: Use `get_image_url` property for automatic fallback
3. **Gradual Migration**: Migrate in batches, not all at once
4. **Rollback Plan**: Keep local images until S3 is fully validated

## Testing Strategy

1. **Unit Tests**: Test each S3 operation individually
2. **Integration Tests**: Test complete scraping → S3 → display pipeline  
3. **Load Tests**: Test with bulk image operations
4. **Rollback Tests**: Ensure fallback to local images works

## Success Metrics

1. **Performance**: Page load times with S3 vs local images
2. **Reliability**: S3 upload success rates
3. **Cost**: S3 storage costs vs local storage + bandwidth
4. **Scalability**: Multi-container deployment capability

## Risk Mitigation

1. **AWS Costs**: Monitor S3 usage and implement lifecycle policies
2. **Network Issues**: Implement retry logic and fallback mechanisms
3. **Data Loss**: Ensure migration scripts have rollback capability
4. **Performance**: Use CDN and optimize images before upload