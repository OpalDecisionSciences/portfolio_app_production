# Migration to add parent_group and related fields for multi-restaurant support
from django.db import migrations, models
import django.db.models.deletion
import uuid

def get_deleted_restaurant_placeholder():
    return uuid.UUID('00000000-0000-0000-0000-000000000002')

class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0011_add_error_tracking_fields'),
    ]

    operations = [
        # Add parent_group field with nullable first to avoid circular dependency
        migrations.AddField(
            model_name='restaurant',
            name='parent_group',
            field=models.ForeignKey(
                null=True,
                blank=True,
                help_text='Parent restaurant group if this is an individual restaurant',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='child_restaurants',
                to='restaurants.restaurant'
            ),
        ),
        
        # Add is_restaurant_group field
        migrations.AddField(
            model_name='restaurant',
            name='is_restaurant_group',
            field=models.BooleanField(default=False, help_text='True if this represents a restaurant group'),
        ),
        
        # Add group_source_url field
        migrations.AddField(
            model_name='restaurant',
            name='group_source_url',
            field=models.URLField(blank=True, max_length=500, help_text='Original multi-restaurant URL'),
        ),
        
        # Add individual_restaurant_index field
        migrations.AddField(
            model_name='restaurant',
            name='individual_restaurant_index',
            field=models.IntegerField(blank=True, help_text='Index of this restaurant within the group', null=True),
        ),
    ]
