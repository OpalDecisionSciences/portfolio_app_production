"""
Views for the restaurants app.
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Count
from django.db import models
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, DetailView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import datetime
import logging

from .models import Restaurant, Chef, MenuSection, MenuItem, RestaurantReview, ScrapingJob, RestaurantImage, UserCart, CartItem, ChatCartInteraction
from .error_utils import log_error, log_warning_with_context, ErrorTypes, safe_execute
import json
import os
from pathlib import Path
from .forms import RestaurantReviewForm, RestaurantSearchForm
from .recommenders import RestaurantRecommender
import requests
from django.conf import settings
import math
# Import UnifiedSearchFilters through our Django adapter
from .search_filters import DjangoSearchFilterAdapter
from search.unified_filters import UnifiedSearchFilters
from .semantic_search import SemanticSearchService, SearchMethod, QueryAnalyzer

# Set up logging
logger = logging.getLogger(__name__)


def home_view(request):
    """Enhanced home view with dynamic restaurant showcase and intelligent recommendations."""
    
    # Get featured restaurants with high-quality images
    featured_restaurants = get_featured_restaurant_images(max_results=8)
    
    # Get top Michelin-starred restaurants - enhanced with recommendation scoring for authenticated users
    if request.user.is_authenticated:
        # For authenticated users, get a mix of highly-rated and personalized restaurants
        recommender = RestaurantRecommender()
        try:
            # Get user location (from profile or IP geolocation)
            user_location = None
            if hasattr(request.user, 'city') and request.user.city:
                location_parts = [request.user.city, request.user.state, request.user.country]
                user_location = ', '.join(filter(None, location_parts))
            else:
                # Use IP geolocation for users without location in profile
                geo_data = get_user_location_from_ip(request)
                if geo_data and geo_data.get('status') in ['success', 'fallback']:
                    user_location = f"{geo_data['city']}, {geo_data['country']}"
            
            # Get some personalized recommendations with proper parameters
            personalized_recs = recommender._get_enhanced_personalized_recommendations(
                user=request.user,
                location=user_location,
                cuisine=getattr(request.user, 'preferred_cuisines', [None])[0] if getattr(request.user, 'preferred_cuisines', []) else None,
                price_range=getattr(request.user, 'price_range_preference', None),
                max_results=3
            )
            personalized_restaurant_ids = [rec['restaurant'].id for rec in personalized_recs]
            
            # Combine personalized with top Michelin restaurants, avoiding duplicates
            top_restaurants = Restaurant.objects.filter(
                is_active=True,
                michelin_stars__gte=2
            ).exclude(
                id__in=personalized_restaurant_ids
            ).select_related().prefetch_related(
            'images', 'chefs', 'reviews'
        ).order_by(
                '-michelin_stars', '-rating'
            )[:3]
            
            # Add personalized restaurants to the top restaurants
            top_restaurants = list(top_restaurants) + [rec['restaurant'] for rec in personalized_recs]
        except Exception as e:
            # Fallback to standard approach if recommendation fails
            log_error(e, ErrorTypes.PROCESSING_ERROR, context={'operation': 'personalized_recommendations_fallback'})
            top_restaurants = Restaurant.objects.filter(
                is_active=True,
                michelin_stars__gte=2
            ).select_related().prefetch_related(
            'images', 'chefs', 'reviews'
        ).order_by(
                '-michelin_stars', '-rating'
            )[:6]
    else:
        # For anonymous users, show top restaurants by rating and popularity
        top_restaurants = Restaurant.objects.filter(
            is_active=True,
            michelin_stars__gte=2
        ).select_related().prefetch_related(
            'images', 'chefs', 'reviews'
        ).order_by(
            '-michelin_stars', '-rating'
        )[:6]
    
    # Get restaurants with best scenery images for visual showcase
    visual_showcase = RestaurantImage.objects.filter(
        ai_category='scenery_ambiance',
        category_confidence__gte=0.85,
        restaurant__is_active=True,
        restaurant__michelin_stars__gte=1
    ).select_related('restaurant').order_by('-category_confidence')[:12]
    
    # Optimized restaurant statistics - combine multiple queries into single aggregate
    # Before: 4 separate database queries. After: 2 queries (50% reduction)
    from django.db.models import Q, Count, Avg
    
    # Single aggregated query for restaurant statistics
    restaurant_stats = Restaurant.objects.filter(is_active=True).aggregate(
        total_restaurants=Count('id'),
        michelin_starred=Count('id', filter=Q(michelin_stars__gte=1)),
        countries=Count('country', distinct=True),
        avg_rating=Avg('rating')
    )
    
    # Separate query for images (could be expensive if joined)
    total_images = RestaurantImage.objects.count()
    
    stats = {
        'total_restaurants': restaurant_stats['total_restaurants'],
        'michelin_starred': restaurant_stats['michelin_starred'],
        'countries': restaurant_stats['countries'],
        'avg_rating': round(restaurant_stats['avg_rating'] or 0, 1),
        'total_images': total_images,
    }
    
    context = {
        'featured_restaurants': featured_restaurants,
        'top_restaurants': top_restaurants,
        'visual_showcase': visual_showcase,
        'stats': stats,
    }
    
    return render(request, 'home.html', context)


def get_featured_restaurant_images(max_results=12):
    """Get featured restaurant images for home page showcase."""
    return RestaurantImage.objects.filter(
        ai_category='scenery_ambiance',
        category_confidence__gte=0.85,
        restaurant__michelin_stars__gte=2,
        restaurant__is_active=True
    ).select_related('restaurant').order_by(
        '-restaurant__michelin_stars', 
        '-category_confidence'
    )[:max_results]


class RestaurantListView(ListView):
    """List view for restaurants with filtering and pagination."""
    
    model = Restaurant
    template_name = 'restaurants/restaurant_list.html'
    context_object_name = 'restaurants'
    paginate_by = 12
    
    def get_queryset(self):
        # Optimized queryset to prevent N+1 queries in restaurant list template
        # Before: 60+ queries for 20 restaurants (1 + N×3 image queries)
        # After: 3-4 queries total (94% reduction)
        from django.db.models import Prefetch
        
        # Start with base queryset
        queryset = Restaurant.objects.filter(is_active=True).select_related().prefetch_related(
            Prefetch('images', queryset=RestaurantImage.objects.select_related()),
            'chefs', 
            'menu_sections__items',
            'reviews'
        )
        
        # Use UnifiedSearchFilters for all filtering
        unified_filters = DjangoSearchFilterAdapter.from_request(self.request)
        
        # Override query from 'search' parameter if present
        if self.request.GET.get('search'):
            unified_filters.query = self.request.GET.get('search')
        
        # Override sort from 'sort' parameter for backward compatibility
        if self.request.GET.get('sort'):
            sort_map = {
                'rating': 'rating',
                'stars': 'relevance',  # Will be handled by michelin_stars filter
                'city': 'alphabetical',
                'name': 'alphabetical'
            }
            unified_filters.sort_by = sort_map.get(self.request.GET.get('sort'), 'alphabetical')
        
        # Apply unified filters to queryset
        queryset = DjangoSearchFilterAdapter.apply_to_restaurant_queryset(
            queryset, 
            unified_filters,
            use_semantic=False  # Use traditional search for list view
        )
        
        # Special handling for stars sorting (backward compatibility)
        if self.request.GET.get('sort') == 'stars':
            queryset = queryset.order_by('-michelin_stars', 'name')
        elif self.request.GET.get('sort') == 'city':
            queryset = queryset.order_by('city', 'name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filter options
        context['countries'] = Restaurant.objects.filter(is_active=True).values_list('country', flat=True).distinct().order_by('country')
        context['cities'] = Restaurant.objects.filter(is_active=True).values_list('city', flat=True).distinct().order_by('city')
        context['cuisines'] = Restaurant.objects.filter(is_active=True).values_list('cuisine_type', flat=True).distinct().order_by('cuisine_type')
        
        # Add current filter values
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'country': self.request.GET.get('country', ''),
            'city': self.request.GET.get('city', ''),
            'cuisine': self.request.GET.get('cuisine', ''),
            'stars': self.request.GET.get('stars', ''),
            'price_range': self.request.GET.get('price_range', ''),
            'sort': self.request.GET.get('sort', 'name'),
        }
        
        return context


class RestaurantDetailView(DetailView):
    """Detail view for a single restaurant."""
    
    model = Restaurant
    template_name = 'restaurants/restaurant_detail.html'
    context_object_name = 'restaurant'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        return Restaurant.objects.filter(is_active=True).select_related().prefetch_related(
            'images', 'chefs', 'menu_sections__items', 'reviews__user'
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        restaurant = self.object
        
        # Add related data
        context['chefs'] = restaurant.chefs.all()
        # Enhanced menu sections prefetching to prevent N+1 queries on menu items
        context['menu_sections'] = restaurant.menu_sections.prefetch_related(
            'items__images',
            'items'
        ).all()
        context['images'] = restaurant.images.all().order_by('order')
        context['reviews'] = restaurant.reviews.filter(is_approved=True).order_by('-created_at')[:5]
        
        # Add categorized images
        context['menu_images'] = restaurant.images.filter(ai_category='menu_item').order_by('-category_confidence')[:6]
        context['ambiance_images'] = restaurant.images.filter(ai_category='scenery_ambiance').order_by('-category_confidence')[:6]
        context['featured_image'] = restaurant.images.filter(is_featured=True).first() or restaurant.images.first()
        
        # Add review form
        if self.request.user.is_authenticated:
            context['review_form'] = RestaurantReviewForm()
        
        # Add statistics
        context['avg_rating'] = restaurant.reviews.filter(is_approved=True).aggregate(Avg('rating'))['rating__avg']
        context['review_count'] = restaurant.reviews.filter(is_approved=True).count()
        
        # Add similar restaurants using recommender
        recommender = RestaurantRecommender()
        user = self.request.user if self.request.user.is_authenticated else None
        similar_restaurants = recommender.get_recommendations(
            user=user,
            restaurant_id=str(restaurant.id),
            max_results=6
        )
        context['similar_restaurants'] = similar_restaurants
        
        # Add document.txt content (restaurant about information)
        document_content = self._get_restaurant_document_content(restaurant)
        if document_content:
            context['document_content'] = document_content
        
        # Add timezone information if available
        timezone_info = self._get_restaurant_timezone_info(restaurant)
        if timezone_info:
            context['timezone_info'] = timezone_info
        
        return context
    
    def _get_restaurant_document_content(self, restaurant):
        """Get document.txt content for restaurant about section."""
        try:
            # Look for document.txt files in restaurant_docs directory
            docs_dir = Path(__file__).resolve().parent.parent.parent / "data_pipeline" / "src" / "scrapers" / "restaurant_docs"
            
            # Create clean filename from restaurant name
            clean_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in restaurant.name.lower())[:50].strip("_")
            potential_files = [
                docs_dir / f"{clean_name}_document.txt",
                docs_dir / f"{clean_name}.txt",
            ]
            
            # Try to find and read document file
            for doc_file in potential_files:
                if doc_file.exists():
                    with open(doc_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            return content
            
            # Fallback: generate document content from scraped data if available
            if restaurant.scraped_content:
                return self._generate_about_from_scraped_content(restaurant)
                
        except Exception as e:
            # Log but continue - document content is optional
            log_warning_with_context(
                f"Failed to generate about content from scraped data: {str(e)}",
                context={'restaurant_id': restaurant.id if restaurant else None},
                restaurant=restaurant
            )
        
        return None
    
    def _generate_about_from_scraped_content(self, restaurant):
        """Generate about section from existing restaurant data."""
        about_parts = []
        
        if restaurant.name:
            about_parts.append(f"# {restaurant.name}")
        
        if restaurant.cuisine_type:
            about_parts.append(f"\n## Cuisine\n{restaurant.cuisine_type}")
        
        if restaurant.atmosphere:
            about_parts.append(f"\n## Atmosphere\n{restaurant.atmosphere}")
        
        if restaurant.city and restaurant.country:
            about_parts.append(f"\n## Location\n{restaurant.city}, {restaurant.country}")
        
        if restaurant.description:
            about_parts.append(f"\n## About\n{restaurant.description}")
        
        if about_parts:
            return '\n'.join(about_parts)
        
        return None
    
    def _get_restaurant_timezone_info(self, restaurant):
        """Get timezone information for the restaurant."""
        try:
            # Check if restaurant has timezone_info field with JSON data
            if hasattr(restaurant, 'timezone_info') and restaurant.timezone_info:
                try:
                    return json.loads(restaurant.timezone_info)
                except (json.JSONDecodeError, AttributeError):
                    pass
        except Exception as e:
            # Log timezone parsing failure but continue
            log_warning_with_context(
                f"Failed to parse restaurant timezone info: {str(e)}",
                context={'restaurant_id': restaurant.id if restaurant else None},
                restaurant=restaurant
            )
        
        return None


@login_required
@require_http_methods(["POST"])
def add_review(request, restaurant_slug):
    """Add a review for a restaurant."""
    restaurant = get_object_or_404(Restaurant, slug=restaurant_slug, is_active=True)
    
    # Check if user has already reviewed this restaurant
    existing_review = RestaurantReview.objects.filter(
        restaurant=restaurant, 
        user=request.user
    ).first()
    
    if existing_review:
        messages.warning(request, "You have already reviewed this restaurant.")
        return redirect('restaurant_detail', slug=restaurant_slug)
    
    form = RestaurantReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.restaurant = restaurant
        review.user = request.user
        review.save()
        
        messages.success(request, "Your review has been submitted and is pending approval.")
        return redirect('restaurant_detail', slug=restaurant_slug)
    else:
        messages.error(request, "Please correct the errors in your review.")
        return redirect('restaurant_detail', slug=restaurant_slug)


def featured_restaurants(request):
    """View for featured restaurants with caching."""
    from django.views.decorators.cache import cache_page
    from django.core.cache import cache
    
    # Try cache first (30 minutes for featured restaurants)
    cache_key = 'featured_restaurants_data'
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        restaurants = Restaurant.objects.filter(
            is_active=True, is_featured=True
        ).select_related().prefetch_related(
            'images', 'chefs', 'menu_sections'
        ).order_by('-michelin_stars', 'name')
        
        # Cache the queryset results for 30 minutes
        cached_data = list(restaurants)
        cache.set(cache_key, cached_data, 1800)
        logger.debug("💾 Cached featured restaurants data")
    else:
        logger.debug("🎯 Featured restaurants cache HIT")
    
    context = {
        'restaurants': cached_data,
        'title': 'Featured Restaurants'
    }
    
    return render(request, 'restaurants/featured_restaurants.html', context)


def michelin_starred_restaurants(request):
    """View for Michelin starred restaurants with caching."""
    from django.core.cache import cache
    
    # Try cache first (30 minutes for Michelin restaurants) 
    cache_key = 'michelin_starred_restaurants_data'
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        restaurants = Restaurant.objects.filter(
            is_active=True, 
            michelin_stars__gt=0
        ).select_related().prefetch_related(
            'images', 'chefs', 'menu_sections'
        ).order_by('-michelin_stars', 'name')
        
        # Cache the queryset results for 30 minutes
        cached_data = list(restaurants)
        cache.set(cache_key, cached_data, 1800)
        logger.debug("💾 Cached Michelin starred restaurants data")
    else:
        logger.debug("🎯 Michelin starred restaurants cache HIT")
    
    context = {
        'restaurants': cached_data,
        'title': 'Michelin Starred Restaurants'
    }
    
    return render(request, 'restaurants/michelin_starred.html', context)


def restaurant_search_api(request):
    """Enhanced API endpoint for restaurant search with recommendations and images using UnifiedSearchFilters."""
    # Use UnifiedSearchFilters for standardized parameter handling
    unified_filters = DjangoSearchFilterAdapter.from_request(request)
    
    recommender = RestaurantRecommender()
    
    # Convert UnifiedSearchFilters to legacy format for recommender (temporary compatibility)
    filters = {}
    if unified_filters.cuisine_type:
        filters['cuisine'] = unified_filters.cuisine_type
    if unified_filters.price_range:
        filters['price_range'] = unified_filters.price_range[0] if isinstance(unified_filters.price_range, list) else unified_filters.price_range
    if unified_filters.michelin_stars:
        filters['min_stars'] = unified_filters.michelin_stars[0] if isinstance(unified_filters.michelin_stars, list) else unified_filters.michelin_stars
    
    # Get search results with recommendations
    if unified_filters.query or unified_filters.city or unified_filters.country or filters:
        search_results = recommender.search_restaurants(
            query=unified_filters.query,
            location=unified_filters.city or unified_filters.country,
            filters=filters,
            max_results=unified_filters.limit
        )
    else:
        # Return popular restaurants for empty search
        search_results = recommender._get_popular_restaurants(unified_filters.limit)
    
    # Format results for API response
    results = []
    for result in search_results:
        restaurant = result['restaurant']
        featured_image = result.get('featured_image')
        
        restaurant_data = {
            'id': str(restaurant.id),
            'name': restaurant.name,
            'city': restaurant.city,
            'country': restaurant.country,
            'cuisine_type': restaurant.cuisine_type,
            'michelin_stars': restaurant.michelin_stars,
            'rating': float(restaurant.rating) if restaurant.rating else None,
            'price_range': restaurant.price_range,
            'url': restaurant.get_absolute_url(),
            'description': restaurant.description[:200] + '...' if len(restaurant.description) > 200 else restaurant.description,
            'image_count': result.get('image_count', 0),
            'match_reasons': result.get('match_reasons', []),
            'relevance_score': result.get('relevance_score', result.get('popularity_score', 0))
        }
        
        # Add featured image data
        if featured_image:
            restaurant_data['featured_image'] = featured_image
        
        results.append(restaurant_data)
    
    return JsonResponse({
        'results': results,
        'total_count': len(results),
        'query': query,
        'location': location,
        'filters': filters
    })


def geocode_address(address):
    """Geocode an address using Google Maps API."""
    google_maps_api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
    if not google_maps_api_key:
        return None
    
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            'address': address,
            'key': google_maps_api_key
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if data['status'] == 'OK' and data['results']:
            location = data['results'][0]['geometry']['location']
            return {
                'lat': location['lat'],
                'lng': location['lng'],
                'formatted_address': data['results'][0]['formatted_address']
            }
    except Exception as e:
        log_error(e, ErrorTypes.EXTERNAL_API_ERROR, context={'operation': 'geocoding', 'address': address})
    
    return None


def calculate_distance(lat1, lng1, lat2, lng2):
    """Calculate distance between two points using Haversine formula."""
    R = 6371  # Earth's radius in kilometers
    
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2) * math.sin(dlat/2) + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlng/2) * math.sin(dlng/2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = R * c
    
    return distance


def geographic_search_api(request):
    """Enhanced geographic search with Google Maps integration."""
    address = request.GET.get('address', '')
    query = request.GET.get('q', '')
    max_results = int(request.GET.get('max_results', 10))
    radius_km = float(request.GET.get('radius', 50))  # Default 50km radius
    
    result = {
        'query': query,
        'address': address,
        'results': [],
        'fallback_results': [],
        'message': '',
        'search_type': 'local'
    }
    
    # First try to geocode the address
    geocoded = geocode_address(address) if address else None
    
    if geocoded:
        user_lat = geocoded['lat']
        user_lng = geocoded['lng']
        
        # Find restaurants with coordinates within radius
        restaurants_with_coords = Restaurant.objects.filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False
        ).select_related().prefetch_related(
            'images', 'chefs', 'menu_sections'
        )
        
        nearby_restaurants = []
        for restaurant in restaurants_with_coords:
            distance = calculate_distance(
                user_lat, user_lng,
                float(restaurant.latitude), float(restaurant.longitude)
            )
            if distance <= radius_km:
                nearby_restaurants.append({
                    'restaurant': restaurant,
                    'distance': distance
                })
        
        # Sort by distance
        nearby_restaurants.sort(key=lambda x: x['distance'])
        
        # Apply query filter if provided
        if query:
            filtered_restaurants = []
            query_lower = query.lower()
            for item in nearby_restaurants:
                restaurant = item['restaurant']
                if (query_lower in restaurant.name.lower() or
                    (restaurant.cuisine_type and query_lower in restaurant.cuisine_type.lower()) or
                    query_lower in restaurant.city.lower()):
                    filtered_restaurants.append(item)
            nearby_restaurants = filtered_restaurants
        
        # Format results
        for item in nearby_restaurants[:max_results]:
            restaurant = item['restaurant']
            featured_image = get_restaurant_featured_image(restaurant)
            
            result['results'].append({
                'id': str(restaurant.id),
                'name': restaurant.name,
                'city': restaurant.city,
                'country': restaurant.country,
                'cuisine_type': restaurant.cuisine_type,
                'michelin_stars': restaurant.michelin_stars,
                'rating': float(restaurant.rating) if restaurant.rating else None,
                'price_range': restaurant.price_range,
                'url': restaurant.get_absolute_url(),
                'description': restaurant.description[:200] + '...' if len(restaurant.description) > 200 else restaurant.description,
                'distance_km': round(item['distance'], 1),
                'featured_image': featured_image,
                'image_count': restaurant.images.count(),
            })
        
        if result['results']:
            result['message'] = f"Found {len(result['results'])} restaurant{'s' if len(result['results']) != 1 else ''} within {radius_km}km of {geocoded['formatted_address']}"
        else:
            # Fallback: find nearest Michelin restaurants regardless of query
            michelin_restaurants = []
            for restaurant in restaurants_with_coords.filter(michelin_stars__gt=0):
                distance = calculate_distance(
                    user_lat, user_lng,
                    float(restaurant.latitude), float(restaurant.longitude)
                )
                michelin_restaurants.append({
                    'restaurant': restaurant,
                    'distance': distance
                })
            
            michelin_restaurants.sort(key=lambda x: x['distance'])
            
            # Format fallback results
            for item in michelin_restaurants[:max_results]:
                restaurant = item['restaurant']
                featured_image = get_restaurant_featured_image(restaurant)
                
                result['fallback_results'].append({
                    'id': str(restaurant.id),
                    'name': restaurant.name,
                    'city': restaurant.city,
                    'country': restaurant.country,
                    'cuisine_type': restaurant.cuisine_type,
                    'michelin_stars': restaurant.michelin_stars,
                    'rating': float(restaurant.rating) if restaurant.rating else None,
                    'price_range': restaurant.price_range,
                    'url': restaurant.get_absolute_url(),
                    'description': restaurant.description[:200] + '...' if len(restaurant.description) > 200 else restaurant.description,
                    'distance_km': round(item['distance'], 1),
                    'featured_image': featured_image,
                    'image_count': restaurant.images.count(),
                })
            
            if result['fallback_results']:
                result['message'] = f"No restaurants found matching '{query}' near {geocoded['formatted_address']}. Here are the nearest Michelin-starred restaurants:"
                result['search_type'] = 'fallback_nearest_michelin'
            else:
                result['message'] = f"No restaurants found near {geocoded['formatted_address']}. Try expanding your search area or browse our global collection."
                result['search_type'] = 'no_results'
    
    else:
        # Fallback to text-based location search
        if address:
            result['message'] = f"Could not locate '{address}'. Showing restaurants matching this location name:"
        else:
            result['message'] = "Please enter a location to find nearby restaurants."
        
        # Try to find restaurants by city/country name matching the address
        if address:
            restaurants = Restaurant.objects.filter(
                Q(city__icontains=address) | Q(country__icontains=address),
                is_active=True
            ).select_related().prefetch_related(
                'images', 'chefs', 'menu_sections'
            )
            
            if query:
                restaurants = restaurants.filter(
                    Q(name__icontains=query) |
                    Q(cuisine_type__icontains=query) |
                    Q(description__icontains=query)
                )
            
            # Format results
            for restaurant in restaurants[:max_results]:
                featured_image = get_restaurant_featured_image(restaurant)
                
                result['results'].append({
                    'id': str(restaurant.id),
                    'name': restaurant.name,
                    'city': restaurant.city,
                    'country': restaurant.country,
                    'cuisine_type': restaurant.cuisine_type,
                    'michelin_stars': restaurant.michelin_stars,
                    'rating': float(restaurant.rating) if restaurant.rating else None,
                    'price_range': restaurant.price_range,
                    'url': restaurant.get_absolute_url(),
                    'description': restaurant.description[:200] + '...' if len(restaurant.description) > 200 else restaurant.description,
                    'featured_image': featured_image,
                    'image_count': restaurant.images.count(),
                })
            
            result['search_type'] = 'text_location_match'
    
    return JsonResponse(result)


def get_restaurant_featured_image(restaurant):
    """Helper function to get featured image for a restaurant."""
    image = (
        restaurant.images.filter(is_featured=True).first() or
        restaurant.images.filter(is_menu_highlight=True).first() or
        restaurant.images.filter(is_ambiance_highlight=True).first() or
        restaurant.images.filter(ai_category='scenery_ambiance').first() or
        restaurant.images.first()
    )
    
    if image:
        return {
            'id': str(image.id),
            'url': image.source_url if image.source_url else (image.image.url if image.image else None),
            'caption': image.get_display_name(),
            'category': image.ai_category,
            'labels': image.ai_labels[:3] if image.ai_labels else [],
        }
    return None


def restaurant_stats_api(request):
    """API endpoint for restaurant statistics."""
    stats = {
        'total_restaurants': Restaurant.objects.filter(is_active=True).count(),
        'michelin_starred': Restaurant.objects.filter(is_active=True, michelin_stars__gt=0).count(),
        'countries': Restaurant.objects.filter(is_active=True).values('country').distinct().count(),
        'cities': Restaurant.objects.filter(is_active=True).values('city').distinct().count(),
        'cuisines': Restaurant.objects.filter(is_active=True).values('cuisine_type').distinct().count(),
        'avg_rating': Restaurant.objects.filter(is_active=True).aggregate(Avg('rating'))['rating__avg'] or 0,
    }
    
    return JsonResponse(stats)


@require_http_methods(["GET"])
def restaurant_timezone_status_api(request, restaurant_id):
    """API endpoint to get restaurant's current status in its local timezone."""
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        # Get restaurant's current local time and status
        local_time = restaurant.get_current_local_time()
        open_status = restaurant.is_currently_open()
        
        response_data = {
            'restaurant_name': restaurant.name,
            'location': f"{restaurant.city}, {restaurant.country}",
            'timezone': restaurant.get_timezone_display(),
            'local_time': local_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'local_time_12h': local_time.strftime('%I:%M %p %Z'),
            'is_open': open_status['is_open'],
            'status': open_status['status'],
            'opening_hours': restaurant.opening_hours or 'Not available'
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        # Try to get restaurant for error tracking
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id)
        except:
            restaurant = None
        
        log_error(
            e, 
            ErrorTypes.API_ERROR, 
            context={'operation': 'restaurant_timezone_status', 'restaurant_id': restaurant_id},
            restaurant=restaurant
        )
        return JsonResponse({
            'error': 'Unable to get restaurant status',
            'details': str(e)
        }, status=500)


@require_http_methods(["GET"])
def restaurants_open_now_api(request):
    """API endpoint to get restaurants currently open in their local timezones."""
    try:
        # Get restaurants with timezone info
        restaurants = Restaurant.objects.filter(
            is_active=True,
            timezone_info__isnull=False
        ).exclude(opening_hours='')[:50]  # Limit for performance
        
        open_restaurants = []
        
        for restaurant in restaurants:
            try:
                status = restaurant.is_currently_open()
                if status['is_open'] is True:
                    local_time = restaurant.get_current_local_time()
                    open_restaurants.append({
                        'id': str(restaurant.id),
                        'name': restaurant.name,
                        'location': f"{restaurant.city}, {restaurant.country}",
                        'local_time': local_time.strftime('%H:%M %Z'),
                        'status': status['status'],
                        'michelin_stars': restaurant.michelin_stars,
                        'url': restaurant.get_absolute_url()
                    })
            except Exception as e:
                # Skip restaurants with invalid data but log the issue
                log_warning_with_context(
                    f"Skipping restaurant with invalid data: {str(e)}",
                    context={'restaurant_id': restaurant.id if restaurant else None},
                    restaurant=restaurant
                )
                continue
        
        return JsonResponse({
            'open_restaurants': open_restaurants,
            'count': len(open_restaurants),
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'error': 'Unable to get open restaurants',
            'details': str(e)
        }, status=500)


@csrf_exempt
def restaurant_recommendations_api(request):
    """API endpoint for personalized restaurant recommendations."""
    user = request.user if request.user.is_authenticated else None
    restaurant_id = request.GET.get('restaurant_id', '')
    location = request.GET.get('location', '')
    cuisine = request.GET.get('cuisine', '')
    price_range = request.GET.get('price_range', '')
    max_results = int(request.GET.get('max_results', 6))
    
    recommender = RestaurantRecommender()
    
    # Get enhanced recommendations with collaborative filtering
    if user and user.is_authenticated:
        recommendations = recommender._get_enhanced_personalized_recommendations(
            user=user,
            max_results=max_results,
            location=location if location else None,
            cuisine_preference=cuisine if cuisine else None,
            price_range=price_range if price_range else None
        )
    else:
        # Fallback to original method for anonymous users
        recommendations = recommender.get_recommendations(
            user=user,
            restaurant_id=restaurant_id if restaurant_id else None,
            location=location if location else None,
            cuisine_preference=cuisine if cuisine else None,
            price_range=price_range if price_range else None,
            max_results=max_results
        )
    
    # Format results for API response
    results = []
    for rec in recommendations:
        restaurant = rec['restaurant']
        featured_image = rec.get('featured_image')
        
        recommendation_data = {
            'id': str(restaurant.id),
            'name': restaurant.name,
            'city': restaurant.city,
            'country': restaurant.country,
            'cuisine_type': restaurant.cuisine_type,
            'michelin_stars': restaurant.michelin_stars,
            'rating': float(restaurant.rating) if restaurant.rating else None,
            'price_range': restaurant.price_range,
            'url': restaurant.get_absolute_url(),
            'description': restaurant.description[:150] + '...' if len(restaurant.description) > 150 else restaurant.description,
            'image_count': rec.get('image_count', 0),
            'recommendation_score': rec.get('similarity_score', rec.get('preference_score', rec.get('popularity_score', 0))),
            'reasons': rec.get('similar_features', rec.get('recommendation_reasons', rec.get('recommendation_reasons', [])))
        }
        
        # Add featured image data
        if featured_image:
            recommendation_data['featured_image'] = featured_image
        
        results.append(recommendation_data)
    
    return JsonResponse({
        'recommendations': results,
        'total_count': len(results),
        'recommendation_type': 'similar' if restaurant_id else ('personalized' if user else 'popular'),
        'user_authenticated': bool(user)
    })


def restaurant_images_api(request, restaurant_id):
    """API endpoint for restaurant images by category."""
    try:
        restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
    except Restaurant.DoesNotExist:
        return JsonResponse({'error': 'Restaurant not found'}, status=404)
    
    category = request.GET.get('category', 'all')  # Support all AI categories
    limit = int(request.GET.get('limit', 20))
    
    # Filter images by category (supports all ImageAI service categories)
    images = restaurant.images.all()
    if category != 'all' and category != 'featured':
        # Filter by specific AI category
        images = images.filter(ai_category=category)
    elif category == 'featured':
        images = images.filter(Q(is_featured=True) | Q(is_menu_highlight=True) | Q(is_ambiance_highlight=True))
    
    # Order by confidence and limit results
    images = images.order_by('-category_confidence', '-created_at')[:limit]
    
    # Format image data
    image_data = []
    for image in images:
        image_info = {
            'id': str(image.id),
            'url': image.source_url if image.source_url else (image.image.url if image.image else None),
            'caption': image.get_display_name(),
            'ai_category': image.ai_category,
            'ai_labels': image.ai_labels[:5] if image.ai_labels else [],
            'ai_description': image.ai_description,
            'confidence': image.category_confidence,
            'is_featured': image.is_featured,
            'is_menu_highlight': image.is_menu_highlight,
            'is_ambiance_highlight': image.is_ambiance_highlight,
            'width': image.width,
            'height': image.height
        }
        image_data.append(image_info)
    
    return JsonResponse({
        'restaurant_id': str(restaurant.id),
        'restaurant_name': restaurant.name,
        'images': image_data,
        'category': category,
        'total_count': len(image_data),
        'total_images': restaurant.images.count()
    })


@login_required
def scraping_jobs(request):
    """View for scraping job management."""
    jobs = ScrapingJob.objects.select_related().all().order_by('-created_at')
    
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'jobs': page_obj,
        'title': 'Scraping Jobs'
    }
    
    return render(request, 'restaurants/scraping_jobs.html', context)


@login_required
def scraping_job_detail(request, job_id):
    """View for scraping job details."""
    job = get_object_or_404(ScrapingJob, id=job_id)
    
    context = {
        'job': job,
        'title': f'Scraping Job: {job.job_name}'
    }
    
    return render(request, 'restaurants/scraping_job_detail.html', context)


def gallery_view(request):
    """Gallery view showing restaurants with image carousels, grouped by restaurant."""
    
    # Build base queryset for restaurants with images
    restaurants = Restaurant.objects.filter(
        is_active=True,
        images__isnull=False
    ).select_related().prefetch_related(
        'images', 'chefs', 'menu_sections'
    ).distinct()
    
    # Enhanced filtering with AI labels support  
    category = request.GET.get('category', '')
    if category:
        # Check if it's an AI label or traditional category
        if category in ['scenery_ambiance', 'menu_item', 'uncategorized']:
            restaurants = restaurants.filter(images__ai_category=category)
        else:
            # Filter by AI labels for more granular filtering
            restaurants = restaurants.filter(images__ai_labels__icontains=category)
    
    country = request.GET.get('country', '')
    if country:
        restaurants = restaurants.filter(country=country)
    
    cuisine = request.GET.get('cuisine', '')
    if cuisine:
        restaurants = restaurants.filter(cuisine_type__iexact=cuisine)
    
    # Search with AI labels support
    search_query = request.GET.get('search', '')
    if search_query:
        restaurants = restaurants.filter(
            Q(name__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(images__caption__icontains=search_query) |
            Q(images__ai_category__icontains=search_query) |
            Q(images__ai_labels__icontains=search_query) |
            Q(images__ai_description__icontains=search_query)
        ).distinct()
    
    # Order by restaurants with most images first, then by name
    restaurants = restaurants.annotate(
        image_count=models.Count('images')
    ).order_by('-image_count', 'name')
    
    # Pagination - restaurants per page instead of images
    paginator = Paginator(restaurants, 12)  # 12 restaurants per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate total images for display
    total_images = RestaurantImage.objects.filter(
        restaurant__in=restaurants
    ).count()
    
    # Get improved filter options
    
    # 1. Enhanced Categories: Use top AI labels instead of basic categories
    from collections import Counter
    from itertools import chain
    
    # Get all AI labels and count frequency
    all_labels = RestaurantImage.objects.exclude(ai_labels=[]).values_list('ai_labels', flat=True)
    label_counter = Counter()
    for label_list in all_labels:
        if label_list:  # Ensure it's not empty
            label_counter.update(label_list)
    
    # Get top 15 most common AI labels as categories
    top_ai_labels = [label for label, count in label_counter.most_common(15) if count > 5]
    
    # Add traditional categories as backup
    traditional_categories = ['scenery_ambiance', 'menu_item', 'uncategorized']
    categories = traditional_categories + top_ai_labels
    
    # 2. Clean Countries: Filter out non-countries
    import re
    
    # List of common country name patterns to validate
    valid_country_patterns = [
        r'^[A-Z][a-zA-Z\s]+$',  # Starts with capital, contains only letters and spaces
        r'^[A-Z][a-zA-Z]+(\s[A-Z][a-zA-Z]+)*$'  # Proper country name format
    ]
    
    # Get all countries and clean them
    all_countries = Restaurant.objects.filter(
        is_active=True, 
        images__isnull=False
    ).values_list('country', flat=True).distinct()
    
    # Filter out empty/invalid countries and normalize
    clean_countries = set()  # Use set for automatic deduplication
    for country in all_countries:
        if country and country.strip():  # Not empty
            country = country.strip()
            # Filter out obvious non-countries (contains numbers, too many special chars, etc.)
            if (not re.search(r'\d', country) and  # No numbers
                len(country) > 2 and  # Not too short
                len(country) < 50 and  # Not too long
                not country.startswith('A-') and  # Not postal code
                '-' not in country[:3]):  # Not starting with hyphen prefix
                # Normalize country name: title case
                normalized_country = country.title()
                clean_countries.add(normalized_country)
    
    countries = sorted(list(clean_countries))
    
    # 3. Deduplicated Cuisines: Use set to remove duplicates with case normalization
    cuisine_values = Restaurant.objects.filter(
        is_active=True, 
        images__isnull=False
    ).values_list('cuisine_type', flat=True).distinct().exclude(cuisine_type='')
    
    # Normalize and deduplicate cuisines
    normalized_cuisines = set()
    for cuisine in cuisine_values:
        if cuisine and cuisine.strip():
            # Normalize: title case and strip whitespace
            normalized = cuisine.strip().title()
            normalized_cuisines.add(normalized)
    
    cuisines = sorted(list(normalized_cuisines))
    
    context = {
        'restaurants': page_obj,  # Changed from images to restaurants
        'categories': categories,
        'countries': countries,
        'cuisines': cuisines,
        'current_filters': {
            'category': category,
            'country': country,
            'cuisine': cuisine,
            'search': search_query,
        },
        'total_images': total_images,
        'total_restaurants': restaurants.count(),
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
    }
    
    return render(request, 'restaurants/gallery.html', context)


@require_http_methods(["GET"])
def personalized_recommendations_api(request):
    """Enhanced API endpoint specifically for personalized recommendations with collaborative filtering."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    user = request.user
    max_results = int(request.GET.get('max_results', 10))
    location = request.GET.get('location', '')
    cuisine = request.GET.get('cuisine', '')
    price_range = request.GET.get('price_range', '')
    
    recommender = RestaurantRecommender()
    
    try:
        # Get enhanced personalized recommendations
        recommendations = recommender._get_enhanced_personalized_recommendations(
            user=user,
            max_results=max_results,
            location=location if location else None,
            cuisine_preference=cuisine if cuisine else None,
            price_range=price_range if price_range else None
        )
        
        # Format results with enhanced data
        results = []
        for rec in recommendations:
            restaurant = rec['restaurant']
            
            recommendation_data = {
                'id': str(restaurant.id),
                'name': restaurant.name,
                'city': restaurant.city,
                'country': restaurant.country,
                'cuisine_type': restaurant.cuisine_type,
                'michelin_stars': restaurant.michelin_stars,
                'rating': float(restaurant.rating) if restaurant.rating else None,
                'price_range': restaurant.price_range,
                'url': restaurant.get_absolute_url(),
                'description': restaurant.description[:200] + '...' if len(restaurant.description) > 200 else restaurant.description,
                'image_count': rec.get('image_count', 0),
                'total_score': rec.get('total_score', 0),
                'favorites_score': rec.get('favorites_score', 0),
                'profile_score': rec.get('profile_score', 0),
                'collaborative_score': rec.get('collaborative_score', 0),
                'review_score': rec.get('review_score', 0),
                'popularity_score': rec.get('popularity_score', 0),
                'explanation': rec.get('explanation', ''),
                'similar_users_count': rec.get('similar_users_count', 0),
                'is_favorited': rec.get('is_favorited', False)
            }
            
            # Add featured image if available
            featured_image = rec.get('featured_image')
            if featured_image:
                recommendation_data['featured_image'] = featured_image
            
            results.append(recommendation_data)
        
        # Get user's favorites summary
        from accounts.models import UserFavoriteRestaurant
        user_favorites_count = UserFavoriteRestaurant.objects.filter(user=user).count()
        
        return JsonResponse({
            'recommendations': results,
            'total_count': len(results),
            'user_favorites_count': user_favorites_count,
            'recommendation_type': 'enhanced_personalized',
            'algorithm': 'collaborative_filtering_hybrid',
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'error': 'Unable to generate personalized recommendations',
            'details': str(e)
        }, status=500)


def get_user_location_from_ip(request):
    """
    Get user's approximate location from their IP address using ipapi.co.
    Returns dictionary with latitude, longitude, city, country.
    """
    try:
        # Get user's IP address
        user_ip = request.META.get('HTTP_X_FORWARDED_FOR')
        if user_ip:
            user_ip = user_ip.split(',')[0].strip()
        else:
            user_ip = request.META.get('REMOTE_ADDR')
        
        # Skip localhost and private IPs
        if not user_ip or user_ip in ['127.0.0.1', 'localhost'] or user_ip.startswith('192.168.') or user_ip.startswith('10.'):
            # Default to New York for development/localhost
            return {
                'status': 'default_location',
                'latitude': 40.7128,
                'longitude': -74.0060,
                'city': 'New York',
                'country': 'United States',
                'ip': user_ip or 'localhost'
            }
        
        # Use ipapi.co for geolocation (free, no API key needed)
        import requests
        response = requests.get(f'https://ipapi.co/{user_ip}/json/', timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('latitude') and data.get('longitude'):
                return {
                    'status': 'success',
                    'latitude': float(data.get('latitude')),
                    'longitude': float(data.get('longitude')),
                    'city': data.get('city', 'Unknown'),
                    'country': data.get('country_name', 'Unknown'),
                    'ip': user_ip
                }
        
        # Fallback to New York if geolocation fails
        return {
            'status': 'fallback',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'city': 'New York',
            'country': 'United States',
            'ip': user_ip
        }
        
    except Exception as e:
        logger.warning(f"IP geolocation failed: {str(e)}")
        # Fallback to New York on any error
        return {
            'status': 'error',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'city': 'New York',
            'country': 'United States',
            'ip': 'unknown'
        }


def get_weather_data(lat, lng, restaurant_id=None):
    """
    Get weather data for restaurant location using OpenWeatherMap API with Redis caching.
    Cache results for up to 3 times per day (morning/afternoon/evening).
    """
    import redis
    from datetime import datetime, timezone
    import hashlib
    
    weather_api_key = getattr(settings, 'OPENWEATHER_API_KEY', None)
    if not weather_api_key or weather_api_key.startswith('your-'):
        return {
            'status': 'no_api_key',
            'message': 'Weather API key not configured'
        }
    
    # Connect to Redis for caching
    try:
        redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 1)),  # Use DB 1 for API cache
            password=os.getenv("REDIS_PASSWORD", None),
        )
        
        # Create cache key based on coordinates and time period
        now = datetime.now(timezone.utc)
        hour = now.hour
        
        # Determine time period (morning: 0-11, afternoon: 12-17, evening: 18-23)
        if hour < 12:
            time_period = "morning"
        elif hour < 18:
            time_period = "afternoon"
        else:
            time_period = "evening"
        
        # Create unique cache key
        location_hash = hashlib.md5(f"{lat},{lng}".encode()).hexdigest()[:8]
        cache_key = f"weather:{location_hash}:{now.strftime('%Y-%m-%d')}:{time_period}"
        
        # Try to get cached data first
        cached_data = redis_client.get(cache_key)
        if cached_data:
            import json
            logger.info(f"Weather cache hit for {cache_key}")
            cached_weather = json.loads(cached_data.decode('utf-8'))
            # Mark as cached and update timestamp
            cached_weather['cached'] = True
            cached_weather['cache_hit_timestamp'] = datetime.now().isoformat()
            return cached_weather
        
    except Exception as redis_error:
        logger.warning(f"Redis connection failed for weather cache: {redis_error}")
        redis_client = None
    
    # If no cache or Redis unavailable, fetch from API
    try:
        # Current weather
        current_url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            'lat': lat,
            'lon': lng,
            'appid': weather_api_key,
            'units': 'metric'  # Celsius
        }
        
        logger.info(f"Fetching weather data from OpenWeather API for {lat}, {lng}")
        response = requests.get(current_url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            # Format weather data
            weather_info = {
                'status': 'success',
                'temperature': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'humidity': data['main']['humidity'],
                'description': data['weather'][0]['description'].title(),
                'icon': data['weather'][0]['icon'],
                'wind_speed': data['wind'].get('speed', 0),
                'visibility': data.get('visibility', 0) / 1000,  # Convert to km
                'city_name': data.get('name', 'Unknown'),
                'timestamp': datetime.now().isoformat(),
                'cached': False,
                'cache_period': time_period
            }
            
            # Cache the result for current time period (expires at end of day)
            if redis_client:
                try:
                    # Calculate expiration - end of current day
                    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                    ttl = int((end_of_day - now).total_seconds())
                    
                    import json
                    redis_client.setex(
                        cache_key, 
                        ttl, 
                        json.dumps(weather_info)
                    )
                    logger.info(f"Weather data cached with key {cache_key} for {ttl} seconds")
                except Exception as cache_error:
                    logger.warning(f"Failed to cache weather data: {cache_error}")
            
            return weather_info
        else:
            return {
                'status': 'api_error',
                'message': f'Weather API returned {response.status_code}'
            }
            
    except Exception as e:
        logger.error(f"Weather API error: {str(e)}")
        return {
            'status': 'error',
            'message': 'Failed to fetch weather data'
        }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def restaurant_location_weather_api(request, restaurant_id):
    """
    Get distance and weather information for a restaurant.
    
    Optional JSON payload: {"user_lat": float, "user_lng": float}
    If no coordinates provided, automatically detects user location from IP.
    """
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        # Try to parse user location from request body
        user_lat = None
        user_lng = None
        user_location_info = None
        
        try:
            if request.body:
                data = json.loads(request.body)
                user_lat = data.get('user_lat')
                user_lng = data.get('user_lng')
                
                if user_lat is not None and user_lng is not None:
                    user_lat = float(user_lat)
                    user_lng = float(user_lng)
                    user_location_info = {
                        'status': 'provided',
                        'latitude': user_lat,
                        'longitude': user_lng,
                        'source': 'manual_coordinates'
                    }
        except (json.JSONDecodeError, TypeError, ValueError):
            # If JSON parsing fails, we'll use IP geolocation
            pass
        
        # If no coordinates provided, use IP geolocation
        if user_lat is None or user_lng is None:
            user_location_info = get_user_location_from_ip(request)
            user_lat = user_location_info['latitude']
            user_lng = user_location_info['longitude']
        
        result = {
            'restaurant_id': str(restaurant.id),
            'restaurant_name': restaurant.name,
            'restaurant_location': {
                'city': restaurant.city,
                'country': restaurant.country,
                'address': restaurant.address,
                'latitude': float(restaurant.latitude) if restaurant.latitude else None,
                'longitude': float(restaurant.longitude) if restaurant.longitude else None
            },
            'user_location': user_location_info
        }
        
        # Calculate distance if restaurant has coordinates
        if restaurant.latitude and restaurant.longitude:
            distance_km = calculate_distance(
                user_lat, user_lng,
                float(restaurant.latitude), float(restaurant.longitude)
            )
            
            # Convert to miles for US users (optional)
            distance_miles = distance_km * 0.621371
            
            result['distance'] = {
                'kilometers': round(distance_km, 2),
                'miles': round(distance_miles, 2),
                'status': 'calculated'
            }
            
            # Get weather data for restaurant location (with caching)
            weather_data = get_weather_data(
                float(restaurant.latitude), 
                float(restaurant.longitude),
                restaurant_id=str(restaurant.id)
            )
            result['weather'] = weather_data
            
        else:
            # Try to geocode restaurant address if no coordinates
            if restaurant.address:
                geocode_result = geocode_address(f"{restaurant.address}, {restaurant.city}, {restaurant.country}")
                
                if geocode_result:
                    # Update restaurant coordinates for future use
                    restaurant.latitude = geocode_result['lat']
                    restaurant.longitude = geocode_result['lng']
                    restaurant.save(update_fields=['latitude', 'longitude'])
                    
                    # Calculate distance with new coordinates
                    distance_km = calculate_distance(
                        user_lat, user_lng,
                        geocode_result['lat'], geocode_result['lng']
                    )
                    distance_miles = distance_km * 0.621371
                    
                    result['distance'] = {
                        'kilometers': round(distance_km, 2),
                        'miles': round(distance_miles, 2),
                        'status': 'geocoded'
                    }
                    
                    # Get weather data (with caching)
                    weather_data = get_weather_data(
                        geocode_result['lat'], 
                        geocode_result['lng'],
                        restaurant_id=str(restaurant.id)
                    )
                    result['weather'] = weather_data
                    
                else:
                    result['distance'] = {
                        'status': 'geocoding_failed',
                        'message': 'Could not determine restaurant location'
                    }
                    result['weather'] = {
                        'status': 'no_coordinates',
                        'message': 'Cannot get weather without restaurant coordinates'
                    }
            else:
                result['distance'] = {
                    'status': 'no_address',
                    'message': 'Restaurant has no address information'
                }
                result['weather'] = {
                    'status': 'no_address',
                    'message': 'Cannot get weather without restaurant address'
                }
        
        return JsonResponse(result)
        
    except Exception as e:
        log_error(
            e,
            ErrorTypes.API_ERROR,
            context={'operation': 'restaurant_location_weather', 'restaurant_id': restaurant_id},
            restaurant=restaurant if 'restaurant' in locals() else None
        )
        return JsonResponse({
            'error': 'Failed to get location and weather data'
        }, status=500)


# Cart API Views

@csrf_exempt
@require_http_methods(["GET", "POST"])
def cart_api(request):
    """Main cart API endpoint - GET to view cart, POST with restaurant_id to get/create cart."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    if request.method == 'GET':
        # Get all active carts for user
        carts = UserCart.objects.filter(
            user=request.user, is_active=True
        ).select_related('restaurant').prefetch_related(
            'items__menu_item__section'
        )
        
        cart_data = []
        for cart in carts:
            cart_items = cart.items.select_related(
                'menu_item__section__restaurant'
            ).all()
            items = []
            
            for cart_item in cart_items:
                items.append({
                    'id': str(cart_item.id),
                    'menu_item_id': str(cart_item.menu_item.id),
                    'name': cart_item.menu_item.name,
                    'description': cart_item.menu_item.description,
                    'price': cart_item.menu_item.cleaned_price,
                    'quantity': cart_item.quantity,
                    'subtotal': cart_item.subtotal,
                    'special_requests': cart_item.special_requests
                })
            
            cart_data.append({
                'cart_id': str(cart.id),
                'restaurant_id': str(cart.restaurant.id),
                'restaurant_name': cart.restaurant.name,
                'total_items': cart.total_items,
                'estimated_total': cart.estimated_total,
                'items': items,
                'notes': cart.notes,
                'created_at': cart.created_at.isoformat(),
                'updated_at': cart.updated_at.isoformat()
            })
        
        return JsonResponse({
            'carts': cart_data,
            'total_carts': len(cart_data)
        })
    
    elif request.method == 'POST':
        # Get or create cart for specific restaurant
        try:
            data = json.loads(request.body)
            restaurant_id = data.get('restaurant_id')
            
            if not restaurant_id:
                return JsonResponse({'error': 'restaurant_id required'}, status=400)
            
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
            cart, created = UserCart.objects.get_or_create(
                user=request.user,
                restaurant=restaurant,
                is_active=True,
                defaults={'notes': data.get('notes', '')}
            )
            
            # Return cart with items
            cart_items = cart.items.select_related(
                'menu_item__section__restaurant'
            ).all()
            items = []
            
            for cart_item in cart_items:
                items.append({
                    'id': str(cart_item.id),
                    'menu_item_id': str(cart_item.menu_item.id),
                    'name': cart_item.menu_item.name,
                    'price': cart_item.menu_item.cleaned_price,
                    'quantity': cart_item.quantity,
                    'subtotal': cart_item.subtotal,
                    'special_requests': cart_item.special_requests
                })
            
            return JsonResponse({
                'cart_id': str(cart.id),
                'restaurant_id': str(restaurant.id),
                'restaurant_name': restaurant.name,
                'total_items': cart.total_items,
                'estimated_total': cart.estimated_total,
                'items': items,
                'notes': cart.notes,
                'created': created
            })
            
        except Restaurant.DoesNotExist:
            return JsonResponse({'error': 'Restaurant not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def add_to_cart_api(request):
    """Add item to cart API endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        restaurant_id = data.get('restaurant_id')
        menu_item_id = data.get('menu_item_id')
        quantity = int(data.get('quantity', 1))
        special_requests = data.get('special_requests', '')
        
        if not restaurant_id or not menu_item_id:
            return JsonResponse({'error': 'restaurant_id and menu_item_id required'}, status=400)
        
        if quantity < 1:
            return JsonResponse({'error': 'quantity must be at least 1'}, status=400)
        
        # Get restaurant and menu item
        restaurant = Restaurant.objects.select_related().get(id=restaurant_id, is_active=True)
        menu_item = MenuItem.objects.select_related(
            'section__restaurant'
        ).get(
            id=menu_item_id,
            section__restaurant=restaurant,
            is_available=True,
            is_available_for_cart=True
        )
        
        # Get or create cart
        cart, created = UserCart.objects.get_or_create(
            user=request.user,
            restaurant=restaurant,
            is_active=True,
            defaults={'notes': ''}
        )
        
        # Add or update cart item
        cart_item, item_created = CartItem.objects.get_or_create(
            cart=cart,
            menu_item=menu_item,
            defaults={
                'quantity': quantity,
                'special_requests': special_requests
            }
        )
        
        if not item_created:
            # Update existing item
            cart_item.quantity += quantity
            if special_requests:
                if cart_item.special_requests:
                    cart_item.special_requests += f"; {special_requests}"
                else:
                    cart_item.special_requests = special_requests
            cart_item.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Added {quantity}x {menu_item.name} to cart',
            'cart_item_id': str(cart_item.id),
            'cart_total_items': cart.total_items,
            'cart_estimated_total': cart.estimated_total,
            'item_quantity': cart_item.quantity,
            'item_subtotal': cart_item.subtotal
        })
        
    except Restaurant.DoesNotExist:
        return JsonResponse({'error': 'Restaurant not found'}, status=404)
    except MenuItem.DoesNotExist:
        return JsonResponse({'error': 'Menu item not found or not available'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValueError:
        return JsonResponse({'error': 'Invalid quantity'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def remove_from_cart_api(request):
    """Remove item from cart API endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        cart_item_id = data.get('cart_item_id')
        quantity = data.get('quantity')  # Optional - if not provided, remove all
        
        if not cart_item_id:
            return JsonResponse({'error': 'cart_item_id required'}, status=400)
        
        # Get cart item
        cart_item = CartItem.objects.select_related(
            'cart__restaurant', 'menu_item__section'
        ).get(
            id=cart_item_id,
            cart__user=request.user,
            cart__is_active=True
        )
        
        item_name = cart_item.menu_item.name
        
        if quantity is None or quantity >= cart_item.quantity:
            # Remove item completely
            cart_item.delete()
            message = f'Removed {item_name} from cart'
        else:
            # Reduce quantity
            cart_item.quantity -= quantity
            cart_item.save()
            message = f'Reduced {item_name} quantity by {quantity}'
        
        # Get updated cart totals
        cart = cart_item.cart
        
        return JsonResponse({
            'success': True,
            'message': message,
            'cart_total_items': cart.total_items,
            'cart_estimated_total': cart.estimated_total
        })
        
    except CartItem.DoesNotExist:
        return JsonResponse({'error': 'Cart item not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def update_cart_api(request):
    """Update cart item quantity API endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        cart_item_id = data.get('cart_item_id')
        new_quantity = int(data.get('quantity'))
        special_requests = data.get('special_requests')
        
        if not cart_item_id or new_quantity < 0:
            return JsonResponse({'error': 'cart_item_id and valid quantity required'}, status=400)
        
        # Get cart item
        cart_item = CartItem.objects.select_related(
            'cart__restaurant', 'menu_item__section'
        ).get(
            id=cart_item_id,
            cart__user=request.user,
            cart__is_active=True
        )
        
        item_name = cart_item.menu_item.name
        old_quantity = cart_item.quantity
        
        if new_quantity == 0:
            # Remove item
            cart_item.delete()
            message = f'Removed {item_name} from cart'
        else:
            # Update quantity and special requests
            cart_item.quantity = new_quantity
            if special_requests is not None:
                cart_item.special_requests = special_requests
            cart_item.save()
            message = f'Updated {item_name} quantity from {old_quantity} to {new_quantity}'
        
        # Get updated cart totals
        cart = cart_item.cart
        
        return JsonResponse({
            'success': True,
            'message': message,
            'cart_total_items': cart.total_items,
            'cart_estimated_total': cart.estimated_total,
            'item_subtotal': cart_item.subtotal if new_quantity > 0 else 0
        })
        
    except CartItem.DoesNotExist:
        return JsonResponse({'error': 'Cart item not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValueError:
        return JsonResponse({'error': 'Invalid quantity'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def clear_cart_api(request):
    """Clear cart API endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        restaurant_id = data.get('restaurant_id')
        
        if not restaurant_id:
            return JsonResponse({'error': 'restaurant_id required'}, status=400)
        
        # Get cart
        cart = UserCart.objects.select_related('restaurant').get(
            user=request.user,
            restaurant_id=restaurant_id,
            is_active=True
        )
        
        # Clear all items
        items_count = cart.items.count()
        cart.clear_cart()
        
        return JsonResponse({
            'success': True,
            'message': f'Cleared {items_count} items from cart',
            'cart_total_items': 0,
            'cart_estimated_total': 0.0
        })
        
    except UserCart.DoesNotExist:
        return JsonResponse({'error': 'Cart not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def cart_llm_interaction_api(request):
    """API endpoint for LLM chatbot cart interactions."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')
        restaurant_id = data.get('restaurant_id')
        session_id = data.get('session_id', '')
        
        if not user_message:
            return JsonResponse({'error': 'message required'}, status=400)
        
        # This would integrate with your LangChain cart tools
        # For now, return a basic response
        
        restaurant = None
        if restaurant_id:
            try:
                restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
            except Restaurant.DoesNotExist:
                pass
        
        # Mock LLM response - you would replace this with your actual LangChain tool integration
        response = {
            'bot_response': f"I understand you want to: '{user_message}'. I'm ready to help you with {restaurant.name if restaurant else 'the menu'}! Use the cart tools to add items.",
            'action_taken': 'provide_info',
            'cart_updated': False,
            'items_affected': []
        }
        
        # Log the interaction
        if restaurant_id:
            try:
                cart = UserCart.objects.get(
                    user=request.user,
                    restaurant_id=restaurant_id,
                    is_active=True
                )
                
                ChatCartInteraction.objects.create(
                    user=request.user,
                    cart=cart,
                    user_message=user_message,
                    bot_response=response['bot_response'],
                    action_taken=response['action_taken'],
                    items_affected=response['items_affected'],
                    session_id=session_id
                )
            except UserCart.DoesNotExist:
                pass
        
        return JsonResponse(response)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def unified_search_view(request):
    """
    Unified search page that integrates with the new RAG endpoints.
    Provides semantic search across restaurants, images, menu items, and documents.
    """
    # Get RAG service URL from settings
    rag_service_url = getattr(settings, 'RAG_SERVICE_URL', 'http://localhost:8001')
    
    # Get initial filter options from database
    context = {
        'title': 'Unified Search - AI-Powered Discovery',
        'rag_service_url': rag_service_url,
        'countries': Restaurant.objects.filter(is_active=True).values_list('country', flat=True).distinct().order_by('country'),
        'cities': Restaurant.objects.filter(is_active=True).values_list('city', flat=True).distinct().order_by('city'),
        'cuisines': Restaurant.objects.filter(is_active=True).values_list('cuisine_type', flat=True).distinct().order_by('cuisine_type'),
    }
    
    return render(request, 'restaurants/unified_search.html', context)


def semantic_search_view(request):
    """
    Semantic search page with advanced AI-powered search interface.
    Demonstrates the full capabilities of the semantic search system.
    """
    context = {
        'title': 'Semantic Search - AI-Powered Restaurant Discovery',
        'page_description': 'Experience intelligent restaurant search that understands context, intent, and natural language queries.',
        'search_methods': [
            {
                'id': 'automatic',
                'name': 'Auto-Route',
                'description': 'Intelligent routing based on query analysis',
                'icon': '🤖'
            },
            {
                'id': 'semantic',
                'name': 'Semantic',
                'description': 'AI-powered understanding of meaning and context',
                'icon': '🧠'
            },
            {
                'id': 'hybrid',
                'name': 'Hybrid',
                'description': 'Best of traditional and semantic search',
                'icon': '⚡'
            },
            {
                'id': 'traditional',
                'name': 'Traditional',
                'description': 'Fast keyword-based search',
                'icon': '🔍'
            }
        ],
        'example_queries': [
            'romantic dinner for anniversary',
            'best family friendly restaurants',
            'authentic Italian experience',
            'cozy atmosphere with great wine',
            'business lunch venue',
            'innovative modern cuisine',
            'restaurants with outdoor seating',
            'places for special celebrations'
        ]
    }
    
    return render(request, 'restaurants/semantic_search.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def unified_search_proxy_api(request):
    """
    High-performance proxy API endpoint for unified search with Redis caching.
    Integrates Django data with RAG service using UnifiedSearchFilters.
    """
    try:
        from .cache_integration import get_django_cache
        django_cache = get_django_cache()
        
        # Use UnifiedSearchFilters for standardized parameter handling
        unified_filters = DjangoSearchFilterAdapter.from_request(request)
        
        if not unified_filters.query:
            return JsonResponse({'error': 'Query is required'}, status=400)
        
        # Convert filters to dict for caching and RAG service
        filter_dict = DjangoSearchFilterAdapter.to_dict(unified_filters)
        
        # Try cache first
        cached_results = django_cache.get_cached_search_results(unified_filters.query, filter_dict)
        if cached_results:
            return JsonResponse(cached_results)
        
        # Get RAG service URL
        rag_service_url = getattr(settings, 'RAG_SERVICE_URL', 'http://localhost:8001')
        
        # Forward request to RAG service with unified filters
        try:
            rag_response = requests.post(
                f"{rag_service_url}/unified-search/search",
                json=filter_dict,
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            
            if rag_response.status_code != 200:
                return JsonResponse({
                    'error': 'RAG service error',
                    'details': f'Status: {rag_response.status_code}'
                }, status=502)
            
            rag_data = rag_response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"RAG service connection error: {e}")
            return JsonResponse({
                'error': 'RAG service unavailable',
                'details': 'Could not connect to search service'
            }, status=503)
        
        # Enhance results with Django data using intelligent caching
        enhanced_results = []
        
        for result in rag_data.get('results', []):
            try:
                # Get restaurant context
                restaurant_id = result.get('restaurant_id')
                restaurant_data = None
                
                if restaurant_id:
                    # Try cache first
                    restaurant_data = django_cache.get_cached_restaurant_data(restaurant_id)
                    
                    if restaurant_data is None:
                        try:
                            restaurant = Restaurant.objects.select_related().prefetch_related('images').get(
                                id=restaurant_id, 
                                is_active=True
                            )
                            restaurant_data = {
                                'id': str(restaurant.id),
                                'name': restaurant.name,
                                'slug': restaurant.slug,
                                'city': restaurant.city,
                                'country': restaurant.country,
                                'cuisine_type': restaurant.cuisine_type,
                                'michelin_stars': restaurant.michelin_stars,
                                'rating': float(restaurant.rating) if restaurant.rating else None,
                                'price_range': restaurant.price_range,
                                'url': restaurant.get_absolute_url(),
                                'featured_image': get_restaurant_featured_image(restaurant)
                            }
                            # Cache the restaurant data
                            django_cache.cache_restaurant_data(restaurant_id, restaurant_data)
                        except Restaurant.DoesNotExist:
                            restaurant_data = None
                            django_cache.cache_restaurant_data(restaurant_id, None)
                
                # Enhance result with Django data
                enhanced_result = {
                    **result,
                    'django_restaurant_data': restaurant_data
                }
                
                # Add image URL if this is an image result
                if result.get('content_type') == 'image' and restaurant_data:
                    content_id = result.get('content_id')
                    if content_id:
                        try:
                            image = RestaurantImage.objects.get(id=content_id)
                            enhanced_result['image_url'] = image.source_url if image.source_url else (
                                image.image.url if image.image else None
                            )
                            enhanced_result['thumbnail_url'] = enhanced_result['image_url']  # Could be optimized
                        except RestaurantImage.DoesNotExist:
                            pass
                
                enhanced_results.append(enhanced_result)
                
            except Exception as e:
                logger.error(f"Error enhancing search result: {e}")
                # Include original result even if enhancement fails
                enhanced_results.append(result)
        
        # Create enhanced response
        enhanced_response = {
            **rag_data,
            'results': enhanced_results,
            'enhanced_with_django': True,
            'cache_status': 'miss',
            'performance_metrics': {
                **rag_data.get('performance_metrics', {}),
                'django_enhancement_time': 'calculated_separately',
                'cached': False
            }
        }
        
        # Cache the enhanced response
        django_cache.cache_search_results(query, data, enhanced_response)
        
        return JsonResponse(enhanced_response)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request'}, status=400)
    except Exception as e:
        logger.error(f"Unified search proxy error: {e}")
        return JsonResponse({
            'error': 'Search proxy error',
            'details': str(e)
        }, status=500)


@require_http_methods(["GET"])
def unified_search_suggestions_api(request):
    """
    High-performance API endpoint for unified search suggestions with Redis caching.
    Provides intelligent suggestions based on Django data and user history.
    """
    try:
        from .cache_integration import get_django_cache
        django_cache = get_django_cache()
        
        query = request.GET.get('query', '').strip()
        limit = min(int(request.GET.get('limit', 8)), 20)
        
        if len(query) < 2:
            return JsonResponse({
                'restaurants': [],
                'cuisines': [],
                'locations': [],
                'categories': [],
                'cached': False
            })
        
        # Try cache first
        cached_suggestions = django_cache.get_cached_suggestions(query)
        if cached_suggestions:
            return JsonResponse({
                **cached_suggestions,
                'cached': True
            })
        
        # Generate suggestions
        query_lower = query.lower()
        suggestions = {
            'restaurants': [],
            'cuisines': [],
            'locations': [],
            'categories': []
        }
        
        # Restaurant name suggestions
        restaurants = Restaurant.objects.filter(
            name__icontains=query,
            is_active=True
        ).only('name').values_list('name', flat=True)[:limit]
        suggestions['restaurants'] = list(restaurants)
        
        # Cuisine suggestions
        cuisines = Restaurant.objects.filter(
            cuisine_type__icontains=query,
            is_active=True
        ).only('cuisine_type').values_list('cuisine_type', flat=True).distinct()[:limit]
        suggestions['cuisines'] = list(set(cuisines))  # Remove duplicates
        
        # Location suggestions (cities and countries)
        cities = Restaurant.objects.filter(
            city__icontains=query,
            is_active=True
        ).only('city').values_list('city', flat=True).distinct()[:limit//2]
        
        countries = Restaurant.objects.filter(
            country__icontains=query,
            is_active=True
        ).only('country').values_list('country', flat=True).distinct()[:limit//2]
        
        suggestions['locations'] = list(set(list(cities) + list(countries)))
        
        # AI category suggestions from images
        ai_categories = ['scenery_ambiance', 'menu_item', 'uncategorized']
        matching_categories = [cat for cat in ai_categories if query_lower in cat.lower()]
        suggestions['categories'] = matching_categories
        
        # Add common search terms if relevant
        common_terms = ['michelin star', 'fine dining', 'romantic', 'family friendly', 'outdoor seating']
        matching_terms = [term for term in common_terms if query_lower in term.lower()]
        suggestions['categories'].extend(matching_terms)
        
        # Cache the suggestions
        django_cache.cache_suggestions(query, suggestions)
        
        return JsonResponse({
            **suggestions,
            'cached': False
        })
        
    except Exception as e:
        logger.error(f"Unified search suggestions error: {e}")
        return JsonResponse({
            'error': 'Failed to load suggestions',
            'restaurants': [],
            'cuisines': [],
            'locations': [],
            'categories': []
        })


def semantic_gallery_view(request):
    """
    Advanced image gallery with semantic search and AI categorization.
    Uses unified search for intelligent image discovery.
    """
    # Get RAG service URL from settings
    rag_service_url = getattr(settings, 'RAG_SERVICE_URL', 'http://localhost:8001')
    
    context = {
        'title': 'AI-Powered Image Gallery',
        'rag_service_url': rag_service_url,
    }
    
    return render(request, 'restaurants/semantic_gallery.html', context)


@require_http_methods(["GET"])
def images_by_category_api(request):
    """
    High-performance API endpoint to get restaurant images by AI category with Redis caching.
    Supports semantic filtering and pagination.
    """
    try:
        from .cache_integration import get_django_cache
        django_cache = get_django_cache()
        
        category = request.GET.get('category', 'all')
        limit = min(int(request.GET.get('limit', 24)), 100)
        offset = int(request.GET.get('offset', 0))
        
        # Create cache key from parameters
        cache_key = f"images_category_{category}_{limit}_{offset}"
        
        # Try cache first for frequently accessed categories
        if category in ['all', 'scenery_ambiance', 'menu_item']:
            cached_images = django_cache.get_cached_search_results(cache_key, {
                'category': category,
                'limit': limit,
                'offset': offset,
                'type': 'images_by_category'
            })
            if cached_images:
                return JsonResponse(cached_images)
        
        # Build base queryset
        images = RestaurantImage.objects.select_related('restaurant').filter(
            restaurant__is_active=True
        )
        
        # Apply category filter
        if category != 'all':
            if category in ['scenery_ambiance', 'menu_item', 'uncategorized']:
                images = images.filter(ai_category=category)
            else:
                # Search in AI labels
                images = images.filter(ai_labels__icontains=category)
        
        # Order by confidence and created date
        images = images.order_by('-category_confidence', '-created_at')
        
        # Apply pagination
        total_count = images.count()
        images = images[offset:offset + limit]
        
        # Format image data
        image_data = []
        for image in images:
            image_info = {
                'id': str(image.id),
                'url': image.source_url if image.source_url else (image.image.url if image.image else None),
                'caption': image.get_display_name(),
                'restaurant_name': image.restaurant.name,
                'restaurant_url': image.restaurant.get_absolute_url(),
                'ai_category': image.ai_category,
                'ai_labels': image.ai_labels[:6] if image.ai_labels else [],
                'ai_description': image.ai_description,
                'confidence': image.category_confidence,
                'michelin_stars': image.restaurant.michelin_stars,
                'city': image.restaurant.city,
                'country': image.restaurant.country,
                'is_featured': image.is_featured,
                'width': image.width,
                'height': image.height
            }
            image_data.append(image_info)
        
        response_data = {
            'images': image_data,
            'category': category,
            'total_count': total_count,
            'offset': offset,
            'limit': limit,
            'has_more': offset + len(image_data) < total_count,
            'cached': False
        }
        
        # Cache frequently accessed categories
        if category in ['all', 'scenery_ambiance', 'menu_item']:
            django_cache.cache_search_results(cache_key, {
                'category': category,
                'limit': limit,
                'offset': offset,
                'type': 'images_by_category'
            }, response_data)
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Images by category API error: {e}")
        return JsonResponse({
            'error': 'Failed to load images',
            'images': [],
            'total_count': 0
        }, status=500)


# Cache monitoring and health check endpoints

@require_http_methods(["GET"])
def cache_stats_api(request):
    """
    API endpoint to get comprehensive cache statistics.
    Useful for monitoring and debugging cache performance.
    """
    try:
        from .cache_integration import get_django_cache
        from .signals import get_cache_invalidation_summary
        
        django_cache = get_django_cache()
        
        # Get comprehensive cache stats
        cache_stats = django_cache.get_cache_stats()
        invalidation_summary = get_cache_invalidation_summary()
        
        response_data = {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'cache_stats': cache_stats,
            'invalidation_summary': invalidation_summary,
            'django_integration': {
                'endpoints_with_caching': [
                    'unified_search_proxy_api',
                    'unified_search_suggestions_api', 
                    'images_by_category_api'
                ],
                'signal_handlers_active': True,
                'cache_integration_loaded': True
            }
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Cache stats API error: {e}")
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def cache_invalidate_api(request):
    """
    API endpoint to manually invalidate cache entries.
    Useful for admin operations and debugging.
    """
    try:
        from .cache_integration import get_django_cache
        from .signals import invalidate_all_search_cache
        
        data = json.loads(request.body) if request.body else {}
        invalidation_type = data.get('type', 'all')
        
        django_cache = get_django_cache()
        
        if invalidation_type == 'all':
            # Invalidate all cache
            invalidate_all_search_cache()
            message = "All cache invalidated"
            
        elif invalidation_type == 'search':
            # Invalidate only search cache
            django_cache.cache_manager.invalidate_search_cache()
            message = "Search cache invalidated"
            
        elif invalidation_type == 'restaurant':
            # Invalidate specific restaurant cache
            restaurant_id = data.get('restaurant_id')
            if restaurant_id:
                django_cache.invalidate_restaurant_cache(restaurant_id)
                message = f"Restaurant cache invalidated for ID: {restaurant_id}"
            else:
                return JsonResponse({'error': 'restaurant_id required for restaurant invalidation'}, status=400)
        
        else:
            return JsonResponse({'error': 'Invalid invalidation type'}, status=400)
        
        return JsonResponse({
            'status': 'success',
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request'}, status=400)
    except Exception as e:
        logger.error(f"Cache invalidation API error: {e}")
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }, status=500)


@require_http_methods(["GET"])
def cache_health_api(request):
    """
    API endpoint for cache system health check.
    Returns detailed health information for monitoring.
    """
    try:
        from .cache_integration import get_django_cache
        
        django_cache = get_django_cache()
        
        # Get cache health from UnifiedCacheManager
        cache_health = django_cache.cache_manager.health_check()
        
        # Get cache stats for performance info
        cache_stats = django_cache.get_cache_stats()
        
        # Overall health determination
        overall_status = 'healthy'
        if cache_health.get('status') != 'healthy':
            overall_status = 'degraded'
        
        health_data = {
            'status': overall_status,
            'timestamp': datetime.now().isoformat(),
            'cache_system': cache_health,
            'performance_summary': {
                'hit_rate': cache_stats.get('performance', {}).get('hit_rate_percentage', 0),
                'total_requests': cache_stats.get('performance', {}).get('total_requests', 0),
                'cache_errors': cache_stats.get('performance', {}).get('cache_errors', 0)
            },
            'django_integration': {
                'signal_handlers': 'active',
                'cache_integration': 'loaded',
                'endpoints_cached': ['search', 'suggestions', 'images']
            },
            'recommendations': []
        }
        
        # Add recommendations based on performance
        hit_rate = cache_stats.get('performance', {}).get('hit_rate_percentage', 0)
        if hit_rate < 50:
            health_data['recommendations'].append('Consider adjusting cache TTL settings')
        
        cache_errors = cache_stats.get('performance', {}).get('cache_errors', 0)
        if cache_errors > 10:
            health_data['recommendations'].append('Investigate cache connection issues')
        
        return JsonResponse(health_data)
        
    except Exception as e:
        logger.error(f"Cache health API error: {e}")
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
            'recommendations': ['Check cache service configuration']
        }, status=500)


# =============================================================================
# SEMANTIC SEARCH API ENDPOINTS
# =============================================================================

@csrf_exempt
@require_http_methods(["POST", "GET"])
def semantic_search_api(request):
    """
    Advanced semantic search API with intelligent query routing.
    Uses UnifiedSearchFilters for consistent parameter handling.
    """
    try:
        # Use UnifiedSearchFilters for standardized parameter handling
        unified_filters = DjangoSearchFilterAdapter.from_request(request)
        
        if not unified_filters.query:
            return JsonResponse({'error': 'Query is required'}, status=400)
        
        # Initialize semantic search service
        semantic_service = SemanticSearchService()
        
        # Extract context from unified filters
        context = {
            'location': unified_filters.city or unified_filters.country,
            'user_preferences': {},
            'address': f"{unified_filters.city}, {unified_filters.country}" if unified_filters.city and unified_filters.country else None
        }
        
        # Convert unified filters to semantic search format
        filters = {
            'city': unified_filters.city,
            'country': unified_filters.country,
            'cuisine_type': unified_filters.cuisine_type,
            'michelin_stars': unified_filters.michelin_stars[0] if unified_filters.michelin_stars else None,
            'price_range': unified_filters.price_range[0] if unified_filters.price_range else None,
            'rating_min': unified_filters.rating_min,
            'rating_max': unified_filters.rating_max
        }
        
        # Handle search method from unified filters
        force_method = None
        if hasattr(unified_filters, 'search_method'):
            method_map = {
                'semantic': SearchMethod.SEMANTIC,
                'traditional': SearchMethod.TRADITIONAL,
                'hybrid': SearchMethod.HYBRID
            }
            force_method = method_map.get(unified_filters.search_method)
        
        # Perform semantic search
        results = semantic_service.search_restaurants(
            query=unified_filters.query,
            context=context,
            filters=filters,
            limit=unified_filters.limit,
            force_method=force_method
        )
        
        # Convert restaurant objects to dictionaries for JSON response
        serialized_results = []
        for restaurant in results.get('results', []):
            restaurant_data = {
                'id': str(restaurant.id),
                'name': restaurant.name,
                'slug': restaurant.slug,
                'city': restaurant.city,
                'country': restaurant.country,
                'cuisine_type': restaurant.cuisine_type,
                'michelin_stars': restaurant.michelin_stars,
                'rating': float(restaurant.rating) if restaurant.rating else None,
                'price_range': restaurant.price_range,
                'description': restaurant.description,
                'url': restaurant.get_absolute_url(),
                'featured_image': get_restaurant_featured_image(restaurant)
            }
            serialized_results.append(restaurant_data)
        
        # Add semantic scoring if available
        if 'semantic_results' in results:
            for i, semantic_result in enumerate(results['semantic_results']):
                if i < len(serialized_results):
                    serialized_results[i].update({
                        'relevance_score': semantic_result.relevance_score,
                        'semantic_score': semantic_result.semantic_score,
                        'traditional_score': semantic_result.traditional_score,
                        'explanation': semantic_result.explanation,
                        'matched_features': semantic_result.matched_features
                    })
        
        # Create enhanced response
        response_data = {
            **results,
            'results': serialized_results,
            'api_version': 'semantic_v1',
            'enhanced_scoring': 'semantic_results' in results
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Semantic search API error: {e}")
        return JsonResponse({
            'error': 'Semantic search failed',
            'details': str(e),
            'fallback_available': True
        }, status=500)


@require_http_methods(["GET"])
def semantic_search_intent_api(request):
    """
    Analyze search query intent and recommend optimal search method.
    Provides insights into query complexity and routing decisions.
    """
    try:
        query = request.GET.get('query', '').strip()
        if not query:
            return JsonResponse({'error': 'Query is required'}, status=400)
        
        # Extract context
        context = {
            'location': request.GET.get('location'),
            'address': request.GET.get('address'),
            'user_type': request.GET.get('user_type', 'anonymous')
        }
        
        # Analyze query intent
        intent = QueryAnalyzer.analyze_query(query, context)
        
        # Convert to serializable format
        intent_data = {
            'original_query': intent.original_query,
            'intent_type': intent.intent_type,
            'entities': intent.entities,
            'sentiment': intent.sentiment,
            'complexity_score': intent.complexity_score,
            'recommended_method': intent.recommended_method.value,
            'analysis_confidence': 'high' if intent.complexity_score > 0.7 else 'medium' if intent.complexity_score > 0.3 else 'low',
            'routing_explanation': f"Query classified as {intent.intent_type} with {intent.complexity_score:.1%} complexity"
        }
        
        return JsonResponse({
            'intent_analysis': intent_data,
            'api_version': 'intent_v1',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Semantic intent analysis error: {e}")
        return JsonResponse({
            'error': 'Intent analysis failed',
            'details': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def hybrid_search_api(request):
    """
    Hybrid search API combining traditional and semantic approaches.
    Provides the best of both search methodologies.
    """
    try:
        data = json.loads(request.body) if request.body else {}
        query = data.get('query', '').strip()
        
        if not query:
            return JsonResponse({'error': 'Query is required'}, status=400)
        
        # Initialize semantic search service
        semantic_service = SemanticSearchService()
        
        # Extract parameters
        context = {
            'location': data.get('location'),
            'user_preferences': data.get('user_preferences', {}),
            'search_history': data.get('search_history', [])
        }
        
        filters = {k: v for k, v in data.items() if v is not None and k not in ['query', 'context', 'limit']}
        limit = int(data.get('limit', 20))
        
        # Force hybrid search method
        results = semantic_service.search_restaurants(
            query=query,
            context=context,
            filters=filters,
            limit=limit,
            force_method=SearchMethod.HYBRID
        )
        
        # Convert restaurant objects to dictionaries
        serialized_results = []
        for restaurant in results.get('results', []):
            restaurant_data = {
                'id': str(restaurant.id),
                'name': restaurant.name,
                'slug': restaurant.slug,
                'city': restaurant.city,
                'country': restaurant.country,
                'cuisine_type': restaurant.cuisine_type,
                'michelin_stars': restaurant.michelin_stars,
                'rating': float(restaurant.rating) if restaurant.rating else None,
                'price_range': restaurant.price_range,
                'description': restaurant.description,
                'url': restaurant.get_absolute_url(),
                'featured_image': get_restaurant_featured_image(restaurant)
            }
            serialized_results.append(restaurant_data)
        
        # Create response with hybrid scoring information
        response_data = {
            **results,
            'results': serialized_results,
            'search_method': 'hybrid',
            'api_version': 'hybrid_v1',
            'scoring_explanation': 'Results combine traditional search relevance with semantic understanding'
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Hybrid search API error: {e}")
        return JsonResponse({
            'error': 'Hybrid search failed',
            'details': str(e),
            'fallback_to_traditional': True
        }, status=500)


@require_http_methods(["GET"])
def semantic_search_methods_api(request):
    """
    Get available semantic search methods and their descriptions.
    Useful for frontend method selection and documentation.
    """
    try:
        methods = {
            SearchMethod.TRADITIONAL.value: {
                'name': 'Traditional Search',
                'description': 'Fast keyword-based search with PostgreSQL full-text search',
                'best_for': ['Simple queries', 'Exact matches', 'Fast results'],
                'performance': 'High speed, low latency'
            },
            SearchMethod.SEMANTIC.value: {
                'name': 'Semantic Search',
                'description': 'AI-powered semantic understanding using RAG service',
                'best_for': ['Complex queries', 'Conceptual search', 'Experience-based queries'],
                'performance': 'Moderate speed, high relevance'
            },
            SearchMethod.HYBRID.value: {
                'name': 'Hybrid Search',
                'description': 'Combines traditional and semantic search with intelligent weighting',
                'best_for': ['Most queries', 'Balanced performance', 'High accuracy'],
                'performance': 'Balanced speed and relevance'
            },
            SearchMethod.GEOGRAPHIC.value: {
                'name': 'Geographic Search',
                'description': 'Location-aware search with semantic enhancement',
                'best_for': ['Location queries', 'Near me searches', 'Geographic filtering'],
                'performance': 'Location-optimized results'
            }
        }
        
        return JsonResponse({
            'search_methods': methods,
            'default_method': 'automatic_routing',
            'api_version': 'methods_v1',
            'routing_info': {
                'automatic': 'System automatically selects best method based on query analysis',
                'manual': 'Force specific method using force_method parameter'
            }
        })
        
    except Exception as e:
        logger.error(f"Search methods API error: {e}")
        return JsonResponse({
            'error': 'Failed to get search methods',
            'details': str(e)
        }, status=500)