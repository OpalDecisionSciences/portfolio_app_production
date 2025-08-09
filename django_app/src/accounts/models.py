from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import EmailValidator
from django.utils import timezone
from datetime import datetime
import uuid

# Import zero-CASCADE, zero-NULL architecture components
from restaurants.base_models import (
    BaseModel, get_system_user, get_deleted_restaurant_placeholder,
    get_deleted_user, DELETED_USER_ID, DELETED_RESTAURANT_ID
)


class User(AbstractUser):
    """
    Custom User model extending Django's AbstractUser.
    Includes profile information and dining preferences.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(
        unique=True,
        validators=[EmailValidator()],
        help_text="Email address for account notifications and password reset"
    )
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    
    # Profile Information
    phone_number = models.CharField(max_length=20, blank=True)
    birth_month = models.IntegerField(
        null=True, 
        blank=True,
        choices=[
            (1, 'January'), (2, 'February'), (3, 'March'),
            (4, 'April'), (5, 'May'), (6, 'June'),
            (7, 'July'), (8, 'August'), (9, 'September'),
            (10, 'October'), (11, 'November'), (12, 'December')
        ],
        help_text="Birth month for birthday greetings"
    )
    
    # Location fields (structured)
    city = models.CharField(max_length=100, blank=True, help_text="City of residence")
    state = models.CharField(max_length=100, blank=True, help_text="State/Province of residence")
    country = models.CharField(max_length=100, blank=True, help_text="Country of residence")
    
    # Dining Preferences
    preferred_cuisines = models.JSONField(
        default=list,
        blank=True,
        help_text="User's preferred cuisine types"
    )
    dietary_restrictions = models.JSONField(
        default=list,
        blank=True,
        help_text="Dietary restrictions and preferences"
    )
    price_range_preference = models.CharField(
        max_length=20,
        choices=[
            ('budget', 'Budget-friendly ($)'),
            ('moderate', 'Moderate ($$)'),
            ('upscale', 'Upscale ($$$)'),
            ('luxury', 'Luxury ($$$$)'),
            ('any', 'Any price range')
        ],
        default='any',
        blank=True
    )
    
    # Account Settings
    email_verified = models.BooleanField(default=False)
    newsletter_subscription = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    
    # Metadata
    profile_completed = models.BooleanField(default=False)
    last_active = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']
    
    class Meta:
        db_table = 'accounts_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.email})"
    
    def get_full_name(self):
        """Return the first_name plus the last_name, with a space in between."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.username
    
    def get_short_name(self):
        """Return the short name for the user."""
        return self.first_name or self.username
    
    @property
    def has_complete_profile(self):
        """Check if user has completed their profile."""
        return bool(
            self.first_name and 
            self.last_name and 
            self.city and
            self.country and
            self.preferred_cuisines
        )
    
    @property
    def location_display(self):
        """Get formatted location string for display."""
        parts = []
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.country:
            parts.append(self.country)
        return ', '.join(parts) if parts else 'Location not set'


class UserFavoriteRestaurant(BaseModel):
    """
    User's favorite restaurants with notes and categories.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        related_name='favorite_restaurants',
        default=get_deleted_user
    )
    restaurant = models.ForeignKey(
        'restaurants.Restaurant', 
        on_delete=models.PROTECT,
        related_name='user_favorites',
        default=get_deleted_restaurant_placeholder
    )
    
    # Favorite details
    category = models.CharField(
        max_length=50,
        choices=[
            ('to_visit', 'Want to Visit'),
            ('visited', 'Visited & Loved'),
            ('special_occasion', 'Special Occasions'),
            ('business_dining', 'Business Dining'),
            ('romantic', 'Romantic Dinners'),
            ('family', 'Family-Friendly'),
            ('quick_bite', 'Quick Bites'),
        ],
        default='to_visit'
    )
    
    personal_rating = models.IntegerField(
        null=True, 
        blank=True,
        choices=[(i, f"{i} Stars") for i in range(1, 6)],
        help_text="Personal rating (1-5 stars)"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Personal notes about this restaurant"
    )
    
    visit_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date of visit (if visited)"
    )
    
    recommended_dishes = models.JSONField(
        default=list,
        blank=True,
        help_text="List of recommended dishes"
    )
    
    # Metadata
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'restaurant']
        ordering = ['-added_at']
        verbose_name = 'Favorite Restaurant'
        verbose_name_plural = 'Favorite Restaurants'
    
    def __str__(self):
        return f"{self.user.get_short_name()}'s favorite: {self.restaurant.name}"


class UserChatHistory(BaseModel):
    """
    Store user's chat conversation history for better recommendations.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        related_name='chat_history',
        default=get_deleted_user
    )
    
    # Chat session info
    conversation_id = models.CharField(max_length=100, db_index=True)
    session_start = models.DateTimeField(auto_now_add=True)
    session_end = models.DateTimeField(null=True, blank=True)
    
    # Conversation summary
    topics_discussed = models.JSONField(
        default=list,
        help_text="Main topics discussed in this conversation"
    )
    restaurants_mentioned = models.ManyToManyField(
        'restaurants.Restaurant',
        blank=True,
        help_text="Restaurants discussed in this conversation"
    )
    
    # Preferences learned
    preferences_learned = models.JSONField(
        default=dict,
        help_text="User preferences discovered during conversation"
    )
    
    message_count = models.IntegerField(default=0)
    satisfaction_rating = models.IntegerField(
        null=True,
        blank=True,
        choices=[(i, f"{i} Stars") for i in range(1, 6)],
        help_text="User's satisfaction with the conversation"
    )
    
    class Meta:
        ordering = ['-session_start']
        verbose_name = 'Chat History'
        verbose_name_plural = 'Chat Histories'
    
    def __str__(self):
        return f"{self.user.get_short_name()}'s chat on {self.session_start.date()}"


class PasswordResetToken(BaseModel):
    """
    Custom password reset tokens with enhanced security.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.PROTECT,
        default=get_deleted_user
    )
    token = models.CharField(max_length=100, unique=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(default='127.0.0.1')
    
    class Meta:
        ordering = ['-created_at']
    
    def is_valid(self):
        """Check if token is still valid."""
        return not self.used and timezone.now() < self.expires_at
    
    def __str__(self):
        return f"Password reset for {self.user.email}"