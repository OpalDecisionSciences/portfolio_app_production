"""
Celery tasks for birthday email campaigns.
Sends monthly birthday greetings to newsletter subscribers.
"""

from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@shared_task
def send_birthday_emails():
    """
    Monthly task to send birthday emails to users.
    Should be scheduled to run on the 1st of each month.
    """
    from accounts.models import User
    from restaurants.models import Restaurant, RestaurantRecommendation
    
    current_month = timezone.now().month
    
    # Get all users with birthdays this month who are subscribed to newsletter
    birthday_users = User.objects.filter(
        birth_month=current_month,
        newsletter_subscription=True,
        is_active=True
    )
    
    success_count = 0
    failure_count = 0
    
    for user in birthday_users:
        try:
            # Get top restaurants in user's location
            top_restaurants = []
            if user.city and user.country:
                # Try to get location-specific recommendations
                recommendations = RestaurantRecommendation.objects.filter(
                    city=user.city,
                    country=user.country,
                    is_featured_homepage=True
                ).select_related('restaurant')[:5]
                
                if not recommendations:
                    # Fallback to country-level recommendations
                    recommendations = RestaurantRecommendation.objects.filter(
                        country=user.country,
                        is_featured_homepage=True
                    ).select_related('restaurant')[:5]
            
            if not top_restaurants:
                # Fallback to global top recommendations
                recommendations = RestaurantRecommendation.objects.filter(
                    is_featured_homepage=True
                ).select_related('restaurant')[:5]
            
            top_restaurants = [rec.restaurant for rec in recommendations]
            
            # Render email content
            context = {
                'user': user,
                'first_name': user.first_name or user.username,
                'month_name': datetime(2000, current_month, 1).strftime('%B'),
                'top_restaurants': top_restaurants,
                'has_location': bool(user.city and user.country),
                'location_display': user.location_display,
            }
            
            html_content = render_to_string('emails/birthday_greeting.html', context)
            text_content = render_to_string('emails/birthday_greeting.txt', context)
            
            # Send email
            send_mail(
                subject=f'🎂 Happy Birthday from Opal Decision Sciences, {user.first_name}!',
                message=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_content,
                fail_silently=False
            )
            
            success_count += 1
            logger.info(f"Birthday email sent to {user.email}")
            
        except Exception as e:
            failure_count += 1
            logger.error(f"Failed to send birthday email to {user.email}: {str(e)}")
    
    logger.info(f"Birthday email campaign completed: {success_count} sent, {failure_count} failed")
    
    return {
        'success_count': success_count,
        'failure_count': failure_count,
        'total_users': birthday_users.count()
    }


@shared_task
def update_top_restaurant_recommendations():
    """
    Daily task to update the top restaurant recommendations.
    Calculates scores and updates the homepage featured restaurants.
    """
    from restaurants.models import RestaurantRecommendation
    
    try:
        RestaurantRecommendation.update_top_recommendations(limit=20)
        logger.info("Top restaurant recommendations updated successfully")
        return {'status': 'success', 'message': 'Top recommendations updated'}
    except Exception as e:
        logger.error(f"Failed to update top recommendations: {str(e)}")
        return {'status': 'error', 'message': str(e)}


@shared_task
def track_recommendation_impression(restaurant_ids, user_id, context='homepage_featured'):
    """
    Track when recommendations are shown to users (impressions).
    """
    from restaurants.models import Restaurant, UserRecommendationInteraction
    from accounts.models import User
    
    try:
        user = User.objects.get(id=user_id)
        session_id = f"{user_id}_{timezone.now().timestamp()}"
        
        for restaurant_id in restaurant_ids:
            restaurant = Restaurant.objects.get(id=restaurant_id)
            
            # Create or update interaction
            UserRecommendationInteraction.objects.get_or_create(
                user=user,
                restaurant=restaurant,
                interaction_type='impression',
                session_id=session_id,
                defaults={
                    'interaction_context': context,
                    'recommendation_score_at_time': getattr(
                        restaurant.recommendation_data, 
                        'recommendation_score', 
                        0.0
                    ) if hasattr(restaurant, 'recommendation_data') else 0.0
                }
            )
        
        return {'status': 'success', 'tracked': len(restaurant_ids)}
    except Exception as e:
        logger.error(f"Failed to track impressions: {str(e)}")
        return {'status': 'error', 'message': str(e)}