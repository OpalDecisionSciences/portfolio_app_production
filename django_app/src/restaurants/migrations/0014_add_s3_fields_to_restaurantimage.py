# Migration to add S3 fields to RestaurantImage model
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0013_add_restaurantimage_fields'),
    ]

    operations = [
        # Add S3 URL field (primary image URL)
        migrations.AddField(
            model_name='restaurantimage',
            name='s3_url',
            field=models.URLField(blank=True, max_length=500, help_text='Primary S3 URL for the image'),
        ),
        
        # Add S3 key field (for management operations)
        migrations.AddField(
            model_name='restaurantimage',
            name='s3_key',
            field=models.CharField(blank=True, max_length=500, help_text='S3 key for management operations'),
        ),
        
        # Add index on s3_key for fast lookups
        migrations.AddIndex(
            model_name='restaurantimage',
            index=models.Index(fields=['s3_key'], name='restaurants_s3_key_idx'),
        ),
        
        # Add index on s3_url for fast lookups
        migrations.AddIndex(
            model_name='restaurantimage',
            index=models.Index(fields=['s3_url'], name='restaurants_s3_url_idx'),
        ),
    ]