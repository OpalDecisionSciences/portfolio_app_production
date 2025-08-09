from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
import os
import json
import logging
from .safety import chat_safety
from accounts.models import User, UserChatHistory, UserFavoriteRestaurant
from restaurants.models import Restaurant

logger = logging.getLogger(__name__)


def chat_view(request):
    """
    Render the chat interface with RAG service configuration, safety guidelines, and user context.
    """
    # Get RAG service URL from environment or use default
    rag_service_url = os.getenv('RAG_SERVICE_URL', 'http://rag_service:8001')
    
    # Get safety guidelines for display
    safety_guidelines = chat_safety.get_safety_guidelines()
    
    # Get user-specific context if authenticated
    user_context = {}
    user_favorites = []
    user_preferences = {}
    
    if request.user.is_authenticated:
        user_context = {
            'user_id': str(request.user.id),
            'full_name': request.user.get_full_name(),
            'short_name': request.user.get_short_name(),
            'location': request.user.location_display,
            'profile_completed': request.user.has_complete_profile,
        }
        
        # Get user's favorite restaurants for context
        user_favorites = UserFavoriteRestaurant.objects.filter(
            user=request.user
        ).select_related('restaurant')[:10]
        
        # Get user's dining preferences
        user_preferences = {
            'preferred_cuisines': request.user.preferred_cuisines,
            'dietary_restrictions': request.user.dietary_restrictions,
            'price_range_preference': request.user.get_price_range_preference_display(),
        }
        
        # Update last active timestamp
        request.user.last_active = timezone.now()
        request.user.save(update_fields=['last_active'])
    
    context = {
        'rag_service_url': rag_service_url,
        'safety_guidelines': safety_guidelines,
        'user_context': user_context,
        'user_favorites': user_favorites,
        'user_preferences': user_preferences,
        'is_authenticated': request.user.is_authenticated,
    }
    
    return render(request, 'chat/chat.html', context)


@method_decorator(csrf_exempt, name='dispatch')
class ChatSafetyValidationView(View):
    """
    Server-side safety validation endpoint for chat messages.
    Provides an additional layer of validation before sending to RAG service.
    """
    
    def post(self, request):
        """
        Validate a message for safety and topic relevance.
        
        Expected JSON payload:
        {
            "message": "user message to validate",
            "user_id": "optional user identifier"
        }
        
        Returns:
        {
            "valid": true/false,
            "reason": "explanation if invalid",
            "cleaned_message": "sanitized message if valid"
        }
        """
        try:
            data = json.loads(request.body)
            message = data.get('message', '')
            user_id = data.get('user_id', request.session.session_key)
            
            # Validate the message
            validation_result = chat_safety.validate_message(message, user_id)
            
            # Log validation attempts for monitoring
            if not validation_result['valid']:
                logger.warning(f"Message validation failed: {validation_result.get('category', 'unknown')} - User: {user_id}")
            
            return JsonResponse(validation_result)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'valid': False,
                'reason': 'Invalid request format. Please try again.',
                'category': 'invalid_request'
            }, status=400)
        except Exception as e:
            logger.error(f"Error in chat safety validation: {str(e)}")
            return JsonResponse({
                'valid': False,
                'reason': 'Internal error. Please try again.',
                'category': 'server_error'
            }, status=500)


@require_http_methods(["GET"])
def chat_guidelines_view(request):
    """
    API endpoint to get chat safety guidelines.
    """
    guidelines = chat_safety.get_safety_guidelines()
    return JsonResponse(guidelines)


@login_required
@require_http_methods(["POST"])
def start_chat_session_view(request):
    """
    Start a new chat session for authenticated users.
    """
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        
        if conversation_id:
            # Create or update chat history record
            chat_history, created = UserChatHistory.objects.get_or_create(
                user=request.user,
                conversation_id=conversation_id,
                defaults={'session_start': timezone.now()}
            )
            
            return JsonResponse({
                'success': True,
                'chat_history_id': str(chat_history.id),
                'user_preferences': {
                    'preferred_cuisines': request.user.preferred_cuisines,
                    'dietary_restrictions': request.user.dietary_restrictions,
                    'location': request.user.location_display,
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Missing conversation_id'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error starting chat session: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to start chat session'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def end_chat_session_view(request):
    """
    End a chat session and save conversation summary.
    """
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        message_count = data.get('message_count', 0)
        topics_discussed = data.get('topics_discussed', [])
        satisfaction_rating = data.get('satisfaction_rating')
        
        if conversation_id:
            try:
                chat_history = UserChatHistory.objects.get(
                    user=request.user,
                    conversation_id=conversation_id
                )
                
                # Update chat session details
                chat_history.session_end = timezone.now()
                chat_history.message_count = message_count
                chat_history.topics_discussed = topics_discussed
                
                if satisfaction_rating:
                    chat_history.satisfaction_rating = satisfaction_rating
                
                chat_history.save()
                
                return JsonResponse({'success': True})
                
            except UserChatHistory.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Chat session not found'
                }, status=404)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Missing conversation_id'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error ending chat session: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to end chat session'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def add_restaurant_to_favorites_from_chat_view(request):
    """
    Add a restaurant to favorites directly from chat interface.
    """
    try:
        data = json.loads(request.body)
        restaurant_id = data.get('restaurant_id')
        category = data.get('category', 'to_visit')
        notes = data.get('notes', '')
        
        if restaurant_id:
            restaurant = get_object_or_404(Restaurant, id=restaurant_id)
            
            favorite, created = UserFavoriteRestaurant.objects.get_or_create(
                user=request.user,
                restaurant=restaurant,
                defaults={
                    'category': category,
                    'notes': notes or f'Added from AI chat conversation on {timezone.now().date()}'
                }
            )
            
            if created:
                return JsonResponse({
                    'success': True,
                    'message': f'{restaurant.name} has been added to your favorites!',
                    'favorite_id': str(favorite.id)
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': f'{restaurant.name} is already in your favorites.',
                    'favorite_id': str(favorite.id)
                })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Missing restaurant_id'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error adding restaurant to favorites from chat: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to add restaurant to favorites'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_user_context_view(request):
    """
    Get user context for personalized chat responses.
    """
    try:
        # Get user's recent favorites
        recent_favorites = UserFavoriteRestaurant.objects.filter(
            user=request.user
        ).select_related('restaurant').order_by('-added_at')[:5]
        
        # Get user's recent chat history
        recent_chats = UserChatHistory.objects.filter(
            user=request.user
        ).order_by('-session_start')[:3]
        
        # Prepare favorites data
        favorites_data = []
        for favorite in recent_favorites:
            favorites_data.append({
                'restaurant_name': favorite.restaurant.name,
                'restaurant_id': str(favorite.restaurant.id),
                'category': favorite.get_category_display(),
                'cuisine_type': favorite.restaurant.cuisine_type,
                'michelin_stars': favorite.restaurant.michelin_stars,
                'location': f"{favorite.restaurant.city}, {favorite.restaurant.country}",
                'notes': favorite.notes
            })
        
        # Prepare chat history data
        chat_history_data = []
        for chat in recent_chats:
            chat_history_data.append({
                'date': chat.session_start.date().isoformat(),
                'topics_discussed': chat.topics_discussed,
                'message_count': chat.message_count
            })
        
        context_data = {
            'user_id': str(request.user.id),
            'profile': {
                'name': request.user.get_full_name(),
                'location': request.user.location_display,
                'preferred_cuisines': request.user.preferred_cuisines,
                'dietary_restrictions': request.user.dietary_restrictions,
                'price_range_preference': request.user.price_range_preference,
            },
            'recent_favorites': favorites_data,
            'recent_chat_history': chat_history_data,
            'profile_completed': request.user.has_complete_profile
        }
        
        return JsonResponse({
            'success': True,
            'context': context_data
        })
        
    except Exception as e:
        logger.error(f"Error getting user context: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to get user context'
        }, status=500)