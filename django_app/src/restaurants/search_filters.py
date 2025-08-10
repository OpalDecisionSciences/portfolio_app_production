"""
Django integration module for UnifiedSearchFilters.
Provides utilities to convert between Django QuerySets and UnifiedSearchFilters.
Supports hybrid semantic search and unified filtering across all search types.
"""
from typing import Optional, List, Dict, Any, Tuple
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
import logging

# Import UnifiedSearchFilters from shared module
from search.unified_filters import UnifiedSearchFilters

logger = logging.getLogger(__name__)


class DjangoSearchFilterAdapter:
    """
    Adapter class to integrate UnifiedSearchFilters with Django ORM.
    Provides methods to convert filters to Django QuerySets.
    Supports both traditional filtering and semantic search capabilities.
    """
    
    @staticmethod
    def from_request(request: HttpRequest) -> UnifiedSearchFilters:
        """
        Create UnifiedSearchFilters from Django HttpRequest.
        Extracts parameters from GET or POST data.
        """
        # Handle both GET and POST requests
        if request.method == 'POST':
            import json
            try:
                data = json.loads(request.body) if request.body else {}
            except json.JSONDecodeError:
                data = {}
        else:
            data = dict(request.GET.items())
        
        # Extract and convert parameters
        filters = UnifiedSearchFilters(
            # Restaurant identifiers
            restaurant_id=data.get('restaurant_id'),
            restaurant_name=data.get('restaurant_name'),
            restaurant_slug=data.get('restaurant_slug'),
            
            # Geographic filters
            country=data.get('country'),
            city=data.get('city'),
            latitude=float(data.get('latitude')) if data.get('latitude') else None,
            longitude=float(data.get('longitude')) if data.get('longitude') else None,
            radius_km=float(data.get('radius_km')) if data.get('radius_km') else None,
            
            # Cuisine & Quality filters
            cuisine_type=data.get('cuisine_type') or data.get('cuisine'),
            cuisine_types=data.get('cuisine_types', '').split(',') if data.get('cuisine_types') else None,
            michelin_stars=_parse_int_list(data.get('michelin_stars') or data.get('min_stars')),
            price_range=data.get('price_range', '').split(',') if data.get('price_range') else None,
            rating_min=float(data.get('rating_min')) if data.get('rating_min') else None,
            rating_max=float(data.get('rating_max')) if data.get('rating_max') else None,
            
            # Image filters
            ai_category=data.get('ai_category'),
            ai_categories=data.get('ai_categories', '').split(',') if data.get('ai_categories') else None,
            image_labels=data.get('image_labels', '').split(',') if data.get('image_labels') else None,
            is_featured=_parse_bool(data.get('is_featured')),
            is_menu_highlight=_parse_bool(data.get('is_menu_highlight')),
            is_ambiance_highlight=_parse_bool(data.get('is_ambiance_highlight')),
            
            # Search parameters
            query=data.get('query') or data.get('q', ''),
            limit=int(data.get('limit', 20)),
            offset=int(data.get('offset', 0)),
            sort_by=data.get('sort_by', 'relevance'),
            sort_order=data.get('sort_order', 'desc'),
            
            # Semantic search parameters
            search_method=data.get('search_method', 'hybrid'),  # hybrid, semantic, traditional
            semantic_weight=float(data.get('semantic_weight', 0.7)) if data.get('semantic_weight') else 0.7,
            include_embeddings=_parse_bool(data.get('include_embeddings')),
            
            # Content types
            content_types=data.get('content_types', '').split(',') if data.get('content_types') else None,
        )
        
        return filters
    
    @staticmethod
    def apply_to_restaurant_queryset(queryset: QuerySet, filters: UnifiedSearchFilters, 
                                    use_semantic: bool = False) -> QuerySet:
        """
        Apply UnifiedSearchFilters to a Restaurant QuerySet.
        Supports both traditional and semantic search.
        Returns filtered QuerySet.
        """
        # Apply text search (traditional or semantic based on method)
        if filters.query:
            search_method = getattr(filters, 'search_method', 'traditional')
            
            if use_semantic and search_method in ['semantic', 'hybrid']:
                # Use PostgreSQL full-text search for semantic-like behavior
                search_vector = SearchVector('name', weight='A') + \
                              SearchVector('description', weight='B') + \
                              SearchVector('cuisine_type', weight='B') + \
                              SearchVector('city', 'country', weight='C')
                
                search_query = SearchQuery(filters.query)
                
                queryset = queryset.annotate(
                    search_rank=SearchRank(search_vector, search_query)
                )
                
                # For hybrid search, combine with traditional filters
                if search_method == 'hybrid':
                    traditional_q = Q(name__icontains=filters.query) | \
                                  Q(description__icontains=filters.query) | \
                                  Q(cuisine_type__icontains=filters.query)
                    
                    # Apply hybrid search with weighting
                    semantic_weight = getattr(filters, 'semantic_weight', 0.7)
                    if semantic_weight > 0.5:
                        # Prefer semantic results
                        queryset = queryset.filter(
                            Q(search_rank__gt=0.1) | traditional_q
                        )
                    else:
                        # Prefer traditional results
                        queryset = queryset.filter(traditional_q).annotate(
                            search_rank=SearchRank(search_vector, search_query)
                        )
                
                # Order by search rank for semantic results
                queryset = queryset.order_by('-search_rank')
            else:
                # Traditional keyword search
                queryset = queryset.filter(
                    Q(name__icontains=filters.query) |
                    Q(description__icontains=filters.query) |
                    Q(cuisine_type__icontains=filters.query) |
                    Q(city__icontains=filters.query) |
                    Q(country__icontains=filters.query)
                )
        
        # Apply restaurant filters
        if filters.restaurant_id:
            queryset = queryset.filter(id=filters.restaurant_id)
        
        if filters.restaurant_name:
            queryset = queryset.filter(name__icontains=filters.restaurant_name)
        
        if filters.restaurant_slug:
            queryset = queryset.filter(slug=filters.restaurant_slug)
        
        # Apply geographic filters
        if filters.country:
            queryset = queryset.filter(country__iexact=filters.country)
        
        if filters.city:
            queryset = queryset.filter(city__iexact=filters.city)
        
        # Apply cuisine filters
        if filters.cuisine_type:
            queryset = queryset.filter(cuisine_type__iexact=filters.cuisine_type)
        
        if filters.cuisine_types:
            cuisine_q = Q()
            for cuisine in filters.cuisine_types:
                cuisine_q |= Q(cuisine_type__iexact=cuisine)
            queryset = queryset.filter(cuisine_q)
        
        # Apply quality filters
        if filters.michelin_stars:
            if isinstance(filters.michelin_stars, list):
                queryset = queryset.filter(michelin_stars__in=filters.michelin_stars)
            else:
                queryset = queryset.filter(michelin_stars__gte=filters.michelin_stars)
        
        if filters.price_range:
            if isinstance(filters.price_range, list):
                queryset = queryset.filter(price_range__in=filters.price_range)
            else:
                queryset = queryset.filter(price_range=filters.price_range)
        
        if filters.rating_min is not None:
            queryset = queryset.filter(rating__gte=filters.rating_min)
        
        if filters.rating_max is not None:
            queryset = queryset.filter(rating__lte=filters.rating_max)
        
        # Apply geographic distance filter if coordinates provided
        if filters.latitude and filters.longitude and filters.radius_km:
            # Use Haversine formula for distance calculation
            from django.db.models import F
            from django.db.models.functions import ACos, Cos, Radians, Sin
            
            lat = filters.latitude
            lon = filters.longitude
            radius = filters.radius_km
            
            # Earth radius in km
            earth_radius = 6371
            
            queryset = queryset.annotate(
                distance=earth_radius * ACos(
                    Cos(Radians(lat)) * Cos(Radians(F('latitude'))) *
                    Cos(Radians(F('longitude')) - Radians(lon)) +
                    Sin(Radians(lat)) * Sin(Radians(F('latitude')))
                )
            ).filter(distance__lte=radius)
        
        # Apply sorting (if not already sorted by search rank)
        if not (filters.query and use_semantic):
            if filters.sort_by == 'rating':
                order_field = '-rating' if filters.sort_order == 'desc' else 'rating'
            elif filters.sort_by == 'alphabetical':
                order_field = '-name' if filters.sort_order == 'desc' else 'name'
            elif filters.sort_by == 'date':
                order_field = '-created_at' if filters.sort_order == 'desc' else 'created_at'
            elif filters.sort_by == 'distance' and filters.latitude and filters.longitude:
                order_field = 'distance' if filters.sort_order == 'asc' else '-distance'
            else:  # Default to relevance (rating for now)
                order_field = '-rating'
            
            queryset = queryset.order_by(order_field)
        
        return queryset
    
    @staticmethod
    def apply_to_image_queryset(queryset: QuerySet, filters: UnifiedSearchFilters) -> QuerySet:
        """
        Apply UnifiedSearchFilters to a RestaurantImage QuerySet.
        Returns filtered QuerySet.
        """
        # Apply restaurant filters first
        if filters.restaurant_id:
            queryset = queryset.filter(restaurant_id=filters.restaurant_id)
        
        # Apply AI category filters
        if filters.ai_category:
            queryset = queryset.filter(ai_category=filters.ai_category)
        
        if filters.ai_categories:
            queryset = queryset.filter(ai_category__in=filters.ai_categories)
        
        # Apply label filters
        if filters.image_labels:
            label_q = Q()
            for label in filters.image_labels:
                label_q |= Q(ai_labels__icontains=label)
            queryset = queryset.filter(label_q)
        
        # Apply featured filter
        if filters.is_featured is not None:
            queryset = queryset.filter(is_featured=filters.is_featured)
        
        # Apply highlight filters
        if getattr(filters, 'is_menu_highlight', None) is not None:
            queryset = queryset.filter(is_menu_highlight=filters.is_menu_highlight)
        
        if getattr(filters, 'is_ambiance_highlight', None) is not None:
            queryset = queryset.filter(is_ambiance_highlight=filters.is_ambiance_highlight)
        
        # Apply confidence filter
        if hasattr(filters, 'confidence_min') and filters.confidence_min:
            queryset = queryset.filter(category_confidence__gte=filters.confidence_min)
        
        # Apply sorting
        if filters.sort_by == 'date':
            order_field = '-created_at' if filters.sort_order == 'desc' else 'created_at'
        else:
            order_field = '-category_confidence'
        
        queryset = queryset.order_by(order_field)
        
        return queryset
    
    @staticmethod
    def apply_to_menu_item_queryset(queryset: QuerySet, filters: UnifiedSearchFilters) -> QuerySet:
        """
        Apply UnifiedSearchFilters to a MenuItem QuerySet.
        Returns filtered QuerySet.
        """
        # Apply text search
        if filters.query:
            queryset = queryset.filter(
                Q(name__icontains=filters.query) |
                Q(description__icontains=filters.query) |
                Q(category__icontains=filters.query)
            )
        
        # Apply restaurant filter
        if filters.restaurant_id:
            queryset = queryset.filter(restaurant_id=filters.restaurant_id)
        
        # Apply price filters
        if filters.price_range:
            # Convert price range symbols to actual price ranges
            price_ranges = {
                '$': (0, 20),
                '$$': (20, 50),
                '$$$': (50, 100),
                '$$$$': (100, None)
            }
            
            price_q = Q()
            for range_symbol in filters.price_range:
                if range_symbol in price_ranges:
                    min_price, max_price = price_ranges[range_symbol]
                    if max_price:
                        price_q |= Q(price__gte=min_price, price__lt=max_price)
                    else:
                        price_q |= Q(price__gte=min_price)
            
            if price_q:
                queryset = queryset.filter(price_q)
        
        # Apply sorting
        if filters.sort_by == 'alphabetical':
            order_field = 'name' if filters.sort_order == 'asc' else '-name'
        elif filters.sort_by == 'price':
            order_field = 'price' if filters.sort_order == 'asc' else '-price'
        else:
            order_field = 'name'  # Default to name ordering (consistent with MenuItem.Meta.ordering)
        
        queryset = queryset.order_by(order_field)
        
        return queryset
    
    @staticmethod
    def to_dict(filters: UnifiedSearchFilters) -> Dict[str, Any]:
        """
        Convert UnifiedSearchFilters to dictionary for JSON serialization.
        Includes all parameters for hybrid semantic search.
        """
        return {
            'query': filters.query,
            'restaurant_id': filters.restaurant_id,
            'restaurant_name': filters.restaurant_name,
            'country': filters.country,
            'city': filters.city,
            'latitude': filters.latitude,
            'longitude': filters.longitude,
            'radius_km': filters.radius_km,
            'cuisine_type': filters.cuisine_type,
            'cuisine_types': filters.cuisine_types,
            'michelin_stars': filters.michelin_stars,
            'price_range': filters.price_range,
            'rating_min': filters.rating_min,
            'rating_max': filters.rating_max,
            'ai_category': filters.ai_category,
            'ai_categories': filters.ai_categories,
            'image_labels': filters.image_labels,
            'is_featured': filters.is_featured,
            'is_menu_highlight': getattr(filters, 'is_menu_highlight', None),
            'is_ambiance_highlight': getattr(filters, 'is_ambiance_highlight', None),
            'limit': filters.limit,
            'offset': filters.offset,
            'sort_by': filters.sort_by,
            'sort_order': filters.sort_order,
            'content_types': filters.content_types,
            'search_method': getattr(filters, 'search_method', 'traditional'),
            'semantic_weight': getattr(filters, 'semantic_weight', 0.7),
            'include_embeddings': getattr(filters, 'include_embeddings', False),
        }
    
    @staticmethod
    def paginate_queryset(queryset: QuerySet, filters: UnifiedSearchFilters) -> Tuple[QuerySet, int]:
        """
        Apply pagination to queryset based on filters.
        Returns paginated queryset and total count.
        """
        total_count = queryset.count()
        
        # Apply pagination
        if filters.offset:
            queryset = queryset[filters.offset:]
        
        if filters.limit:
            queryset = queryset[:filters.limit]
        
        return queryset, total_count


def _parse_int_list(value: Any) -> Optional[List[int]]:
    """Parse integer or comma-separated list of integers."""
    if not value:
        return None
    
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value if v]
    
    if isinstance(value, int):
        return [value]
    
    if isinstance(value, str):
        if ',' in value:
            return [int(v.strip()) for v in value.split(',') if v.strip()]
        try:
            return [int(value)]
        except ValueError:
            return None
    
    return None


def _parse_bool(value: Any) -> Optional[bool]:
    """Parse boolean from various input types."""
    if value is None:
        return None
    
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    
    return bool(value)