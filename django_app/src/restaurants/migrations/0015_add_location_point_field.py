# Generated migration for adding GeoDjango PointField for optimized spatial queries

from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import Point
from django.db import migrations


def populate_geolocation_field(apps, schema_editor):
    """Populate the new geolocation field from existing lat/lng values."""
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    
    for restaurant in Restaurant.objects.filter(
        latitude__isnull=False, 
        longitude__isnull=False
    ):
        try:
            # Create Point from existing coordinates
            restaurant.geolocation = Point(
                float(restaurant.longitude), 
                float(restaurant.latitude),
                srid=4326  # WGS84 coordinate system
            )
            restaurant.save(update_fields=['geolocation'])
        except Exception as e:
            print(f"Failed to update geolocation for {restaurant.name}: {e}")


def reverse_geolocation_field(apps, schema_editor):
    """Reverse migration - extract lat/lng from Point."""
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    
    for restaurant in Restaurant.objects.filter(geolocation__isnull=False):
        try:
            restaurant.longitude = restaurant.geolocation.x
            restaurant.latitude = restaurant.geolocation.y
            restaurant.save(update_fields=['longitude', 'latitude'])
        except Exception as e:
            print(f"Failed to extract coordinates for {restaurant.name}: {e}")


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0014_add_s3_fields_to_restaurantimage'),
    ]

    operations = [
        # Add the PointField for optimized spatial queries
        migrations.AddField(
            model_name='restaurant',
            name='geolocation',
            field=gis_models.PointField(
                srid=4326,  # WGS84 coordinate system
                null=True,
                blank=True,
                spatial_index=True,  # Creates spatial index for fast queries
                help_text='Geographic location as Point for spatial queries'
            ),
        ),
        
        # Populate the new field from existing data
        migrations.RunPython(
            populate_geolocation_field,
            reverse_geolocation_field
        ),
        
        # Add spatial index for optimized nearby queries
        migrations.AddIndex(
            model_name='restaurant',
            index=gis_models.Index(fields=['geolocation'], name='geolocation_spatial_idx'),
        ),
    ]