"""
Restaurant Recommendation System

This module provides content-based and collaborative filtering recommendations
for restaurants based on various features like cuisine, location, price, and ratings.
"""

import math
import unicodedata
import numpy as np
from typing import List, Dict, Tuple, Optional, Set
from django.db.models import Q, Count, Avg, F, Case, When, Value, IntegerField
from django.core.cache import cache
from django.conf import settings
from django.contrib.auth import get_user_model
from .models import Restaurant, RestaurantReview, RestaurantImage

# Import favorites model - need to use string reference to avoid circular imports
def get_user_favorite_model():
    from accounts.models import UserFavoriteRestaurant
    return UserFavoriteRestaurant

User = get_user_model()


class RestaurantRecommender:
    """
    Main recommendation engine for restaurants.
    Combines content-based and collaborative filtering approaches.
    """
    
    def __init__(self):
        self.cache_timeout = 3600  # 1 hour cache
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text by removing accents and converting to lowercase."""
        if not text:
            return ""
        # Remove accents and normalize unicode
        normalized = unicodedata.normalize('NFD', text)
        ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
        return ascii_text.lower().strip()
    
    def get_recommendations(self, 
                          user: Optional[User] = None,
                          restaurant_id: Optional[str] = None,
                          location: Optional[str] = None,
                          cuisine_preference: Optional[str] = None,
                          price_range: Optional[str] = None,
                          max_results: int = 10) -> List[Dict]:
        """
        Get personalized restaurant recommendations.
        
        Args:
            user: User for personalized recommendations
            restaurant_id: Restaurant ID for similar restaurants
            location: Location preference (city or country)
            cuisine_preference: Cuisine type preference
            price_range: Price range preference
            max_results: Maximum number of results to return
            
        Returns:
            List of recommended restaurants with scores and reasons
        """
        cache_key = f"recommendations_{user.id if user else 'anon'}_{restaurant_id}_{location}_{cuisine_preference}_{price_range}_{max_results}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        # Optimized base queryset to prevent N+1 queries in templates
        # Prefetch images with select_related for better performance
        from django.db.models import Prefetch
        restaurants = Restaurant.objects.filter(is_active=True).select_related().prefetch_related(
            Prefetch('images', queryset=RestaurantImage.objects.select_related())
        )
        
        if restaurant_id:
            # Similar restaurant recommendations
            recommendations = self._get_similar_restaurants(restaurant_id, max_results)
        elif user:
            # Enhanced personalized recommendations using favorites, reviews, and preferences
            recommendations = self._get_enhanced_personalized_recommendations(user, location, cuisine_preference, price_range, max_results)
        else:
            # Content-based recommendations for anonymous users
            recommendations = self._get_content_based_recommendations(location, cuisine_preference, price_range, max_results)
        
        # Add image data to recommendations
        for rec in recommendations:
            rec['featured_image'] = self._get_featured_image(rec['restaurant'])
            rec['image_count'] = rec['restaurant'].images.count()
        
        cache.set(cache_key, recommendations, self.cache_timeout)
        return recommendations
    
    def search_restaurants(self, 
                         query: str, 
                         location: Optional[str] = None,
                         filters: Optional[Dict] = None,
                         max_results: int = 20) -> List[Dict]:
        """
        Search restaurants with intelligent ranking and recommendations.
        
        Args:
            query: Search query
            location: Location filter
            filters: Additional filters (cuisine, price, stars)
            max_results: Maximum results to return
            
        Returns:
            List of restaurants with relevance scores and images
        """
        if not query and not location and not filters:
            # Return popular restaurants for empty search
            return self._get_popular_restaurants(max_results)
        
        # Build search queryset
        restaurants = Restaurant.objects.filter(is_active=True)
        
        # Text search with accent-insensitive matching
        if query:
            # For better accent-insensitive search, we'll do Python-level filtering
            # on a reasonable subset of restaurants, then apply proper scoring
            normalized_query = self._normalize_text(query)
            
            # Get all restaurants and filter in Python for accent-insensitive search
            all_restaurants = list(restaurants.all())
            matching_restaurants = []
            
            for restaurant in all_restaurants:
                # Check if query matches any field (with accent normalization)
                name_match = (query.lower() in restaurant.name.lower() or 
                             normalized_query in self._normalize_text(restaurant.name))
                city_match = (query.lower() in restaurant.city.lower() or 
                             normalized_query in self._normalize_text(restaurant.city))
                country_match = (query.lower() in restaurant.country.lower() or 
                                normalized_query in self._normalize_text(restaurant.country))
                cuisine_match = (restaurant.cuisine_type and 
                               (query.lower() in restaurant.cuisine_type.lower() or 
                                normalized_query in self._normalize_text(restaurant.cuisine_type)))
                description_match = (restaurant.description and 
                                   (query.lower() in restaurant.description.lower() or 
                                    normalized_query in self._normalize_text(restaurant.description)))
                
                if name_match or city_match or country_match or cuisine_match or description_match:
                    matching_restaurants.append(restaurant)
            
            # Convert back to queryset using IDs
            if matching_restaurants:
                matching_ids = [r.id for r in matching_restaurants]
                restaurants = restaurants.filter(id__in=matching_ids)
            else:
                # No matches found, return empty queryset
                restaurants = restaurants.none()
        
        # Apply filters
        if location:
            restaurants = restaurants.filter(
                Q(city__icontains=location) | Q(country__icontains=location)
            )
        
        if filters:
            if filters.get('cuisine'):
                restaurants = restaurants.filter(cuisine_type__icontains=filters['cuisine'])
            if filters.get('price_range'):
                restaurants = restaurants.filter(price_range=filters['price_range'])
            if filters.get('min_stars'):
                restaurants = restaurants.filter(michelin_stars__gte=filters['min_stars'])
            if filters.get('min_rating'):
                restaurants = restaurants.filter(rating__gte=filters['min_rating'])
        
        # Calculate relevance scores and rank results
        results = []
        for restaurant in restaurants.select_related().prefetch_related('images')[:max_results * 2]:
            score = self._calculate_search_relevance(restaurant, query, location)
            
            results.append({
                'restaurant': restaurant,
                'relevance_score': score,
                'featured_image': self._get_featured_image(restaurant),
                'image_count': restaurant.images.count(),
                'match_reasons': self._get_match_reasons(restaurant, query, location, filters)
            })
        
        # Sort by relevance and return top results
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:max_results]
    
    def _get_similar_restaurants(self, restaurant_id: str, max_results: int) -> List[Dict]:
        """Find restaurants similar to the given restaurant."""
        try:
            target_restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return []
        
        # Get all other restaurants with optimized prefetching to prevent N+1 queries
        from django.db.models import Prefetch
        candidates = Restaurant.objects.filter(
            is_active=True
        ).exclude(id=restaurant_id).select_related().prefetch_related(
            Prefetch('images', queryset=RestaurantImage.objects.select_related())
        )
        
        similarities = []
        for candidate in candidates:
            similarity_score = self._calculate_restaurant_similarity(target_restaurant, candidate)
            if similarity_score > 0.1:  # Minimum similarity threshold
                similarities.append({
                    'restaurant': candidate,
                    'similarity_score': similarity_score,
                    'similar_features': self._get_similarity_reasons(target_restaurant, candidate)
                })
        
        # Sort by similarity and return top results
        similarities.sort(key=lambda x: x['similarity_score'], reverse=True)
        return similarities[:max_results]
    
    def _get_personalized_recommendations(self, user: User, location: str, cuisine: str, price_range: str, max_results: int) -> List[Dict]:
        """Get personalized recommendations based on user's review history."""
        # Get user's reviewed restaurants and preferences
        user_reviews = RestaurantReview.objects.filter(user=user, is_approved=True)
        
        if not user_reviews.exists():
            # Fallback to content-based for new users
            return self._get_content_based_recommendations(location, cuisine, price_range, max_results)
        
        # Analyze user preferences
        preferences = self._analyze_user_preferences(user_reviews)
        
        # Find restaurants matching user preferences
        candidates = Restaurant.objects.filter(is_active=True).exclude(
            id__in=user_reviews.values_list('restaurant_id', flat=True)
        ).select_related().prefetch_related('images')
        
        # Apply preference filters - GLOBAL-AWARE: Include regional field (state/province/region) for worldwide coverage
        if location:
            candidates = candidates.filter(
                Q(city__icontains=location) | 
                Q(state__icontains=location) |  # Covers states/provinces/regions/counties globally
                Q(country__icontains=location)
            )
        if cuisine:
            candidates = candidates.filter(cuisine_type__icontains=cuisine)
        if price_range:
            candidates = candidates.filter(price_range=price_range)
        
        recommendations = []
        for candidate in candidates:
            score = self._calculate_user_preference_score(candidate, preferences)
            if score > 0.3:  # Minimum preference threshold
                recommendations.append({
                    'restaurant': candidate,
                    'preference_score': score,
                    'recommendation_reasons': self._get_preference_reasons(candidate, preferences)
                })
        
        # Sort by preference score
        recommendations.sort(key=lambda x: x['preference_score'], reverse=True)
        return recommendations[:max_results]
    
    def _get_enhanced_personalized_recommendations(self, user: User, location: str, cuisine: str, price_range: str, max_results: int) -> List[Dict]:
        """
        Enhanced personalized recommendations using favorites, reviews, profile preferences, and collaborative filtering.
        """
        UserFavoriteRestaurant = get_user_favorite_model()
        
        # Get user's data sources
        user_reviews = RestaurantReview.objects.filter(user=user, is_approved=True)
        user_favorites = UserFavoriteRestaurant.objects.filter(user=user).select_related('restaurant')
        
        # Get restaurants to exclude (already favorited or reviewed)
        excluded_ids = set()
        if user_favorites.exists():
            excluded_ids.update(user_favorites.values_list('restaurant_id', flat=True))
        if user_reviews.exists():
            excluded_ids.update(user_reviews.values_list('restaurant_id', flat=True))
        
        # Use user profile preferences if available
        user_cuisines = getattr(user, 'preferred_cuisines', []) or []
        user_dietary = getattr(user, 'dietary_restrictions', []) or []
        user_price_pref = getattr(user, 'price_range_preference', None)
        user_location = getattr(user, 'location', None)
        
        # Start with all active restaurants - OPTIMIZED: Proper database query optimization
        candidates = Restaurant.objects.filter(is_active=True).exclude(
            id__in=excluded_ids
        ).select_related(
            'created_by', 'deactivated_by'  # Foreign keys that may be accessed in scoring
        ).prefetch_related(
            'images', 'chefs', 'reviews__user', 'menu_sections__items'  # Related objects to avoid N+1
        )
        
        # Apply location filters (prefer user's location if not specified)
        location_filter = location or user_location
        if location_filter:
            # CRITICAL FIX: Enhanced location filtering with state field and intelligent parsing
            location_parts = [part.strip() for part in location_filter.split(',')]
            location_q = Q()
            for part in location_parts:
                if part:
                    location_q |= (
                        Q(city__icontains=part) | 
                        Q(state__icontains=part) | 
                        Q(country__icontains=part)
                    )
            if location_q:
                candidates = candidates.filter(location_q)
        
        # Apply cuisine filter
        if cuisine:
            candidates = candidates.filter(cuisine_type__icontains=cuisine)
        
        # Apply price range filter (prefer user's preference if not specified)
        price_filter = price_range or user_price_pref
        if price_filter and price_filter != 'any':
            candidates = candidates.filter(price_range=price_filter)
        
        recommendations = []
        
        # CRITICAL FIX: Pre-calculate expensive operations OUTSIDE the loop to fix N+1 queries
        user_preferences = self._analyze_user_preferences(user_reviews) if user_reviews.exists() else {}
        similar_users = self._find_similar_users(user)
        collab_recommendations = self._get_collaborative_recommendations(user, similar_users) if similar_users else {}
        
        for candidate in candidates:
            # Calculate multiple scores using pre-calculated data
            scores = {
                'favorites_score': self._calculate_favorites_similarity_score(user_favorites, candidate),
                'profile_score': self._calculate_profile_match_score(user, candidate),
                'review_score': self._calculate_user_preference_score(candidate, user_preferences),  # Now uses pre-calculated preferences
                'collaborative_score': collab_recommendations.get(candidate.id, 0),
                'popularity_score': self._calculate_popularity_score(candidate) * 0.3,  # Lower weight for popularity
            }
            
            # Calculate weighted final score
            final_score = (
                scores['favorites_score'] * 0.35 +      # High weight for favorites similarity
                scores['profile_score'] * 0.25 +        # Profile preferences
                scores['review_score'] * 0.20 +         # Review history
                scores['collaborative_score'] * 0.15 +  # Collaborative filtering
                scores['popularity_score'] * 0.05       # Popularity boost
            )
            
            # Only include if score meets threshold
            if final_score > 0.25:
                recommendation_reasons = []
                
                # Build explanation reasons
                if scores['favorites_score'] > 0.3:
                    recommendation_reasons.extend(self._get_favorites_reasons(user_favorites, candidate))
                if scores['profile_score'] > 0.3:
                    recommendation_reasons.extend(self._get_profile_match_reasons(user, candidate))
                if scores['review_score'] > 0.3:
                    recommendation_reasons.extend(self._get_preference_reasons(candidate, self._analyze_user_preferences(user_reviews)))
                if scores['collaborative_score'] > 0.2:
                    recommendation_reasons.append("Users with similar tastes also liked this restaurant")
                
                recommendations.append({
                    'restaurant': candidate,
                    'final_score': final_score,
                    'score_breakdown': scores,
                    'recommendation_reasons': recommendation_reasons[:3],  # Limit to top 3 reasons
                    'recommendation_type': 'enhanced_personalized'
                })
        
        # If no personalized recommendations found, fall back to content-based
        if not recommendations and (user_cuisines or location_filter or price_filter):
            fallback_recs = self._get_content_based_recommendations(location_filter, cuisine or (user_cuisines[0] if user_cuisines else None), price_filter, max_results)
            for rec in fallback_recs:
                rec['recommendation_type'] = 'content_based_fallback'
            return fallback_recs
        
        # Sort by final score
        recommendations.sort(key=lambda x: x['final_score'], reverse=True)
        return recommendations[:max_results]
    
    def _get_content_based_recommendations(self, location: str, cuisine: str, price_range: str, max_results: int) -> List[Dict]:
        """Get content-based recommendations for anonymous users."""
        restaurants = Restaurant.objects.filter(is_active=True).select_related().prefetch_related('images')
        
        # Apply filters - GLOBAL-AWARE: Include regional subdivisions
        if location:
            restaurants = restaurants.filter(
                Q(city__icontains=location) | 
                Q(state__icontains=location) |  # Regional subdivisions (state/province/region/county)
                Q(country__icontains=location)
            )
        if cuisine:
            restaurants = restaurants.filter(cuisine_type__icontains=cuisine)
        if price_range:
            restaurants = restaurants.filter(price_range=price_range)
        
        # Score restaurants based on popularity and quality
        recommendations = []
        for restaurant in restaurants:
            score = self._calculate_popularity_score(restaurant)
            recommendations.append({
                'restaurant': restaurant,
                'popularity_score': score,
                'recommendation_reasons': self._get_popularity_reasons(restaurant)
            })
        
        # Sort by popularity score
        recommendations.sort(key=lambda x: x['popularity_score'], reverse=True)
        return recommendations[:max_results]
    
    def _get_popular_restaurants(self, max_results: int) -> List[Dict]:
        """Get popular restaurants for empty searches."""
        restaurants = Restaurant.objects.filter(
            is_active=True
        ).annotate(
            review_count=Count('reviews'),
            avg_rating=Avg('reviews__rating')
        ).order_by('-michelin_stars', '-avg_rating', '-review_count').select_related().prefetch_related('images')
        
        results = []
        for restaurant in restaurants[:max_results]:
            results.append({
                'restaurant': restaurant,
                'popularity_score': self._calculate_popularity_score(restaurant),
                'featured_image': self._get_featured_image(restaurant),
                'image_count': restaurant.images.count(),
                'match_reasons': ['Popular restaurant', 'Highly rated']
            })
        
        return results
    
    def _calculate_restaurant_similarity(self, restaurant1: Restaurant, restaurant2: Restaurant) -> float:
        """Calculate similarity score between two restaurants."""
        score = 0.0
        
        # Cuisine similarity (40% weight)
        if restaurant1.cuisine_type and restaurant2.cuisine_type:
            if restaurant1.cuisine_type.lower() == restaurant2.cuisine_type.lower():
                score += 0.4
            elif any(word in restaurant2.cuisine_type.lower() for word in restaurant1.cuisine_type.lower().split()):
                score += 0.2
        
        # Location similarity (25% weight)
        if restaurant1.city == restaurant2.city:
            score += 0.15
        if restaurant1.country == restaurant2.country:
            score += 0.1
        
        # Price range similarity (20% weight)
        if restaurant1.price_range and restaurant2.price_range:
            if restaurant1.price_range == restaurant2.price_range:
                score += 0.2
            elif abs(len(restaurant1.price_range) - len(restaurant2.price_range)) <= 1:
                score += 0.1
        
        # Michelin stars similarity (15% weight)
        if restaurant1.michelin_stars and restaurant2.michelin_stars:
            star_diff = abs(restaurant1.michelin_stars - restaurant2.michelin_stars)
            if star_diff == 0:
                score += 0.15
            elif star_diff == 1:
                score += 0.1
            elif star_diff == 2:
                score += 0.05
        
        return min(score, 1.0)
    
    def _calculate_search_relevance(self, restaurant: Restaurant, query: str, location: str) -> float:
        """Calculate search relevance score for a restaurant."""
        score = 0.0
        query_lower = query.lower() if query else ""
        location_lower = location.lower() if location else ""
        
        # Normalize for accent-insensitive comparison
        query_normalized = self._normalize_text(query) if query else ""
        restaurant_name_normalized = self._normalize_text(restaurant.name)
        
        # Exact name match gets highest score (check both original and normalized)
        if query:
            if restaurant.name.lower() == query_lower:
                score += 1.0  # Perfect exact match
            elif restaurant_name_normalized == query_normalized:
                score += 0.98  # Accent-insensitive exact match (e.g., "epicure" = "Épicure") - raised priority
            elif query_lower in restaurant.name.lower():
                score += 0.8  # Substring match with original case
            elif query_normalized in restaurant_name_normalized:
                score += 0.75  # Accent-insensitive substring match
        
        # Location relevance (with accent normalization)
        if location:
            location_normalized = self._normalize_text(location)
            city_normalized = self._normalize_text(restaurant.city)
            country_normalized = self._normalize_text(restaurant.country)
            
            if restaurant.city.lower() == location_lower or city_normalized == location_normalized:
                score += 0.6
            elif location_lower in restaurant.city.lower() or location_normalized in city_normalized:
                score += 0.4
            elif restaurant.country.lower() == location_lower or country_normalized == location_normalized:
                score += 0.3
        
        # Cuisine relevance (with accent normalization)
        if query and restaurant.cuisine_type:
            cuisine_normalized = self._normalize_text(restaurant.cuisine_type)
            if query_lower in restaurant.cuisine_type.lower() or query_normalized in cuisine_normalized:
                score += 0.5
        
        # Quality boosters
        if restaurant.michelin_stars:
            score += restaurant.michelin_stars * 0.1
        
        if restaurant.rating:
            score += (float(restaurant.rating) / 5.0) * 0.2
        
        return min(score, 2.0)  # Cap at 2.0 for sorting
    
    def _calculate_popularity_score(self, restaurant: Restaurant) -> float:
        """Calculate popularity score based on ratings, reviews, and Michelin stars."""
        score = 0.0
        
        # Michelin stars (50% weight)
        if restaurant.michelin_stars:
            score += restaurant.michelin_stars * 0.2  # Max 0.6 for 3 stars
        
        # Rating (30% weight)
        if restaurant.rating:
            score += (float(restaurant.rating) / 5.0) * 0.3
        
        # Review count (20% weight)
        if restaurant.review_count:
            # Logarithmic scale for review count
            score += min(math.log(restaurant.review_count + 1) / 5.0, 0.2)
        
        return score
    
    def _get_featured_image(self, restaurant: Restaurant) -> Optional[Dict]:
        """Get the best featured image for a restaurant."""
        # Priority order: featured -> menu highlight -> ambiance highlight -> any image
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
    
    def _analyze_user_preferences(self, user_reviews) -> Dict:
        """Analyze user preferences from their review history."""
        preferences = {
            'cuisines': {},
            'price_ranges': {},
            'locations': {},
            'avg_rating_given': 0,
            'michelin_preference': 0
        }
        
        total_reviews = user_reviews.count()
        high_rated_reviews = user_reviews.filter(rating__gte=4)
        
        # Analyze cuisine preferences
        for review in high_rated_reviews:
            restaurant = review.restaurant
            cuisine = restaurant.cuisine_type
            if cuisine:
                preferences['cuisines'][cuisine] = preferences['cuisines'].get(cuisine, 0) + 1
        
        # Analyze price preferences
        for review in high_rated_reviews:
            price_range = review.restaurant.price_range
            if price_range:
                preferences['price_ranges'][price_range] = preferences['price_ranges'].get(price_range, 0) + 1
        
        # Analyze location preferences
        for review in high_rated_reviews:
            city = review.restaurant.city
            if city:
                preferences['locations'][city] = preferences['locations'].get(city, 0) + 1
        
        # Calculate averages
        preferences['avg_rating_given'] = user_reviews.aggregate(Avg('rating'))['rating__avg'] or 0
        preferences['michelin_preference'] = high_rated_reviews.filter(restaurant__michelin_stars__gt=0).count() / max(total_reviews, 1)
        
        return preferences
    
    def _calculate_user_preference_score(self, restaurant: Restaurant, preferences: Dict) -> float:
        """Calculate how well a restaurant matches user preferences."""
        score = 0.0
        
        # Cuisine preference (40% weight)
        if restaurant.cuisine_type and restaurant.cuisine_type in preferences['cuisines']:
            cuisine_score = preferences['cuisines'][restaurant.cuisine_type] / sum(preferences['cuisines'].values())
            score += cuisine_score * 0.4
        
        # Price preference (20% weight)
        if restaurant.price_range and restaurant.price_range in preferences['price_ranges']:
            price_score = preferences['price_ranges'][restaurant.price_range] / sum(preferences['price_ranges'].values())
            score += price_score * 0.2
        
        # Location preference (20% weight)
        if restaurant.city and restaurant.city in preferences['locations']:
            location_score = preferences['locations'][restaurant.city] / sum(preferences['locations'].values())
            score += location_score * 0.2
        
        # Michelin preference (20% weight)
        if restaurant.michelin_stars > 0 and preferences['michelin_preference'] > 0.5:
            score += 0.2
        elif restaurant.michelin_stars == 0 and preferences['michelin_preference'] < 0.3:
            score += 0.1
        
        return min(score, 1.0)
    
    def _get_match_reasons(self, restaurant: Restaurant, query: str, location: str, filters: Dict) -> List[str]:
        """Get reasons why a restaurant matches the search."""
        reasons = []
        
        if query:
            if query.lower() in restaurant.name.lower():
                reasons.append(f"Name matches '{query}'")
            if restaurant.cuisine_type and query.lower() in restaurant.cuisine_type.lower():
                reasons.append(f"Cuisine matches '{query}'")
        
        if location:
            if location.lower() in restaurant.city.lower():
                reasons.append(f"Located in {restaurant.city}")
        
        if restaurant.michelin_stars > 0:
            reasons.append(f"{restaurant.michelin_stars} Michelin star{'s' if restaurant.michelin_stars > 1 else ''}")
        
        if restaurant.rating and restaurant.rating >= 4.0:
            reasons.append(f"Highly rated ({restaurant.rating:.1f}/5)")
        
        return reasons
    
    def _get_similarity_reasons(self, restaurant1: Restaurant, restaurant2: Restaurant) -> List[str]:
        """Get reasons why two restaurants are similar."""
        reasons = []
        
        if restaurant1.cuisine_type == restaurant2.cuisine_type:
            reasons.append(f"Same cuisine ({restaurant1.cuisine_type})")
        
        if restaurant1.city == restaurant2.city:
            reasons.append(f"Same city ({restaurant1.city})")
        
        if restaurant1.price_range == restaurant2.price_range:
            reasons.append(f"Similar price range ({restaurant1.price_range})")
        
        if restaurant1.michelin_stars == restaurant2.michelin_stars and restaurant1.michelin_stars > 0:
            reasons.append(f"Both have {restaurant1.michelin_stars} Michelin star{'s' if restaurant1.michelin_stars > 1 else ''}")
        
        return reasons
    
    def _get_preference_reasons(self, restaurant: Restaurant, preferences: Dict) -> List[str]:
        """Get reasons why a restaurant matches user preferences."""
        reasons = []
        
        if restaurant.cuisine_type in preferences['cuisines']:
            reasons.append(f"You like {restaurant.cuisine_type} cuisine")
        
        if restaurant.price_range in preferences['price_ranges']:
            reasons.append(f"Matches your price preference ({restaurant.price_range})")
        
        if restaurant.city in preferences['locations']:
            reasons.append(f"You've enjoyed restaurants in {restaurant.city}")
        
        if restaurant.michelin_stars > 0 and preferences['michelin_preference'] > 0.5:
            reasons.append("You prefer Michelin-starred restaurants")
        
        return reasons
    
    def _get_popularity_reasons(self, restaurant: Restaurant) -> List[str]:
        """Get reasons why a restaurant is popular."""
        reasons = []
        
        if restaurant.michelin_stars > 0:
            reasons.append(f"{restaurant.michelin_stars} Michelin star{'s' if restaurant.michelin_stars > 1 else ''}")
        
        if restaurant.rating and restaurant.rating >= 4.0:
            reasons.append(f"Highly rated ({restaurant.rating:.1f}/5)")
        
        if restaurant.review_count and restaurant.review_count >= 10:
            reasons.append(f"Popular ({restaurant.review_count} reviews)")
        
        if restaurant.is_featured:
            reasons.append("Featured restaurant")
        
        return reasons
    
    # Enhanced recommendation helper methods
    
    def _find_similar_users(self, user: User) -> List[User]:
        """
        Find users with similar preferences using collaborative filtering.
        Based on favorites and reviews similarity.
        """
        UserFavoriteRestaurant = get_user_favorite_model()
        
        # Get current user's favorites and reviews
        user_favorites = set(UserFavoriteRestaurant.objects.filter(user=user).values_list('restaurant_id', flat=True))
        user_reviews = set(RestaurantReview.objects.filter(user=user, is_approved=True).values_list('restaurant_id', flat=True))
        user_restaurants = user_favorites.union(user_reviews)
        
        if not user_restaurants:
            return []
        
        # Find users who have interacted with similar restaurants
        similar_users = []
        other_users = User.objects.exclude(id=user.id).filter(
            Q(favorite_restaurants__restaurant__in=user_restaurants) |
            Q(restaurantreview__restaurant__in=user_restaurants, restaurantreview__is_approved=True)
        ).distinct()
        
        for other_user in other_users:
            other_favorites = set(UserFavoriteRestaurant.objects.filter(user=other_user).values_list('restaurant_id', flat=True))
            other_reviews = set(RestaurantReview.objects.filter(user=other_user, is_approved=True).values_list('restaurant_id', flat=True))
            other_restaurants = other_favorites.union(other_reviews)
            
            # Calculate Jaccard similarity
            intersection = len(user_restaurants.intersection(other_restaurants))
            union = len(user_restaurants.union(other_restaurants))
            
            if union > 0:
                similarity = intersection / union
                if similarity >= 0.15:  # Minimum similarity threshold
                    similar_users.append((other_user, similarity))
        
        # Sort by similarity and return top 10
        similar_users.sort(key=lambda x: x[1], reverse=True)
        return [user for user, similarity in similar_users[:10]]
    
    def _get_collaborative_recommendations(self, user: User, similar_users: List[User]) -> Dict[str, float]:
        """
        Get restaurant recommendations based on what similar users liked.
        """
        if not similar_users:
            return {}
        
        UserFavoriteRestaurant = get_user_favorite_model()
        
        # Get current user's restaurants to exclude
        user_favorites = set(UserFavoriteRestaurant.objects.filter(user=user).values_list('restaurant_id', flat=True))
        user_reviews = set(RestaurantReview.objects.filter(user=user, is_approved=True).values_list('restaurant_id', flat=True))
        user_restaurants = user_favorites.union(user_reviews)
        
        restaurant_scores = {}
        
        for similar_user in similar_users:
            # Get their favorites (higher weight) and positive reviews
            favorites = UserFavoriteRestaurant.objects.filter(user=similar_user).exclude(restaurant_id__in=user_restaurants)
            positive_reviews = RestaurantReview.objects.filter(
                user=similar_user, 
                is_approved=True, 
                rating__gte=4
            ).exclude(restaurant_id__in=user_restaurants)
            
            # Add scores for favorites (weight: 1.0)
            for favorite in favorites:
                restaurant_id = str(favorite.restaurant_id)
                if restaurant_id not in restaurant_scores:
                    restaurant_scores[restaurant_id] = 0
                
                # Weight by favorite category
                category_weights = {
                    'visited': 1.0,
                    'to_visit': 0.7,
                    'special_occasion': 0.9,
                    'business_dining': 0.8,
                    'romantic': 0.8,
                    'family': 0.7,
                    'quick_bite': 0.6,
                }
                weight = category_weights.get(favorite.category, 0.7)
                restaurant_scores[restaurant_id] += weight
            
            # Add scores for positive reviews (weight: 0.7)
            for review in positive_reviews:
                restaurant_id = str(review.restaurant_id)
                if restaurant_id not in restaurant_scores:
                    restaurant_scores[restaurant_id] = 0
                
                # Weight by rating
                rating_weight = (review.rating - 3) / 2  # Scale 4-5 stars to 0.5-1.0
                restaurant_scores[restaurant_id] += rating_weight * 0.7
        
        # Normalize scores by number of similar users
        max_score = max(restaurant_scores.values()) if restaurant_scores else 1
        for restaurant_id in restaurant_scores:
            restaurant_scores[restaurant_id] = min(restaurant_scores[restaurant_id] / max_score, 1.0)
        
        return restaurant_scores
    
    def _calculate_favorites_similarity_score(self, user_favorites, candidate_restaurant: Restaurant) -> float:
        """
        Calculate how similar a candidate restaurant is to user's favorites.
        Uses content-based similarity with favorite restaurants.
        """
        if not user_favorites.exists():
            return 0.0
        
        similarity_scores = []
        
        for favorite in user_favorites:
            favorite_restaurant = favorite.restaurant
            similarity = self._calculate_restaurant_similarity(favorite_restaurant, candidate_restaurant)
            
            # Weight by favorite category and personal rating
            category_weights = {
                'visited': 1.0,
                'to_visit': 0.8,
                'special_occasion': 0.9,
                'business_dining': 0.7,
                'romantic': 0.8,
                'family': 0.7,
                'quick_bite': 0.6,
            }
            category_weight = category_weights.get(favorite.category, 0.7)
            
            # Weight by personal rating if available
            rating_weight = 1.0
            if favorite.personal_rating:
                rating_weight = favorite.personal_rating / 5.0
            
            weighted_similarity = similarity * category_weight * rating_weight
            similarity_scores.append(weighted_similarity)
        
        # Return average similarity
        return sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0.0
    
    def _calculate_profile_match_score(self, user: User, restaurant: Restaurant) -> float:
        """
        Calculate how well a restaurant matches user's profile preferences.
        """
        score = 0.0
        
        # Cuisine preferences (40% weight)
        user_cuisines = getattr(user, 'preferred_cuisines', []) or []
        if user_cuisines and restaurant.cuisine_type:
            cuisine_match = any(cuisine.lower() in restaurant.cuisine_type.lower() for cuisine in user_cuisines)
            if cuisine_match:
                score += 0.4
        
        # Price range preference (25% weight)
        user_price_pref = getattr(user, 'price_range_preference', None)
        if user_price_pref and user_price_pref != 'any' and restaurant.price_range:
            if user_price_pref == restaurant.price_range:
                score += 0.25
        
        # Location preference (20% weight)
        user_location = getattr(user, 'location', None)
        if user_location and restaurant.city:
            location_parts = user_location.lower().split(',')
            restaurant_location = f"{restaurant.city}, {restaurant.country}".lower()
            if any(part.strip() in restaurant_location for part in location_parts):
                score += 0.20
        
        # Dietary restrictions compatibility (15% weight)
        user_dietary = getattr(user, 'dietary_restrictions', []) or []
        if user_dietary:
            # This would need restaurant dietary info to be fully implemented
            # For now, give small boost to vegetarian-friendly cuisines for vegan/vegetarian users
            vegetarian_friendly = ['vegetarian', 'vegan', 'indian', 'mediterranean', 'thai']
            if any(restriction in ['vegetarian', 'vegan'] for restriction in user_dietary):
                if restaurant.cuisine_type and any(cuisine in restaurant.cuisine_type.lower() for cuisine in vegetarian_friendly):
                    score += 0.10
        
        return min(score, 1.0)
    
    def _get_favorites_reasons(self, user_favorites, candidate_restaurant: Restaurant) -> List[str]:
        """
        Generate explanation for why a restaurant is recommended based on favorites.
        """
        reasons = []
        
        for favorite in user_favorites:
            similarity = self._calculate_restaurant_similarity(favorite.restaurant, candidate_restaurant)
            if similarity > 0.5:
                if favorite.restaurant.cuisine_type == candidate_restaurant.cuisine_type:
                    reasons.append(f"Similar to your favorite {favorite.restaurant.cuisine_type} restaurant: {favorite.restaurant.name}")
                elif favorite.restaurant.city == candidate_restaurant.city:
                    reasons.append(f"In the same city as your favorite: {favorite.restaurant.name}")
                elif favorite.restaurant.price_range == candidate_restaurant.price_range:
                    reasons.append(f"Similar price range to your favorite: {favorite.restaurant.name}")
                
                if len(reasons) >= 2:  # Limit to avoid too many reasons
                    break
        
        return reasons
    
    def _get_profile_match_reasons(self, user: User, restaurant: Restaurant) -> List[str]:
        """
        Generate explanation for profile-based recommendations.
        """
        reasons = []
        
        # Check cuisine preferences
        user_cuisines = getattr(user, 'preferred_cuisines', []) or []
        if user_cuisines and restaurant.cuisine_type:
            matching_cuisines = [cuisine for cuisine in user_cuisines if cuisine.lower() in restaurant.cuisine_type.lower()]
            if matching_cuisines:
                reasons.append(f"Matches your preference for {matching_cuisines[0]} cuisine")
        
        # Check price range
        user_price_pref = getattr(user, 'price_range_preference', None)
        if user_price_pref and user_price_pref != 'any' and restaurant.price_range == user_price_pref:
            price_labels = {
                'budget': 'budget-friendly',
                'moderate': 'moderately priced',
                'upscale': 'upscale',
                'luxury': 'luxury'
            }
            reasons.append(f"Fits your {price_labels.get(user_price_pref, user_price_pref)} preference")
        
        # Check location
        user_location = getattr(user, 'location', None)
        if user_location and restaurant.city:
            if user_location.lower() in f"{restaurant.city}, {restaurant.country}".lower():
                reasons.append(f"Located in your area ({restaurant.city})")
        
        return reasons