from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.crypto import get_random_string
from datetime import timedelta
from ratelimit.decorators import ratelimit
from portfolio_project.constants import LOGIN_RATE_LIMIT, PASSWORD_RESET_RATE_LIMIT
import json
import logging

from .models import User, UserFavoriteRestaurant, UserChatHistory, PasswordResetToken
from .forms import (
    CustomUserCreationForm, 
    CustomAuthenticationForm, 
    CustomPasswordResetForm,
    UserProfileForm,
    FavoriteRestaurantForm
)
from restaurants.models import Restaurant

logger = logging.getLogger(__name__)


@ratelimit(key='ip', rate=LOGIN_RATE_LIMIT, method='POST', block=True)
def register_view(request):
    """
    User registration view with enhanced form validation.
    """
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            # Log the user in automatically
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            
            if user:
                login(request, user)
                messages.success(request, f'Welcome to Michelin Star Service, {user.get_short_name()}! Your account has been created successfully.')
                
                # Redirect to profile completion if needed
                if not user.has_complete_profile:
                    messages.info(request, 'Complete your profile to get personalized restaurant recommendations.')
                    return redirect('accounts:profile')
                
                return redirect('home')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


@ratelimit(key='ip', rate=LOGIN_RATE_LIMIT, method='POST', block=True)
def login_view(request):
    """
    Enhanced login view with remember me functionality.
    """
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            remember_me = form.cleaned_data.get('remember_me')
            
            user = authenticate(username=username, password=password)
            if user:
                login(request, user)
                
                # Set session expiry based on remember me
                if remember_me:
                    request.session.set_expiry(2592000)  # 30 days
                else:
                    request.session.set_expiry(0)  # Browser close
                
                messages.success(request, f'Welcome back, {user.get_short_name()}!')
                
                # Redirect to next page or home
                next_page = request.GET.get('next', 'home')
                return redirect(next_page)
        else:
            messages.error(request, 'Invalid email/username or password.')
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """
    User logout view.
    """
    username = request.user.get_short_name() if request.user.is_authenticated else None
    logout(request)
    
    if username:
        messages.success(request, f'Goodbye, {username}! You have been logged out successfully.')
    
    return redirect('home')


@login_required
def profile_view(request):
    """
    User profile view and editing.
    """
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            
            # Update profile completion status
            user.profile_completed = user.has_complete_profile
            user.save()
            
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserProfileForm(instance=request.user)
    
    # Get user's favorite restaurants
    favorites = UserFavoriteRestaurant.objects.filter(user=request.user).select_related('restaurant')
    recent_chats = UserChatHistory.objects.filter(user=request.user)[:5]
    
    context = {
        'form': form,
        'favorites': favorites,
        'recent_chats': recent_chats,
        'favorites_count': favorites.count(),
        'profile_completion': _calculate_profile_completion(request.user)
    }
    
    return render(request, 'accounts/profile.html', context)


@login_required
def favorites_view(request):
    """
    View user's favorite restaurants.
    """
    favorites = UserFavoriteRestaurant.objects.filter(
        user=request.user
    ).select_related('restaurant').order_by('-created_at')
    
    # Group favorites by category
    favorites_by_category = {}
    for favorite in favorites:
        category = favorite.get_category_display()
        if category not in favorites_by_category:
            favorites_by_category[category] = []
        favorites_by_category[category].append(favorite)
    
    context = {
        'favorites': favorites,
        'favorites_by_category': favorites_by_category,
        'total_favorites': favorites.count()
    }
    
    return render(request, 'accounts/favorites.html', context)


@login_required
@require_http_methods(["POST"])
def add_favorite_view(request, restaurant_id):
    """
    Add a restaurant to user's favorites via AJAX.
    """
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        # Check if already favorited
        favorite, created = UserFavoriteRestaurant.objects.get_or_create(
            user=request.user,
            restaurant=restaurant,
            defaults={'category': 'to_visit'}
        )
        
        if created:
            return JsonResponse({
                'success': True,
                'message': f'{restaurant.name} added to your favorites!',
                'favorited': True
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'{restaurant.name} is already in your favorites.',
                'favorited': True
            })
            
    except Exception as e:
        logger.error(f"Error adding favorite: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'Failed to add to favorites. Please try again.',
            'favorited': False
        })


@login_required
@require_http_methods(["POST"])
def remove_favorite_view(request, restaurant_id):
    """
    Remove a restaurant from user's favorites via AJAX.
    """
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        favorite = UserFavoriteRestaurant.objects.filter(
            user=request.user,
            restaurant=restaurant
        ).first()
        
        if favorite:
            favorite.delete()
            return JsonResponse({
                'success': True,
                'message': f'{restaurant.name} removed from your favorites.',
                'favorited': False
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'{restaurant.name} is not in your favorites.',
                'favorited': False
            })
            
    except Exception as e:
        logger.error(f"Error removing favorite: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'Failed to remove from favorites. Please try again.',
            'favorited': True
        })


@login_required
def edit_favorite_view(request, favorite_id):
    """
    Edit favorite restaurant details.
    """
    favorite = get_object_or_404(UserFavoriteRestaurant, id=favorite_id, user=request.user)
    
    if request.method == 'POST':
        form = FavoriteRestaurantForm(request.POST, instance=favorite)
        if form.is_valid():
            form.save()
            messages.success(request, f'Updated your notes for {favorite.restaurant.name}!')
            return redirect('accounts:favorites')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = FavoriteRestaurantForm(instance=favorite)
        # Pre-populate recommended dishes as comma-separated string
        if favorite.recommended_dishes:
            form.initial['recommended_dishes'] = ', '.join(favorite.recommended_dishes)
    
    context = {
        'form': form,
        'favorite': favorite,
        'restaurant': favorite.restaurant
    }
    
    return render(request, 'accounts/edit_favorite.html', context)


@ratelimit(key='ip', rate=PASSWORD_RESET_RATE_LIMIT, method='POST', block=True)
def password_reset_request_view(request):
    """
    Custom password reset request view.
    """
    if request.method == 'POST':
        form = CustomPasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.get(email=email)
            
            # Create custom password reset token
            token = get_random_string(64)
            expires_at = timezone.now() + timedelta(hours=24)
            
            PasswordResetToken.objects.create(
                user=user,
                token=token,
                expires_at=expires_at,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            # Send reset email
            reset_url = request.build_absolute_uri(
                reverse('accounts:password_reset_confirm', kwargs={'token': token})
            )
            
            try:
                send_mail(
                    subject='Reset Your Michelin Star Service Password',
                    message=f'''
Hello {user.get_short_name()},

You requested a password reset for your Michelin Star Service account.

Click the link below to reset your password:
{reset_url}

This link will expire in 24 hours.

If you didn't request this reset, please ignore this email.

Best regards,
The Michelin Star Service Team
                    ''',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False
                )
                
                messages.success(request, 'Password reset instructions have been sent to your email.')
                return redirect('accounts:login')
                
            except Exception as e:
                logger.error(f"Failed to send password reset email: {str(e)}")
                messages.error(request, 'Failed to send reset email. Please try again later.')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomPasswordResetForm()
    
    return render(request, 'accounts/password_reset.html', {'form': form})


def password_reset_confirm_view(request, token):
    """
    Password reset confirmation view.
    """
    reset_token = get_object_or_404(PasswordResetToken, token=token)
    
    if not reset_token.is_valid():
        messages.error(request, 'This password reset link has expired or is invalid.')
        return redirect('accounts:password_reset_request')
    
    if request.method == 'POST':
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        
        if password1 and password1 == password2:
            user = reset_token.user
            user.set_password(password1)
            user.save()
            
            # Mark token as used
            reset_token.used = True
            reset_token.save()
            
            messages.success(request, 'Your password has been reset successfully! You can now log in.')
            return redirect('accounts:login')
        else:
            messages.error(request, 'Passwords do not match.')
    
    context = {
        'token': token,
        'user': reset_token.user
    }
    
    return render(request, 'accounts/password_reset_confirm.html', context)


@login_required
def dashboard_view(request):
    """
    User dashboard with overview of favorites, chat history, and recommendations.
    """
    favorites = UserFavoriteRestaurant.objects.filter(user=request.user).select_related('restaurant')[:6]
    recent_chats = UserChatHistory.objects.filter(user=request.user)[:3]
    
    # Optimized statistics - combine queries to prevent N+1 performance issues
    # Before: 3 separate queries. After: 1 aggregate query + 1 count query (50% reduction)
    from django.db.models import Q, Count, Case, When, IntegerField
    
    # Single aggregated query for favorites statistics
    favorites_stats = UserFavoriteRestaurant.objects.filter(user=request.user).aggregate(
        total_favorites=Count('id'),
        restaurants_visited=Count('id', filter=Q(category='visited'))
    )
    
    # Single count query for chats
    total_chats = UserChatHistory.objects.filter(user=request.user).count()
    
    stats = {
        'total_favorites': favorites_stats['total_favorites'],
        'restaurants_visited': favorites_stats['restaurants_visited'],
        'total_chats': total_chats,
        'profile_completion': _calculate_profile_completion(request.user)
    }
    
    context = {
        'favorites': favorites,
        'recent_chats': recent_chats,
        'stats': stats,
        'user': request.user
    }
    
    return render(request, 'accounts/dashboard.html', context)


def _calculate_profile_completion(user):
    """
    Calculate profile completion percentage.
    """
    fields_to_check = [
        'first_name', 'last_name', 'email', 'location', 
        'preferred_cuisines', 'price_range_preference'
    ]
    
    completed_fields = 0
    total_fields = len(fields_to_check)
    
    for field in fields_to_check:
        value = getattr(user, field, None)
        if value:
            if isinstance(value, list) and len(value) > 0:
                completed_fields += 1
            elif isinstance(value, str) and value.strip():
                completed_fields += 1
            elif value is not None:
                completed_fields += 1
    
    return int((completed_fields / total_fields) * 100)