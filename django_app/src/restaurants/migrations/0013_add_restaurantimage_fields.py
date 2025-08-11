# Migration to add missing fields to RestaurantImage model
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0012_add_parent_group_fields'),
    ]

    operations = [
        # Add content_hash field
        migrations.AddField(
            model_name='restaurantimage',
            name='content_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64, help_text='SHA256 hash of image content for duplicate detection'),
        ),
        
        # Add perceptual_hash field
        migrations.AddField(
            model_name='restaurantimage',
            name='perceptual_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64, help_text='Perceptual hash for similar image detection'),
        ),
        
        # Add source_url_hash field
        migrations.AddField(
            model_name='restaurantimage',
            name='source_url_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64, help_text='SHA256 hash of source URL for tracking'),
        ),
        
        # Add ai_processed field
        migrations.AddField(
            model_name='restaurantimage',
            name='ai_processed',
            field=models.BooleanField(default=False, db_index=True, help_text='Whether AI analysis has been completed'),
        ),
    ]
