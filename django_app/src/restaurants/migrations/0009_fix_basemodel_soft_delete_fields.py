# Generated migration to add missing BaseModel soft delete fields
# Fixes: column restaurants_restaurant.deactivated_by_id does not exist

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
import uuid
from datetime import datetime
from django.utils import timezone

def create_system_user(apps, schema_editor):
    """Create system user placeholder if it doesn't exist"""
    User = apps.get_model(settings.AUTH_USER_MODEL.split('.')[0], settings.AUTH_USER_MODEL.split('.')[1])
    system_user_id = uuid.UUID('00000000-0000-0000-0000-000000000001')
    
    if not User.objects.filter(id=system_user_id).exists():
        User.objects.create(
            id=system_user_id,
            username='[SYSTEM]',
            email='system@opaldecisionsciences.com',
            first_name='System',
            last_name='User',
            is_active=False,
            is_staff=False
        )

def reverse_system_user(apps, schema_editor):
    """Remove system user (optional - usually we keep it)"""
    pass

class Migration(migrations.Migration):
    # Set atomic=False for index creation operations
    atomic = False
    
    dependencies = [
        ('restaurants', '0008_cart_status_indexes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create system user first
        migrations.RunPython(create_system_user, reverse_system_user),
        
        # Add missing BaseModel fields to Restaurant
        migrations.AddField(
            model_name='restaurant',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text='When this record was deactivated. Uses datetime.min for never deactivated.'
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='deactivation_reason',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Reason for deactivation',
                max_length=200
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='deactivated_by',
            field=models.ForeignKey(
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text='User who deactivated this record',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='restaurant_deactivations',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        
        # Add is_active index for performance
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_is_active_created_at_idx "
            "ON restaurants_restaurant (is_active, created_at);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_is_active_created_at_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_deactivated_at_idx "
            "ON restaurants_restaurant (deactivated_at);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_deactivated_at_idx;"
        ),
    ]