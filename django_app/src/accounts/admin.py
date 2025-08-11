from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, UserFavoriteRestaurant, UserChatHistory, PasswordResetToken


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom User admin with enhanced functionality.
    """
    list_display = [
        'email', 'username', 'get_full_name', 'get_location_display', 
        'profile_completed', 'email_verified', 'last_active', 'date_joined'
    ]
    list_filter = [
        'profile_completed', 'email_verified', 'newsletter_subscription',
        'price_range_preference', 'country', 'birth_month', 'is_staff', 'is_active', 'date_joined'
    ]
    search_fields = ['email', 'username', 'first_name', 'last_name', 'city', 'country']
    ordering = ['-date_joined']
    
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Profile Information', {
            'fields': ('phone_number', 'birth_month', 'city', 'state', 'country')
        }),
        ('Dining Preferences', {
            'fields': ('preferred_cuisines', 'dietary_restrictions', 'price_range_preference')
        }),
        ('Account Settings', {
            'fields': ('email_verified', 'newsletter_subscription', 'push_notifications')
        }),
        ('Metadata', {
            'fields': ('profile_completed', 'last_active', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['last_active', 'created_at', 'updated_at']
    
    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username
    get_full_name.short_description = 'Full Name'
    
    def get_location_display(self, obj):
        return obj.location_display
    get_location_display.short_description = 'Location'


@admin.register(UserFavoriteRestaurant)
class UserFavoriteRestaurantAdmin(admin.ModelAdmin):
    """
    Admin for user favorite restaurants.
    """
    list_display = [
        'user', 'restaurant', 'category', 'personal_rating', 
        'visit_date', 'created_at'
    ]
    list_filter = ['category', 'personal_rating', 'created_at']
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name',
        'restaurant__name', 'restaurant__city'
    ]
    date_hierarchy = 'created_at'
    raw_id_fields = ['user', 'restaurant']
    
    fieldsets = (
        (None, {
            'fields': ('user', 'restaurant', 'category')
        }),
        ('Review Details', {
            'fields': ('personal_rating', 'notes', 'visit_date', 'recommended_dishes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(UserChatHistory)
class UserChatHistoryAdmin(admin.ModelAdmin):
    """
    Admin for user chat history.
    """
    list_display = [
        'user', 'conversation_id', 'session_start', 'session_end',
        'message_count', 'satisfaction_rating'
    ]
    list_filter = ['satisfaction_rating', 'session_start']
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name',
        'conversation_id'
    ]
    date_hierarchy = 'session_start'
    raw_id_fields = ['user']
    filter_horizontal = ['restaurants_mentioned']
    
    fieldsets = (
        (None, {
            'fields': ('user', 'conversation_id')
        }),
        ('Session Details', {
            'fields': ('session_start', 'session_end', 'message_count')
        }),
        ('Content Analysis', {
            'fields': ('topics_discussed', 'restaurants_mentioned', 'preferences_learned')
        }),
        ('Feedback', {
            'fields': ('satisfaction_rating',)
        }),
    )
    
    readonly_fields = ['session_start', 'created_at', 'updated_at']


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    """
    Admin for password reset tokens.
    """
    list_display = [
        'user', 'token_preview', 'created_at', 'expires_at', 
        'used', 'ip_address'
    ]
    list_filter = ['used', 'created_at']
    search_fields = ['user__email', 'user__username', 'ip_address']
    date_hierarchy = 'created_at'
    raw_id_fields = ['user']
    
    readonly_fields = ['token', 'created_at']
    
    def token_preview(self, obj):
        """Show a preview of the token for security."""
        if obj.token:
            return f"{obj.token[:8]}...{obj.token[-8:]}"
        return "-"
    token_preview.short_description = 'Token Preview'
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing of tokens for security."""
        return False