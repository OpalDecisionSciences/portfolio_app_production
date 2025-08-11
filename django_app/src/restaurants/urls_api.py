"""
API URL patterns for restaurant spatial and data endpoints.
"""

from django.urls import path
from . import views_spatial

app_name = 'restaurants_api'

urlpatterns = [
    # Spatial/Location endpoints
    path('nearby/', views_spatial.find_nearby_restaurants, name='nearby_restaurants'),
    path('region/', views_spatial.get_restaurants_by_region, name='restaurants_by_region'),
    path('nearest/', views_spatial.get_nearest_restaurant, name='nearest_restaurant'),
    path('clusters/', views_spatial.get_restaurant_clusters, name='restaurant_clusters'),
]