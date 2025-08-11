"""
Optimized spatial views using GeoDjango for location-based queries.
Replaces manual Haversine calculations with PostGIS spatial queries.
"""

from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D  # Distance object for queries
from django.db.models import F, Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_page
from restaurants.models import Restaurant
import logging

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
@cache_page(60 * 5)  # Cache for 5 minutes
def find_nearby_restaurants(request):
    """
    Find restaurants within a specified radius using PostGIS spatial queries.
    Much more efficient than manual Haversine calculations.
    
    Query params:
    - lat: User's latitude
    - lng: User's longitude  
    - radius: Search radius in km (default: 50)
    - limit: Max results (default: 20)
    """
    try:
        # Get parameters
        user_lat = float(request.GET.get('lat'))
        user_lng = float(request.GET.get('lng'))
        radius_km = float(request.GET.get('radius', 50))
        limit = int(request.GET.get('limit', 20))
        
        # Create user location point
        user_location = Point(user_lng, user_lat, srid=4326)
        
        # Use PostGIS spatial query - MUCH faster than Haversine
        nearby_restaurants = Restaurant.objects.filter(
            geolocation__isnull=False,
            is_active=True
        ).filter(
            geolocation__distance_lte=(user_location, D(km=radius_km))
        ).annotate(
            distance_km=Distance('geolocation', user_location)
        ).order_by('distance_km')[:limit]
        
        # Format results
        results = []
        for restaurant in nearby_restaurants:
            results.append({
                'id': str(restaurant.id),
                'name': restaurant.name,
                'cuisine': restaurant.cuisine_type,
                'city': restaurant.city,
                'country': restaurant.country,
                'michelin_stars': restaurant.michelin_stars,
                'rating': float(restaurant.rating) if restaurant.rating else None,
                'distance_km': round(restaurant.distance_km.km, 2),
                'latitude': float(restaurant.latitude) if restaurant.latitude else None,
                'longitude': float(restaurant.longitude) if restaurant.longitude else None,
                'url': restaurant.get_absolute_url() if hasattr(restaurant, 'get_absolute_url') else None
            })
        
        return JsonResponse({
            'success': True,
            'count': len(results),
            'radius_km': radius_km,
            'user_location': {
                'lat': user_lat,
                'lng': user_lng
            },
            'restaurants': results
        })
        
    except (ValueError, TypeError) as e:
        return JsonResponse({
            'success': False,
            'error': 'Invalid parameters. Please provide valid lat, lng, and optional radius.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in find_nearby_restaurants: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while searching for restaurants.'
        }, status=500)


@require_http_methods(["GET"])
@cache_page(60 * 15)  # Cache for 15 minutes
def get_restaurants_by_region(request):
    """
    Get restaurants within a bounding box using spatial queries.
    Useful for map views.
    
    Query params:
    - north: Northern boundary latitude
    - south: Southern boundary latitude
    - east: Eastern boundary longitude
    - west: Western boundary longitude
    - michelin_only: Filter for Michelin starred only (true/false)
    """
    try:
        from django.contrib.gis.geos import Polygon
        
        # Get bounding box parameters
        north = float(request.GET.get('north'))
        south = float(request.GET.get('south'))
        east = float(request.GET.get('east'))
        west = float(request.GET.get('west'))
        michelin_only = request.GET.get('michelin_only', 'false').lower() == 'true'
        
        # Create bounding box polygon
        bbox = Polygon.from_bbox((west, south, east, north))
        
        # Query restaurants within bounding box
        queryset = Restaurant.objects.filter(
            geolocation__within=bbox,
            is_active=True
        )
        
        if michelin_only:
            queryset = queryset.filter(michelin_stars__gt=0)
        
        # Get count by stars for statistics
        stats = {
            'total': queryset.count(),
            'three_stars': queryset.filter(michelin_stars=3).count(),
            'two_stars': queryset.filter(michelin_stars=2).count(),
            'one_star': queryset.filter(michelin_stars=1).count(),
            'green_star': queryset.filter(green_star=True).count(),
        }
        
        # Format results (limit to prevent overload)
        restaurants = []
        for restaurant in queryset.select_related()[:500]:
            restaurants.append({
                'id': str(restaurant.id),
                'name': restaurant.name,
                'lat': float(restaurant.latitude) if restaurant.latitude else None,
                'lng': float(restaurant.longitude) if restaurant.longitude else None,
                'michelin_stars': restaurant.michelin_stars,
                'green_star': restaurant.green_star,
                'cuisine': restaurant.cuisine_type,
                'city': restaurant.city,
                'country': restaurant.country,
            })
        
        return JsonResponse({
            'success': True,
            'bounds': {
                'north': north,
                'south': south,
                'east': east,
                'west': west
            },
            'stats': stats,
            'restaurants': restaurants
        })
        
    except (ValueError, TypeError, KeyError) as e:
        return JsonResponse({
            'success': False,
            'error': 'Invalid parameters. Please provide north, south, east, and west boundaries.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in get_restaurants_by_region: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while fetching restaurants.'
        }, status=500)


@require_http_methods(["GET"])
def get_nearest_restaurant(request):
    """
    Find the single nearest restaurant to a location.
    
    Query params:
    - lat: User's latitude
    - lng: User's longitude
    - cuisine: Optional cuisine type filter
    """
    try:
        user_lat = float(request.GET.get('lat'))
        user_lng = float(request.GET.get('lng'))
        cuisine = request.GET.get('cuisine', None)
        
        # Create user location point
        user_location = Point(user_lng, user_lat, srid=4326)
        
        # Build query
        queryset = Restaurant.objects.filter(
            geolocation__isnull=False,
            is_active=True
        )
        
        if cuisine:
            queryset = queryset.filter(cuisine_type__icontains=cuisine)
        
        # Find nearest restaurant
        nearest = queryset.annotate(
            distance_km=Distance('geolocation', user_location)
        ).order_by('distance_km').first()
        
        if nearest:
            return JsonResponse({
                'success': True,
                'restaurant': {
                    'id': str(nearest.id),
                    'name': nearest.name,
                    'cuisine': nearest.cuisine_type,
                    'city': nearest.city,
                    'country': nearest.country,
                    'michelin_stars': nearest.michelin_stars,
                    'distance_km': round(nearest.distance_km.km, 2),
                    'latitude': float(nearest.latitude) if nearest.latitude else None,
                    'longitude': float(nearest.longitude) if nearest.longitude else None,
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No restaurants found'
            }, status=404)
            
    except (ValueError, TypeError) as e:
        return JsonResponse({
            'success': False,
            'error': 'Invalid parameters. Please provide valid lat and lng.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in get_nearest_restaurant: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while searching.'
        }, status=500)


@require_http_methods(["GET"])
@cache_page(60 * 60)  # Cache for 1 hour
def get_restaurant_clusters(request):
    """
    Get restaurant density clusters for heatmap visualization.
    Groups restaurants by proximity for better map performance.
    
    Query params:
    - zoom: Map zoom level (affects clustering precision)
    """
    try:
        from django.contrib.gis.db.models import Extent
        from django.db.models import Count
        
        zoom = int(request.GET.get('zoom', 5))
        
        # Get extent of all restaurants
        extent = Restaurant.objects.filter(
            geolocation__isnull=False
        ).aggregate(
            bbox=Extent('geolocation')
        )['bbox']
        
        if not extent:
            return JsonResponse({
                'success': True,
                'clusters': []
            })
        
        # Simplified clustering based on grid
        # In production, consider using PostGIS ST_ClusterKMeans
        grid_size = 10 / (2 ** zoom)  # Adjust grid based on zoom
        
        clusters = []
        
        # This is a simplified version - for production, use proper clustering
        restaurants = Restaurant.objects.filter(
            geolocation__isnull=False,
            is_active=True
        ).values('latitude', 'longitude', 'michelin_stars')
        
        # Group into clusters (simplified grid approach)
        cluster_dict = {}
        for r in restaurants:
            if r['latitude'] and r['longitude']:
                # Round to grid
                cluster_key = (
                    round(r['latitude'] / grid_size) * grid_size,
                    round(r['longitude'] / grid_size) * grid_size
                )
                
                if cluster_key not in cluster_dict:
                    cluster_dict[cluster_key] = {
                        'lat': cluster_key[0],
                        'lng': cluster_key[1],
                        'count': 0,
                        'michelin_count': 0
                    }
                
                cluster_dict[cluster_key]['count'] += 1
                if r['michelin_stars'] > 0:
                    cluster_dict[cluster_key]['michelin_count'] += 1
        
        clusters = list(cluster_dict.values())
        
        return JsonResponse({
            'success': True,
            'zoom': zoom,
            'cluster_count': len(clusters),
            'clusters': clusters
        })
        
    except Exception as e:
        logger.error(f"Error in get_restaurant_clusters: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while generating clusters.'
        }, status=500)