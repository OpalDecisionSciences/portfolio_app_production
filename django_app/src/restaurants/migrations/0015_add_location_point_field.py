# Generated migration for adding GeoDjango PointField for optimized spatial queries

from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import Point
from django.db import migrations


def populate_location_field(apps, schema_editor):
    """Populate the new location field from existing lat/lng values."""
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    
    for restaurant in Restaurant.objects.filter(
        latitude__isnull=False, 
        longitude__isnull=False
    ):
        try:
            # Create Point from existing coordinates
            restaurant.location = Point(
                float(restaurant.longitude), 
                float(restaurant.latitude),
                srid=4326  # WGS84 coordinate system
            )
            restaurant.save(update_fields=['location'])
        except Exception as e:
            print(f"Failed to update location for {restaurant.name}: {e}")


def reverse_location_field(apps, schema_editor):
    """Reverse migration - extract lat/lng from Point."""
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    
    for restaurant in Restaurant.objects.filter(location__isnull=False):
        try:
            restaurant.longitude = restaurant.location.x
            restaurant.latitude = restaurant.location.y
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
            name='location',
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
            populate_location_field,
            reverse_location_field
        ),
        
        # Add spatial index for optimized nearby queries
        migrations.AddIndex(
            model_name='restaurant',
            index=gis_models.Index(fields=['location'], name='location_spatial_idx'),
        ),
    ]