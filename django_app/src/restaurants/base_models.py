"""
Base models and utilities for zero-CASCADE, zero-NULL architecture.
"""
import uuid
from datetime import datetime, date
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError


# System constants - No NULL values, use these as defaults
SYSTEM_USER_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')
DELETED_RESTAURANT_ID = uuid.UUID('00000000-0000-0000-0000-000000000002')
DISCONTINUED_ITEM_ID = uuid.UUID('00000000-0000-0000-0000-000000000003')
DELETED_USER_ID = uuid.UUID('00000000-0000-0000-0000-000000000004')
DELETED_CART_ID = uuid.UUID('00000000-0000-0000-0000-000000000005')
DELETED_SECTION_ID = uuid.UUID('00000000-0000-0000-0000-000000000006')

# Date constants for non-NULL date fields
NEVER_DATE = date.max  # 9999-12-31
UNKNOWN_DATE = date.min  # 0001-01-01


def get_system_user():
    """Return system user ID for default foreign key references."""
    return SYSTEM_USER_ID


def get_deleted_restaurant_placeholder():
    """Return placeholder restaurant ID for orphaned records."""
    return DELETED_RESTAURANT_ID


def get_deleted_user():
    """Return deleted user ID for orphaned user references."""
    return DELETED_USER_ID


def get_deleted_cart():
    """Return deleted cart ID for orphaned cart references."""
    return DELETED_CART_ID


def get_discontinued_item():
    """Return discontinued item ID for orphaned menu item references."""
    return DISCONTINUED_ITEM_ID


def get_deleted_section():
    """Return deleted section ID for orphaned menu section references."""
    return DELETED_SECTION_ID


class EntityStatus(models.TextChoices):
    """Universal status choices for all entities."""
    ACTIVE = 'active', 'Active'
    INACTIVE = 'inactive', 'Inactive'
    ARCHIVED = 'archived', 'Archived'
    SUSPENDED = 'suspended', 'Suspended'
    MERGED = 'merged', 'Merged with Another Entity'
    TRANSFERRED = 'transferred', 'Transferred'
    DISCONTINUED = 'discontinued', 'Discontinued'


class EmploymentStatus(models.TextChoices):
    """Employment status for chef records."""
    ACTIVE = 'active', 'Active'
    FORMER = 'former', 'Former Employee'
    TRANSFERRED = 'transferred', 'Transferred to Another Restaurant'
    SUSPENDED = 'suspended', 'Suspended'


class MenuStatus(models.TextChoices):
    """Menu and menu item status choices."""
    CURRENT = 'current', 'Current Menu'
    SEASONAL_INACTIVE = 'seasonal_inactive', 'Seasonal - Inactive'
    DISCONTINUED = 'discontinued', 'Discontinued'
    ARCHIVED = 'archived', 'Archived'
    SOLD_OUT = 'sold_out', 'Sold Out'
    AVAILABLE = 'available', 'Available'


class CartStatus(models.TextChoices):
    """Shopping cart status choices."""
    ACTIVE = 'active', 'Active'
    ABANDONED = 'abandoned', 'Abandoned'
    CONVERTED = 'converted', 'Converted to Order'
    RESTAURANT_UNAVAILABLE = 'restaurant_unavailable', 'Restaurant No Longer Available'
    USER_DEACTIVATED = 'user_deactivated', 'User Account Deactivated'


class CartItemStatus(models.TextChoices):
    """Shopping cart item status choices."""
    VALID = 'valid', 'Valid'
    ITEM_DISCONTINUED = 'item_discontinued', 'Item Discontinued'
    PRICE_CHANGED = 'price_changed', 'Price Changed'  
    RESTAURANT_CLOSED = 'restaurant_closed', 'Restaurant Closed'


class ReviewStatus(models.TextChoices):
    """Review status choices."""
    PUBLISHED = 'published', 'Published'
    ACTIVE = 'active', 'Active'
    HIDDEN = 'hidden', 'Hidden'
    FLAGGED = 'flagged', 'Flagged for Review'
    ARCHIVED = 'archived', 'Archived'
    USER_DEACTIVATED = 'user_deactivated', 'User Account Deactivated'
    RESTAURANT_CLOSED = 'restaurant_closed', 'Restaurant Closed'


class ActiveObjectsManager(models.Manager):
    """Manager that returns only active records."""
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class AllObjectsManager(models.Manager):
    """Manager that returns all records including inactive."""
    def get_queryset(self):
        return super().get_queryset()


class BaseModel(models.Model):
    """
    Base model with soft delete pattern and no NULL foreign keys.
    All models should inherit from this to ensure consistent behavior.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Soft delete fields - NO NULLs
    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(
        default=timezone.make_aware(datetime.min),
        help_text="When this record was deactivated. Uses datetime.min for never deactivated."
    )
    deactivation_reason = models.CharField(
        max_length=200, 
        default='', 
        blank=True,
        help_text="Reason for deactivation"
    )
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='%(class)s_deactivations',
        default=get_system_user,
        help_text="User who deactivated this record"
    )
    
    # Managers
    objects = AllObjectsManager()  # Default manager (all records)
    active = ActiveObjectsManager()  # Only active records
    
    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['is_active', 'created_at']),
            models.Index(fields=['deactivated_at']),
        ]
    
    def deactivate(self, reason="Manual deactivation", deactivated_by=None):
        """
        Soft delete this record with full audit trail.
        No CASCADE - dependent records must be handled explicitly.
        """
        if not self.is_active:
            return  # Already deactivated
            
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.deactivation_reason = reason
        self.deactivated_by_id = deactivated_by.id if deactivated_by else SYSTEM_USER_ID
        self.save()
        
        # Call model-specific cleanup
        self._handle_dependent_records()
    
    def reactivate(self, reactivated_by=None):
        """Reactivate this record."""
        self.is_active = True
        self.deactivated_at = timezone.make_aware(datetime.min)
        self.deactivation_reason = ''
        self.deactivated_by_id = SYSTEM_USER_ID
        self.save()
    
    def _handle_dependent_records(self):
        """
        Override in child models to handle dependent records.
        This replaces CASCADE behavior with explicit business logic.
        """
        pass
    
    @property
    def was_never_deactivated(self):
        """Check if this record was never deactivated."""
        return self.deactivated_at == timezone.make_aware(datetime.min)


class EntityEvent(models.Model):
    """
    Event sourcing for all entity changes.
    Provides complete audit trail without relying on CASCADE.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.UUIDField(db_index=True)
    event_type = models.CharField(
        max_length=50,
        choices=[
            ('created', 'Created'),
            ('updated', 'Updated'), 
            ('deactivated', 'Deactivated'),
            ('reactivated', 'Reactivated'),
            ('merged', 'Merged'),
            ('transferred', 'Transferred'),
            ('status_changed', 'Status Changed'),
        ],
        db_index=True
    )
    event_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        default=get_system_user
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['event_type', 'created_at']),
        ]
        # This table is append-only - no delete permissions
        default_permissions = ('add', 'view')
    
    def __str__(self):
        return f"{self.entity_type} {self.entity_id} - {self.event_type}"


class SystemPlaceholder(models.Model):
    """
    System placeholder records to avoid NULL foreign keys.
    These records should never be deleted.
    """
    id = models.UUIDField(primary_key=True, editable=False)
    entity_type = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    description = models.TextField(default='')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        # No delete permissions - these records are permanent
        default_permissions = ('add', 'view', 'change')
    
    def __str__(self):
        return f"[SYSTEM PLACEHOLDER] {self.entity_type}: {self.name}"