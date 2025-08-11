"""
Restaurant models for the portfolio application.
Zero-CASCADE, Zero-NULL architecture implementation.
"""
from django.db import models, transaction
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import Point
from django.contrib.auth import get_user_model
from django.conf import settings
from django.urls import reverse
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
import uuid
from datetime import datetime, time
import datetime as dt
import json
import hashlib
import re
import pytz

from .base_models import (
    BaseModel, EntityStatus, EmploymentStatus, MenuStatus, CartStatus,
    CartItemStatus, ReviewStatus, EntityEvent, get_system_user,
    get_deleted_restaurant_placeholder, get_deleted_user, get_deleted_cart,
    get_discontinued_item, get_deleted_section, DELETED_RESTAURANT_ID,
    DISCONTINUED_ITEM_ID, DELETED_USER_ID, DELETED_CART_ID, DELETED_SECTION_ID, NEVER_DATE
)


class Restaurant(BaseModel):
    """Main restaurant model with comprehensive information."""
    
    # Basic Information
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)
    
    # Location
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geolocation = gis_models.PointField(srid=4326, null=True, blank=True, spatial_index=True,
                                        help_text="Geographic location as Point for optimized spatial queries")
    
    # Contact
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    
    # Michelin Information
    michelin_stars = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(3)]
    )
    michelin_guide_year = models.IntegerField(null=True, blank=True)
    has_green_star = models.BooleanField(
        default=False, 
        db_index=True, 
        help_text="Michelin Green Star for sustainability"
    )
    
    # Rating and Reviews
    rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    review_count = models.IntegerField(default=0)
    
    # Cuisine and Style
    cuisine_type = models.CharField(max_length=100, blank=True)
    price_range = models.CharField(
        max_length=20,
        choices=[
            ('$', 'Budget'),
            ('$$', 'Moderate'),
            ('$$$', 'Expensive'),
            ('$$$$', 'Very Expensive'),
        ],
        blank=True
    )
    
    # Atmosphere
    atmosphere = models.CharField(max_length=100, blank=True)
    seating_capacity = models.IntegerField(null=True, blank=True)
    has_private_dining = models.BooleanField(default=False)
    
    # Operational
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    opening_hours = models.TextField(blank=True)
    
    # Scraped Data
    original_url = models.URLField(blank=True)
    scraped_at = models.DateTimeField(null=True, blank=True)
    scraped_content = models.TextField(blank=True)
    timezone_info = models.JSONField(null=True, blank=True, help_text="JSON containing timezone and location details")
    
    # Error Tracking - integrates with ScrapingJob system
    has_processing_errors = models.BooleanField(default=False, db_index=True, help_text="Flag for filtering restaurants with processing errors")
    error_count = models.PositiveIntegerField(default=0, help_text="Total number of processing errors encountered")
    last_error_type = models.CharField(max_length=100, blank=True, help_text="Type of most recent error (e.g., 'scraping_failed', 'api_timeout')")
    last_error_at = models.DateTimeField(null=True, blank=True, help_text="When the last error occurred")
    data_quality_score = models.DecimalField(max_digits=3, decimal_places=2, default=1.00, help_text="Data completeness score (0.00-1.00)")
    
    # Multi-restaurant support - NO CASCADE, NO NULL
    parent_group = models.ForeignKey(
        'self', 
        on_delete=models.PROTECT,
        related_name='child_restaurants',
        default=get_deleted_restaurant_placeholder,
        help_text="Parent restaurant group if this is an individual restaurant"
    )
    is_restaurant_group = models.BooleanField(default=False, help_text="True if this represents a restaurant group")
    group_source_url = models.URLField(blank=True, help_text="Original multi-restaurant URL")
    individual_restaurant_index = models.IntegerField(null=True, blank=True,
                                                     help_text="Index of this restaurant within the group")
    
    # Additional metadata beyond BaseModel
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT,
        default=get_system_user,
        related_name='restaurants_created',
        help_text="User who created this restaurant record"
    )
    
    class Meta:
        ordering = ['-michelin_stars', '-rating', 'name']
        indexes = [
            models.Index(fields=['country', 'city']),
            models.Index(fields=['michelin_stars']),
            models.Index(fields=['cuisine_type']),
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['parent_group', 'individual_restaurant_index']),
            models.Index(fields=['is_restaurant_group']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group_source_url', 'individual_restaurant_index'],
                condition=models.Q(individual_restaurant_index__isnull=False),
                name='unique_restaurant_in_group'
            )
        ]
    
    def __str__(self):
        return f"{self.name} ({self.city}, {self.country})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.name}-{self.city}")
        
        # Auto-populate geolocation Point from lat/lng
        if self.latitude and self.longitude and not self.geolocation:
            self.geolocation = Point(float(self.longitude), float(self.latitude), srid=4326)
        
        super().save(*args, **kwargs)
    
    def get_timezone_display(self):
        """Get display-friendly timezone information."""
        if self.timezone_info and isinstance(self.timezone_info, dict):
            timezone_name = self.timezone_info.get('local_timezone', '')
            if timezone_name:
                # Format timezone name for display
                return timezone_name.replace('_', ' ').replace('/', ' / ')
        return 'Unknown'
    
    def get_local_time_info(self):
        """Get current local time information for the restaurant."""
        if self.timezone_info and isinstance(self.timezone_info, dict):
            return {
                'timezone': self.timezone_info.get('local_timezone'),
                'country': self.timezone_info.get('country'),
                'city': self.timezone_info.get('city'),
                'utc_offset': self.timezone_info.get('utc_offset')
            }
        return None
    
    def get_current_local_time(self):
        """Get current time in restaurant's local timezone."""
        if self.timezone_info and self.timezone_info.get('local_timezone'):
            try:
                restaurant_tz = pytz.timezone(self.timezone_info['local_timezone'])
                utc_now = timezone.now()
                return utc_now.astimezone(restaurant_tz)
            except Exception:
                pass
        return timezone.now()
    
    def is_currently_open(self):
        """
        Check if restaurant is currently open based on local time and operating hours.
        Returns: dict with 'is_open' boolean and 'next_change' datetime if available
        """
        if not self.opening_hours:
            return {'is_open': None, 'status': 'Hours not available', 'next_change': None}
        
        local_time = self.get_current_local_time()
        current_day = local_time.strftime('%A').lower()
        current_time = local_time.time()
        
        # Parse opening hours with proper JSON validation
        if self.opening_hours.startswith('{'):
            try:
                hours_data = json.loads(self.opening_hours)
                # Validate that it's a proper dictionary with string keys
                if not isinstance(hours_data, dict):
                    return {'is_open': None, 'status': 'Invalid hours format', 'next_change': None}
                
                # Sanitize keys to prevent injection
                sanitized_hours = {}
                valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                for key, value in hours_data.items():
                    if isinstance(key, str) and key.lower() in valid_days and isinstance(value, str):
                        # Limit value length and sanitize
                        sanitized_value = str(value)[:50]  # Reasonable limit for hours string
                        sanitized_hours[key.lower()] = sanitized_value
                
                hours_data = sanitized_hours
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                return {'is_open': None, 'status': 'Invalid JSON in hours data', 'next_change': None}
        else:
            # Parse simple text format if needed
            return {'is_open': None, 'status': 'Hours format not supported', 'next_change': None}
        
        day_hours = hours_data.get(current_day, '')
        
        if not day_hours or day_hours.lower() in ['closed', 'fermé', 'cerrado']:
            return {'is_open': False, 'status': 'Closed today', 'next_change': None}
        
        # Parse time ranges (e.g., "09:00-14:00,19:00-23:00" or "09:00-22:00")
        time_ranges = day_hours.split(',')
        
        for time_range in time_ranges:
            if '-' in time_range:
                try:
                    start_str, end_str = time_range.strip().split('-')
                    start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
                    end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
                    
                    # Handle overnight hours (e.g., 22:00-02:00)
                    if start_time <= end_time:
                        if start_time <= current_time <= end_time:
                            return {'is_open': True, 'status': f'Open until {end_str}', 'next_change': None}
                    else:
                        # Overnight service
                        if current_time >= start_time or current_time <= end_time:
                            next_close = end_str if current_time >= start_time else end_str
                            return {'is_open': True, 'status': f'Open until {next_close}', 'next_change': None}
                except ValueError:
                    continue
        
        return {'is_open': False, 'status': 'Currently closed', 'next_change': None}
    
    def get_absolute_url(self):
        return reverse('restaurants:restaurant_detail', kwargs={'slug': self.slug})
    
    @property
    def stars_display(self):
        return '⭐' * self.michelin_stars if self.michelin_stars > 0 else 'No stars'
    
    @property
    def is_michelin_starred(self):
        return self.michelin_stars > 0
    
    @property
    def is_individual_restaurant(self):
        """Check if this is an individual restaurant within a group."""
        return self.parent_group is not None
    
    @property
    def group_restaurants_count(self):
        """Get count of child restaurants if this is a group."""
        if self.is_restaurant_group:
            return self.child_restaurants.count()
        return 0
    
    def get_group_restaurants(self):
        """Get all restaurants in this group."""
        if self.is_restaurant_group:
            return self.child_restaurants.filter(is_active=True).order_by('individual_restaurant_index')
        elif self.parent_group:
            return self.parent_group.child_restaurants.filter(is_active=True).order_by('individual_restaurant_index')
        return Restaurant.objects.none()
    
    @classmethod
    def create_restaurant_group(cls, group_name, source_url, **kwargs):
        """Create a restaurant group."""
        return cls.objects.create(
            name=group_name,
            website=source_url,
            group_source_url=source_url,
            is_restaurant_group=True,
            **kwargs
        )
    
    @classmethod
    def create_individual_restaurant_in_group(cls, parent_group, restaurant_data, index):
        """Create an individual restaurant within a group."""
        return cls.objects.create(
            parent_group=parent_group,
            group_source_url=parent_group.group_source_url,
            individual_restaurant_index=index,
            **restaurant_data
        )
    
    # Error Tracking Methods
    def log_processing_error(self, error_type: str, error_message: str = "", save_to_db: bool = True):
        """
        Log a processing error for this restaurant.
        Integrates with the existing ScrapingJob error tracking system.
        
        Args:
            error_type: Type of error (e.g., 'scraping_failed', 'api_timeout', 'data_validation')
            error_message: Detailed error message
            save_to_db: Whether to save changes to database immediately
        """
        import logging
        from django.utils import timezone
        
        logger = logging.getLogger('restaurants')
        
        self.has_processing_errors = True
        self.error_count = models.F('error_count') + 1
        self.last_error_type = error_type
        self.last_error_at = timezone.now()
        
        if save_to_db:
            # Use update to handle F() expression
            Restaurant.objects.filter(pk=self.pk).update(
                has_processing_errors=True,
                error_count=models.F('error_count') + 1,
                last_error_type=error_type,
                last_error_at=timezone.now()
            )
            self.refresh_from_db(fields=['error_count'])
        
        # Log the error with proper context
        logger.error(
            f"Restaurant processing error - {error_type}: {self.name} (ID: {self.pk}). "
            f"Error count: {self.error_count}. Message: {error_message}"
        )
    
    def clear_processing_errors(self, save_to_db: bool = True):
        """Clear error flags after successful processing."""
        self.has_processing_errors = False
        self.last_error_type = ""
        
        if save_to_db:
            self.save(update_fields=['has_processing_errors', 'last_error_type'])
    
    def update_data_quality_score(self, save_to_db: bool = True):
        """
        Calculate and update data quality score based on completeness.
        Score ranges from 0.00 (no data) to 1.00 (complete data).
        """
        score = 0.0
        total_fields = 10  # Adjust based on important fields
        
        # Core fields (weight: 2 each)
        if self.name: score += 2
        if self.description: score += 2
        if self.country: score += 1
        if self.city: score += 1
        
        # Contact info (weight: 1 each)
        if self.phone: score += 1
        if self.website: score += 1
        if self.address: score += 1
        
        # Location data (weight: 1)
        if self.latitude and self.longitude: score += 1
        
        # Calculate final score
        self.data_quality_score = min(score / total_fields, 1.00)
        
        if save_to_db:
            self.save(update_fields=['data_quality_score'])
    
    @property
    def can_be_featured(self):
        """Determine if restaurant can be featured (good data quality, no recent errors)."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Must have good data quality
        if self.data_quality_score < 0.7:
            return False
            
        # Must not have recent errors
        if self.has_processing_errors and self.last_error_at:
            if self.last_error_at > timezone.now() - timedelta(days=7):
                return False
                
        return True
    
    @classmethod
    def get_high_quality_restaurants(cls):
        """Get restaurants with good data quality and no processing errors."""
        return cls.active.filter(
            has_processing_errors=False,
            data_quality_score__gte=0.8
        )
    
    @classmethod  
    def get_restaurants_with_errors(cls):
        """Get restaurants that need attention due to processing errors."""
        return cls.objects.filter(
            has_processing_errors=True
        ).order_by('-last_error_at')
    
    def _handle_dependent_records(self):
        """
        Handle dependent records when restaurant is deactivated.
        This replaces CASCADE behavior with explicit business logic.
        """
        # Mark all chefs as former employees
        for chef in self.chefs.filter(is_active=True):
            chef.employment_status = EmploymentStatus.FORMER
            chef.employment_ended_date = timezone.now().date()
            chef.deactivate(f"Restaurant {self.name} was deactivated")
        
        # Mark menu sections as archived
        for section in self.menu_sections.filter(is_active=True): 
            section.menu_status = MenuStatus.ARCHIVED
            section.deactivate(f"Restaurant {self.name} was deactivated")
        
        # Handle user carts - mark as restaurant unavailable
        for cart in self.user_carts.filter(cart_status=CartStatus.ACTIVE):
            cart.cart_status = CartStatus.RESTAURANT_UNAVAILABLE
            cart.deactivate(f"Restaurant {self.name} no longer available")
        
        # Handle reviews - mark with restaurant closed status
        for review in self.reviews.filter(is_active=True):
            review.review_status = ReviewStatus.RESTAURANT_CLOSED
            review.deactivate(f"Restaurant {self.name} was closed")
        
        # Handle child restaurants if this is a group
        if self.is_restaurant_group:
            for child in self.child_restaurants.filter(is_active=True):
                child.deactivate(f"Parent group {self.name} was deactivated")
        
        # Create audit event
        EntityEvent.objects.create(
            entity_type='restaurant',
            entity_id=self.id,
            event_type='deactivated',
            event_data={
                'name': self.name,
                'status': self.status,
                'reason': self.deactivation_reason
            },
            created_by_id=self.deactivated_by_id
        )


class Chef(BaseModel):
    """Chef model for restaurant staff."""
    
    # Basic Information  
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    biography = models.TextField(blank=True)
    
    # Professional Information
    position = models.CharField(
        max_length=100,
        choices=[
            ('head_chef', 'Head Chef'),
            ('executive_chef', 'Executive Chef'),
            ('sous_chef', 'Sous Chef'),
            ('pastry_chef', 'Pastry Chef'),
            ('chef_de_partie', 'Chef de Partie'),
        ]
    )
    
    # Experience
    years_experience = models.IntegerField(default=0)
    awards = models.TextField(blank=True)
    
    # Employment status - NO NULL values
    employment_status = models.CharField(
        max_length=50,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE,
        db_index=True
    )
    employment_ended_date = models.DateField(
        default=NEVER_DATE,
        help_text="Date employment ended. Uses date.max for current employees."
    )
    
    # Media
    photo = models.ImageField(upload_to='chefs/', blank=True)
    
    # Relationships - NO CASCADE, NO NULL
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.PROTECT, 
        related_name='chefs',
        default=get_deleted_restaurant_placeholder
    )
    
    class Meta:
        ordering = ['restaurant', 'position', 'last_name']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.get_position_display()}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class MenuSection(BaseModel):
    """Menu section model."""
    
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.PROTECT, 
        related_name='menu_sections',
        default=get_deleted_restaurant_placeholder
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    
    # Menu status - NO NULL values
    menu_status = models.CharField(
        max_length=50,
        choices=MenuStatus.choices,
        default=MenuStatus.CURRENT,
        db_index=True
    )
    
    class Meta:
        ordering = ['restaurant', 'order', 'name']
        unique_together = ['restaurant', 'name']
    
    def __str__(self):
        return f"{self.restaurant.name} - {self.name}"


class MenuItem(BaseModel):
    """Menu item model."""
    
    section = models.ForeignKey(
        MenuSection, 
        on_delete=models.PROTECT, 
        related_name='items',
        default=get_deleted_section  # Will need special handling for deleted sections
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.CharField(max_length=20, blank=True)
    
    # Availability status - replaces is_available_for_cart
    availability_status = models.CharField(
        max_length=50,
        choices=[
            ('available', 'Available'),
            ('sold_out', 'Sold Out'),
            ('seasonal', 'Seasonal'),
            ('discontinued', 'Discontinued')
        ],
        default='available',
        db_index=True
    )
    estimated_prep_time = models.CharField(max_length=50, blank=True, help_text="e.g., '15-20 minutes'")
    
    # Dietary Information
    is_vegetarian = models.BooleanField(default=False)
    is_vegan = models.BooleanField(default=False)
    is_gluten_free = models.BooleanField(default=False)
    allergens = models.TextField(blank=True)
    
    # Availability
    is_available = models.BooleanField(default=True)
    is_signature = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['section', 'name']
    
    def __str__(self):
        return f"{self.section.name} - {self.name}"
    
    @property
    def cleaned_price(self):
        """Extract numeric price from price string for calculations."""
        if self.price:
            # Extract numbers from price string (e.g., "$25" -> 25.00)
            price_numbers = re.findall(r'[\d.,]+', self.price)
            if price_numbers:
                try:
                    return float(price_numbers[0].replace(',', ''))
                except ValueError:
                    pass
        return 0.0
    
    @property
    def dietary_tags(self):
        """Get list of dietary restriction tags."""
        tags = []
        if self.is_vegetarian:
            tags.append('Vegetarian')
        if self.is_vegan:
            tags.append('Vegan')
        if self.is_gluten_free:
            tags.append('Gluten-Free')
        return tags


class UserCart(BaseModel):
    """User's shopping cart for restaurant items."""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        related_name='carts',
        default=get_deleted_user
    )
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.PROTECT, 
        related_name='user_carts',
        default=get_deleted_restaurant_placeholder
    )
    
    # Additional cart status beyond BaseModel's is_active
    cart_status = models.CharField(
        max_length=50,
        choices=CartStatus.choices,
        default=CartStatus.ACTIVE,
        db_index=True,
        help_text="Specific cart state - works alongside is_active from BaseModel"
    )
    notes = models.TextField(blank=True, help_text="Special requests or notes")
    
    class Meta:
        ordering = ['-updated_at']
        unique_together = ['user', 'restaurant', 'is_active']  # One active cart per user per restaurant
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['restaurant', 'is_active']),
            models.Index(fields=['cart_status']),
        ]
    
    def __str__(self):
        return f"{self.user.username}'s cart - {self.restaurant.name}"
    
    @property
    def total_items(self):
        """Get total number of items in cart."""
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0
    
    @property
    def estimated_total(self):
        """Calculate estimated total price."""
        total = 0.0
        for item in self.items.all():
            total += item.subtotal
        return total
    
    def clear_cart(self):
        """Remove all items from cart."""
        self.items.all().delete()
    
    def deactivate(self):
        """Mark cart as inactive (e.g., after checkout)."""
        self.is_active = False
        self.save()
    
    @classmethod
    @transaction.atomic
    def get_or_create_active_cart(cls, user, restaurant):
        """
        Safely get or create an active cart for a user at a restaurant.
        Uses database-level locking to prevent race conditions.
        """
        # First, try to get existing active cart with select_for_update
        try:
            cart = cls.objects.select_for_update().get(
                user=user,
                restaurant=restaurant,
                is_active=True
            )
            return cart, False
        except cls.DoesNotExist:
            pass
        
        # Deactivate any existing active carts for this user+restaurant
        cls.objects.filter(
            user=user,
            restaurant=restaurant,
            is_active=True
        ).update(is_active=False)
        
        # Create new active cart
        cart = cls.objects.create(
            user=user,
            restaurant=restaurant,
            is_active=True
        )
        return cart, True


class CartItem(BaseModel):
    """Individual item in a user's cart."""
    
    cart = models.ForeignKey(
        UserCart, 
        on_delete=models.PROTECT, 
        related_name='items',
        default=get_deleted_cart
    )
    menu_item = models.ForeignKey(
        MenuItem, 
        on_delete=models.PROTECT, 
        related_name='cart_items',
        default=get_discontinued_item
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    special_requests = models.TextField(blank=True, help_text="Customizations or special requests")
    
    # Item status when added to cart - preserve data if item changes
    item_status = models.CharField(
        max_length=50,
        choices=CartItemStatus.choices,
        default=CartItemStatus.VALID,
        db_index=True
    )
    
    # Snapshot data - preserve item details at time of adding to cart
    item_name_snapshot = models.CharField(max_length=200)
    item_price_snapshot = models.CharField(max_length=20, blank=True)
    
    # Metadata beyond BaseModel
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['added_at']
        unique_together = ['cart', 'menu_item']  # One entry per menu item per cart
    
    def __str__(self):
        return f"{self.quantity}x {self.menu_item.name}"
    
    @property
    def subtotal(self):
        """Calculate subtotal for this cart item."""
        return self.menu_item.cleaned_price * self.quantity
    
    def increase_quantity(self, amount=1):
        """Increase quantity by specified amount."""
        self.quantity += amount
        self.save()
    
    def decrease_quantity(self, amount=1):
        """Decrease quantity by specified amount."""
        if self.quantity > amount:
            self.quantity -= amount
            self.save()
        else:
            self.delete()  # Remove item if quantity would be 0 or negative
    
    @classmethod
    @transaction.atomic
    def add_or_update_item(cls, cart, menu_item, quantity=1, special_requests=""):
        """
        Safely add or update a cart item. Handles race conditions.
        """
        try:
            # Try to get existing item with lock
            cart_item = cls.objects.select_for_update().get(
                cart=cart,
                menu_item=menu_item
            )
            # Update existing item
            cart_item.quantity += quantity
            cart_item.special_requests = special_requests
            cart_item.save()
            return cart_item, False
        except cls.DoesNotExist:
            # Create new item
            cart_item = cls.objects.create(
                cart=cart,
                menu_item=menu_item,
                quantity=quantity,
                special_requests=special_requests
            )
            return cart_item, True


class ChatCartInteraction(BaseModel):
    """Track LLM chatbot interactions with cart functionality."""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        related_name='chat_cart_interactions',
        default=get_deleted_user
    )
    cart = models.ForeignKey(
        UserCart, 
        on_delete=models.PROTECT, 
        related_name='chat_interactions',
        default=get_deleted_cart
    )
    
    # Interaction data
    user_message = models.TextField(help_text="User's message to the chatbot")
    bot_response = models.TextField(help_text="Chatbot's response")
    action_taken = models.CharField(
        max_length=50,
        choices=[
            ('add_item', 'Added Item to Cart'),
            ('remove_item', 'Removed Item from Cart'),
            ('modify_quantity', 'Modified Item Quantity'),
            ('show_menu', 'Showed Menu Items'),
            ('show_cart', 'Showed Cart Contents'),
            ('clear_cart', 'Cleared Cart'),
            ('provide_info', 'Provided Information'),
            ('no_action', 'No Action Taken'),
        ],
        default='no_action'
    )
    
    # Items affected by this interaction
    items_affected = models.JSONField(default=list, help_text="List of menu item IDs affected by this interaction")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    session_id = models.CharField(max_length=100, blank=True, help_text="Chat session identifier")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['session_id']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.action_taken} at {self.created_at}"


class RestaurantImage(models.Model):
    """Enhanced restaurant image model with AI-powered categorization and labeling."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name='images')
    
    # Image Storage
    image = models.ImageField(upload_to='restaurants/', blank=True)
    source_url = models.URLField(blank=True, help_text="Original URL where the image was scraped from")
    
    # Manual metadata
    caption = models.CharField(max_length=200, blank=True)
    alt_text = models.CharField(max_length=255, blank=True)
    
    # AI-Powered Categorization
    ai_category = models.CharField(
        max_length=50,
        choices=[
            ('food', 'Food/Dish'),
            ('interior', 'Interior'),
            ('exterior', 'Exterior'),
            ('chef', 'Chef'),
            ('staff', 'Staff'),
            ('ambiance', 'Ambiance'),
            ('presentation', 'Presentation'),
            ('ingredients', 'Ingredients'),
            ('bar', 'Bar/Drinks'),
            ('menu_item', 'Menu Item'),           # Legacy category
            ('scenery_ambiance', 'Scenery/Ambiance/Dining'),  # Legacy category
            ('uncategorized', 'Uncategorized'),
        ],
        default='uncategorized',
        help_text="AI-determined primary category"
    )
    
    # AI-Generated Labels and Descriptions
    ai_labels = models.JSONField(
        default=list, 
        blank=True,
        help_text="AI-generated descriptive labels (e.g., ['mountain views', 'outdoor terrace', 'romantic lighting'])"
    )
    ai_description = models.TextField(
        blank=True,
        help_text="AI-generated detailed description of what's in the image"
    )
    
    # Confidence Scores (0.0 to 1.0)
    category_confidence = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="AI confidence score for category classification"
    )
    description_confidence = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="AI confidence score for description accuracy"
    )
    
    # Legacy Image Types (keeping for backwards compatibility)
    image_type = models.CharField(
        max_length=50,
        choices=[
            ('exterior', 'Exterior'),
            ('interior', 'Interior'),
            ('food', 'Food'),
            ('chef', 'Chef'),
            ('staff', 'Staff'),
            ('event', 'Event'),
            ('scenery', 'Scenery'),
            ('dining_room', 'Dining Room'),
            ('ambiance', 'Ambiance'),
        ],
        default='interior'
    )
    
    # Processing Status
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending'
    )
    processing_error = models.TextField(blank=True)
    
    # Image Fingerprinting and Deduplication
    content_hash = models.CharField(
        max_length=64, 
        null=True, 
        blank=True, 
        db_index=True,
        help_text="SHA256 hash of image content for exact duplicate detection"
    )
    perceptual_hash = models.CharField(
        max_length=16, 
        null=True, 
        blank=True, 
        db_index=True,
        help_text="Perceptual hash for similar image detection"
    )
    source_url_hash = models.CharField(
        max_length=64, 
        null=True, 
        blank=True, 
        db_index=True,
        help_text="Hash of source URL to prevent re-downloading same images"
    )
    ai_processed = models.BooleanField(
        default=False,
        help_text="Whether AI classification has been completed for this image"
    )
    
    # Image Quality and Metadata
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True, help_text="File size in bytes")
    
    # Order and display
    order = models.IntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_menu_highlight = models.BooleanField(default=False, help_text="Is this a standout menu item image?")
    is_ambiance_highlight = models.BooleanField(default=False, help_text="Is this a standout ambiance/scenery image?")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['restaurant', 'order', '-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'ai_category']),
            models.Index(fields=['processing_status']),
            models.Index(fields=['is_featured', 'is_menu_highlight', 'is_ambiance_highlight']),
            models.Index(fields=['content_hash']),
            models.Index(fields=['perceptual_hash']),
            models.Index(fields=['restaurant', 'ai_processed']),
            models.Index(fields=['source_url_hash']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['content_hash'], 
                name='unique_content_hash',
                condition=models.Q(content_hash__isnull=False)
            ),
        ]
    
    def __str__(self):
        if self.ai_category and self.ai_category != 'uncategorized':
            return f"{self.restaurant.name} - {self.get_ai_category_display()}"
        return f"{self.restaurant.name} - {self.get_image_type_display()}"
    
    @property
    def get_image_url(self):
        """
        Smart URL getter that prioritizes S3 URL over other sources.
        
        Priority order:
        1. S3 URL (primary cloud storage)
        2. Source URL (original scraped URL)
        3. Local image file URL (Django ImageField)
        
        Returns:
            str: The best available image URL or None
        """
        # Priority 1: S3 URL (if available)
        if hasattr(self, 's3_url') and self.s3_url:
            return self.s3_url
        
        # Priority 2: Source URL (original scraped URL)
        if self.source_url:
            return self.source_url
            
        # Priority 3: Local Django ImageField URL
        if self.image:
            try:
                return self.image.url
            except (ValueError, AttributeError):
                # Handle cases where image file is missing
                pass
        
        # No image URL available
        return None
    
    @property
    def is_s3_stored(self):
        """Check if this image is stored in S3."""
        return hasattr(self, 's3_url') and bool(self.s3_url)
    
    def migrate_to_s3(self):
        """
        Migrate this image to S3 storage.
        
        Returns:
            dict: Migration result with status and S3 URL
        """
        try:
            from services.s3_service import get_s3_service
            
            # Skip if already in S3
            if self.is_s3_stored:
                return {
                    'status': 'already_migrated',
                    's3_url': self.s3_url,
                    'message': 'Image already stored in S3'
                }
            
            s3_service = get_s3_service()
            
            # Determine source for migration
            if self.image:
                # Upload from local file
                result = s3_service.upload_from_local(
                    local_path=self.image.path,
                    content_type='restaurant_images',
                    identifier=self.restaurant.name
                )
            elif self.source_url:
                # Upload from source URL
                result = s3_service.upload_from_url(
                    image_url=self.source_url,
                    content_type='restaurant_images',
                    identifier=self.restaurant.name
                )
            else:
                return {
                    'status': 'failed',
                    'message': 'No source available for migration'
                }
            
            if result:
                # Update model with S3 information
                self.s3_url = result['s3_url']
                self.s3_key = result['s3_key']
                if not self.content_hash:
                    self.content_hash = result['content_hash']
                self.save()
                
                return {
                    'status': 'migrated',
                    's3_url': self.s3_url,
                    's3_key': self.s3_key,
                    'message': 'Successfully migrated to S3'
                }
            else:
                return {
                    'status': 'failed',
                    'message': 'S3 upload failed'
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Migration error: {str(e)}'
            }
    
    @property
    def is_scenery_ambiance(self):
        """Check if this image is categorized as scenery/ambiance."""
        return self.ai_category == 'scenery_ambiance'
    
    @property
    def is_menu_item(self):
        """Check if this image is categorized as a menu item."""
        return self.ai_category == 'menu_item'
    
    @property
    def primary_labels(self):
        """Get the first 3 AI labels as primary descriptors."""
        return self.ai_labels[:3] if self.ai_labels else []
    
    @property
    def is_high_confidence(self):
        """Check if the AI categorization has high confidence (>0.8)."""
        return self.category_confidence > 0.8
    
    def get_display_name(self):
        """Get a human-readable display name for the image."""
        if self.ai_labels:
            return ", ".join(self.primary_labels).title()
        elif self.caption:
            return self.caption
        else:
            return self.get_ai_category_display() or self.get_image_type_display()
    
    def calculate_content_hash(self):
        """Calculate SHA256 hash of image content for exact duplicate detection."""
        if not self.image:
            return None
        
        self.image.seek(0)
        content = self.image.read()
        self.image.seek(0)  # Reset file pointer
        return hashlib.sha256(content).hexdigest()
    
    def calculate_perceptual_hash(self):
        """Calculate perceptual hash for similar image detection."""
        if not self.image:
            return None
        
        try:
            import imagehash
            from PIL import Image
            
            self.image.seek(0)
            pil_image = Image.open(self.image)
            p_hash = str(imagehash.phash(pil_image))
            self.image.seek(0)  # Reset file pointer
            return p_hash
        except ImportError:
            # Fallback if imagehash not available
            return None
    
    def calculate_source_url_hash(self):
        """Calculate hash of source URL to prevent re-downloading."""
        if not self.source_url:
            return None
        
        return hashlib.sha256(self.source_url.encode('utf-8')).hexdigest()
    
    @classmethod
    def check_duplicate_by_content(cls, image_file):
        """Check if an image with the same content already exists."""
        image_file.seek(0)
        content_hash = hashlib.sha256(image_file.read()).hexdigest()
        image_file.seek(0)
        
        return cls.objects.filter(content_hash=content_hash).first()
    
    @classmethod
    def check_duplicate_by_url(cls, source_url):
        """Check if an image from the same URL already exists."""
        url_hash = hashlib.sha256(source_url.encode('utf-8')).hexdigest()
        return cls.objects.filter(source_url_hash=url_hash).first()
    
    def save(self, *args, **kwargs):
        """Override save to automatically calculate hashes."""
        # Calculate hashes if image is present and hashes are not set
        if self.image and not self.content_hash:
            self.content_hash = self.calculate_content_hash()
        
        if self.image and not self.perceptual_hash:
            self.perceptual_hash = self.calculate_perceptual_hash()
        
        if self.source_url and not self.source_url_hash:
            self.source_url_hash = self.calculate_source_url_hash()
        
        super().save(*args, **kwargs)


class RestaurantReview(BaseModel):
    """Restaurant review model."""
    
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.PROTECT, 
        related_name='reviews',
        default=get_deleted_restaurant_placeholder
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT,
        default=get_deleted_user
    )
    
    # Review status - preserve reviews even if restaurant/user deleted
    review_status = models.CharField(
        max_length=50,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PUBLISHED,
        db_index=True
    )
    
    # Review Content
    title = models.CharField(max_length=200)
    content = models.TextField()
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    # Review Details - NO NULL values
    visit_date = models.DateField(default=NEVER_DATE, help_text="Date of visit. Uses date.max if not specified.")
    
    # Moderation
    is_approved = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['restaurant', 'user']
    
    def __str__(self):
        return f"{self.restaurant.name} - {self.user.username} ({self.rating}/5)"


class ScrapingJob(models.Model):
    """Model to track scraping jobs."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Job Information
    job_name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
    )
    
    # Progress Tracking
    total_urls = models.IntegerField(default=0)
    processed_urls = models.IntegerField(default=0)
    successful_urls = models.IntegerField(default=0)
    failed_urls = models.IntegerField(default=0)
    
    # Results
    results = models.JSONField(default=dict, blank=True)
    error_log = models.TextField(blank=True)
    
    # Metadata
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.job_name} - {self.status}"
    
    @property
    def progress_percentage(self):
        if self.total_urls == 0:
            return 0
        return (self.processed_urls / self.total_urls) * 100
    
    @property
    def success_rate(self):
        if self.processed_urls == 0:
            return 0
        return (self.successful_urls / self.processed_urls) * 100


class ImageScrapingJob(BaseModel):
    """Model to track image scraping jobs."""
    
    # Job Information
    job_name = models.CharField(max_length=200)
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.PROTECT, 
        default=get_deleted_restaurant_placeholder
    )
    source_urls = models.JSONField(default=list, help_text="List of URLs to scrape images from")
    
    # Job Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
    )
    
    # Progress Tracking
    total_images_found = models.IntegerField(default=0)
    images_processed = models.IntegerField(default=0)
    images_downloaded = models.IntegerField(default=0)
    images_categorized = models.IntegerField(default=0)
    images_failed = models.IntegerField(default=0)
    
    # Configuration
    max_images_per_url = models.IntegerField(default=20, help_text="Maximum images to scrape per URL")
    min_image_size = models.IntegerField(default=200, help_text="Minimum image size in pixels")
    enable_ai_categorization = models.BooleanField(default=True)
    
    # Results and Errors
    results = models.JSONField(default=dict, blank=True)
    error_log = models.TextField(blank=True)
    
    # Metadata
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='image_scraping_jobs'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        if self.restaurant:
            return f"Image scraping: {self.restaurant.name} - {self.status}"
        return f"{self.job_name} - {self.status}"
    
    @property
    def progress_percentage(self):
        if self.total_images_found == 0:
            return 0
        return (self.images_processed / self.total_images_found) * 100
    
    @property
    def success_rate(self):
        if self.images_processed == 0:
            return 0
        return (self.images_downloaded / self.images_processed) * 100
    
    @property
    def categorization_rate(self):
        if self.images_downloaded == 0:
            return 0
        return (self.images_categorized / self.images_downloaded) * 100


class RestaurantRecommendation(models.Model):
    """
    System-generated TOP restaurant recommendations for homepage and featured sections.
    This is different from user-specific personalized recommendations.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.OneToOneField(
        Restaurant,
        on_delete=models.CASCADE,
        related_name='recommendation_data'
    )
    
    # Recommendation metrics
    recommendation_score = models.FloatField(default=0.0, help_text='Combined recommendation score (0.0-1.0)')
    click_through_rate = models.FloatField(default=0.0, help_text='Percentage of users who clicked')
    user_rating_average = models.FloatField(default=0.0, help_text='Average user rating')
    total_favorites_count = models.IntegerField(default=0, help_text='Total favorites count')
    total_views_count = models.IntegerField(default=0, help_text='Total view count')
    michelin_boost = models.FloatField(default=0.0, help_text='Boost for Michelin stars')
    
    # Algorithm metadata
    algorithm_version = models.CharField(max_length=20, default='v1.0')
    last_calculated = models.DateTimeField(auto_now=True)
    
    # Regional data for location-based recommendations
    city = models.CharField(max_length=100, blank=True, db_index=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    
    # Display configuration
    is_featured_homepage = models.BooleanField(default=False, db_index=True, help_text='Show on homepage')
    homepage_order = models.IntegerField(default=999, help_text='Display order (lower = higher)')
    is_regional_featured = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-recommendation_score', 'homepage_order']
        indexes = [
            models.Index(fields=['is_featured_homepage', '-recommendation_score'], name='featured_homepage_idx'),
            models.Index(fields=['country', 'city', '-recommendation_score'], name='regional_recommendations_idx'),
            models.Index(fields=['algorithm_version', 'last_calculated'], name='algorithm_version_idx'),
        ]
    
    def __str__(self):
        return f"{self.restaurant.name} - Score: {self.recommendation_score:.2f}"
    
    def calculate_score(self):
        """
        Calculate combined recommendation score using weighted algorithm.
        This is the main algorithm for determining top restaurants.
        """
        # Normalize metrics
        rating_normalized = (self.user_rating_average / 5.0) if self.user_rating_average else 0
        ctr_normalized = min(self.click_through_rate, 1.0)  # Cap at 100%
        favorites_normalized = min(self.total_favorites_count / 1000, 1.0)  # Normalize to 1000 favorites
        views_normalized = min(self.total_views_count / 10000, 1.0)  # Normalize to 10000 views
        
        # Calculate weighted score
        self.recommendation_score = (
            rating_normalized * 0.4 +           # 40% weight on ratings
            ctr_normalized * 0.3 +              # 30% weight on click-through rate
            favorites_normalized * 0.2 +        # 20% weight on favorites
            views_normalized * 0.05 +           # 5% weight on views
            self.michelin_boost * 0.05          # 5% weight on Michelin stars
        )
        
        # Ensure score is between 0 and 1
        self.recommendation_score = max(0.0, min(1.0, self.recommendation_score))
        
        return self.recommendation_score
    
    @classmethod
    def update_top_recommendations(cls, limit=20):
        """
        Class method to update the top recommendations for the homepage.
        Should be run periodically (e.g., daily) via Celery task.
        """
        from django.db.models import Count, Avg
        from accounts.models import UserFavoriteRestaurant
        
        # Calculate metrics for all restaurants
        restaurants = Restaurant.objects.filter(
            is_active=True
        ).annotate(
            avg_rating=Avg('reviews__rating'),
            favorites_count=Count('user_favorites'),
            views_count=Count('user_interactions')
        )
        
        for restaurant in restaurants:
            recommendation, created = cls.objects.get_or_create(
                restaurant=restaurant,
                defaults={
                    'city': restaurant.city,
                    'state': '',  # We don't have state in Restaurant model
                    'country': restaurant.country,
                }
            )
            
            # Update metrics
            recommendation.user_rating_average = restaurant.avg_rating or 0
            recommendation.total_favorites_count = restaurant.favorites_count
            recommendation.total_views_count = restaurant.views_count
            recommendation.michelin_boost = restaurant.michelin_stars * 0.1
            
            # Calculate CTR from interactions
            interactions = restaurant.user_interactions.all()
            if interactions.exists():
                clicks = interactions.filter(interaction_type='clicked').count()
                impressions = interactions.filter(interaction_type='impression').count()
                if impressions > 0:
                    recommendation.click_through_rate = clicks / impressions
            
            # Calculate and save score
            recommendation.calculate_score()
            recommendation.save()
        
        # Update homepage featured flags
        cls.objects.update(is_featured_homepage=False)
        top_recommendations = cls.objects.order_by('-recommendation_score')[:limit]
        for idx, rec in enumerate(top_recommendations):
            rec.is_featured_homepage = True
            rec.homepage_order = idx
            rec.save()


class UserRecommendationInteraction(models.Model):
    """
    Track user interactions with restaurant recommendations for algorithm improvement.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recommendation_interactions'
    )
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name='user_interactions'
    )
    
    interaction_type = models.CharField(
        max_length=20,
        choices=[
            ('impression', 'Shown to User'),
            ('viewed', 'Viewed Details'),
            ('clicked', 'Clicked Through'),
            ('favorited', 'Added to Favorites'),
            ('visited', 'Visited Restaurant'),
            ('dismissed', 'Dismissed/Hidden'),
        ],
        db_index=True
    )
    
    interaction_context = models.CharField(
        max_length=50,
        choices=[
            ('homepage_featured', 'Homepage Featured Section'),
            ('homepage_sidebar', 'Homepage Sidebar'),
            ('search_results', 'Search Results'),
            ('recommendation_api', 'Recommendation API'),
            ('email_campaign', 'Email Campaign'),
            ('personalized_page', 'Personalized Recommendations Page'),
        ],
        default='homepage_featured'
    )
    
    session_id = models.CharField(max_length=100, blank=True)
    recommendation_score_at_time = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'interaction_type', '-created_at'], name='user_interaction_idx'),
            models.Index(fields=['restaurant', 'interaction_type'], name='restaurant_interaction_idx'),
            models.Index(fields=['session_id', 'created_at'], name='session_tracking_idx'),
            models.Index(fields=['interaction_context', 'created_at'], name='context_tracking_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'restaurant', 'interaction_type', 'session_id'],
                name='unique_user_restaurant_interaction_per_session'
            ),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.interaction_type} - {self.restaurant.name}"


class ScrapingBacklogTask(BaseModel):
    """PostgreSQL-based scraping backlog task model for async processing."""
    
    TASK_TYPE_CHOICES = [
        ('text', 'Text Scraping'),
        ('images', 'Image Scraping'),
        ('comprehensive', 'Comprehensive Scraping'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    task_id = models.CharField(max_length=255, unique=True, db_index=True)
    url = models.URLField()
    restaurant_name = models.CharField(max_length=255)
    task_type = models.CharField(max_length=20, choices=TASK_TYPE_CHOICES, db_index=True)
    
    # Priority and retry logic
    priority = models.PositiveIntegerField(default=1, db_index=True)
    max_retries = models.PositiveIntegerField(default=3)
    retry_count = models.PositiveIntegerField(default=0)
    
    # Status and tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    error_messages = models.JSONField(default=list, blank=True)
    
    # Timestamps - NO NULL values (BaseModel provides created_at/updated_at)
    last_attempt = models.DateTimeField(default=timezone.make_aware(dt.datetime.min))
    completed_at = models.DateTimeField(default=timezone.make_aware(dt.datetime.min))
    
    # Restaurant association - NO CASCADE, NO NULL
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.PROTECT,
        related_name='backlog_tasks',
        default=get_deleted_restaurant_placeholder
    )
    
    class Meta:
        ordering = ['-priority', 'created_at']
        indexes = [
            models.Index(fields=['status', 'priority', 'created_at']),
            models.Index(fields=['task_type', 'status']),
            models.Index(fields=['retry_count', 'max_retries', 'status']),
        ]
    
    def __str__(self):
        return f"{self.task_type} - {self.restaurant_name} ({self.status})"
    
    @property
    def can_retry(self):
        """Check if task can be retried."""
        return self.retry_count < self.max_retries and self.status != 'completed'
    
    def mark_failed(self, error_message: str):
        """Mark task as failed and increment retry count."""
        from django.utils import timezone
        
        self.retry_count += 1
        self.error_messages.append(f"{timezone.now().isoformat()}: {error_message}")
        self.last_attempt = timezone.now()
        
        if self.retry_count >= self.max_retries:
            self.status = 'failed'
        else:
            self.status = 'pending'  # Allow retry
        
        self.save()
    
    def mark_completed(self):
        """Mark task as completed."""
        from django.utils import timezone
        
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()