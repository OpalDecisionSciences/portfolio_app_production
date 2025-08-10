# Comprehensive BaseModel implementation for all BaseModel-inheriting models
# Systematically adds missing BaseModel fields to maintain zero-CASCADE, zero-NULL architecture

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
    atomic = False
    
    dependencies = [
        ('restaurants', '0008_cart_status_indexes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create system user first
        migrations.RunPython(create_system_user, reverse_system_user),
        
        # Restaurant - Add missing BaseModel fields (proper Django approach)
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
        
        # MenuItem - Add missing BaseModel fields (has created_at, updated_at but missing others)
        migrations.AddField(
            model_name='menuitem',
            name='is_active',
            field=models.BooleanField(default=True, db_index=True),
        ),
        migrations.AddField(
            model_name='menuitem',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text='When this record was deactivated. Uses datetime.min for never deactivated.'
            ),
        ),
        migrations.AddField(
            model_name='menuitem',
            name='deactivation_reason',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Reason for deactivation',
                max_length=200
            ),
        ),
        migrations.AddField(
            model_name='menuitem',
            name='deactivated_by',
            field=models.ForeignKey(
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text='User who deactivated this record',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='menuitem_deactivations',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        
        # MenuSection - Add missing BaseModel fields (has created_at, updated_at but missing others)
        migrations.AddField(
            model_name='menusection',
            name='is_active',
            field=models.BooleanField(default=True, db_index=True),
        ),
        migrations.AddField(
            model_name='menusection',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text='When this record was deactivated. Uses datetime.min for never deactivated.'
            ),
        ),
        migrations.AddField(
            model_name='menusection',
            name='deactivation_reason',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Reason for deactivation',
                max_length=200
            ),
        ),
        migrations.AddField(
            model_name='menusection',
            name='deactivated_by',
            field=models.ForeignKey(
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text='User who deactivated this record',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='menusection_deactivations',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        
        # Chef - Add missing BaseModel fields (has created_at, updated_at but missing others)
        migrations.AddField(
            model_name='chef',
            name='is_active',
            field=models.BooleanField(default=True, db_index=True),
        ),
        migrations.AddField(
            model_name='chef',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text='When this record was deactivated. Uses datetime.min for never deactivated.'
            ),
        ),
        migrations.AddField(
            model_name='chef',
            name='deactivation_reason',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Reason for deactivation',
                max_length=200
            ),
        ),
        migrations.AddField(
            model_name='chef',
            name='deactivated_by',
            field=models.ForeignKey(
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text='User who deactivated this record',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='chef_deactivations',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        
        # UserCart - Add missing BaseModel fields (has created_at, updated_at, is_active but missing others)
        migrations.AddField(
            model_name='usercart',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text='When this record was deactivated. Uses datetime.min for never deactivated.'
            ),
        ),
        migrations.AddField(
            model_name='usercart',
            name='deactivation_reason',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Reason for deactivation',
                max_length=200
            ),
        ),
        migrations.AddField(
            model_name='usercart',
            name='deactivated_by',
            field=models.ForeignKey(
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text='User who deactivated this record',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='usercart_deactivations',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        
        # CartItem - Add missing BaseModel fields (has added_at, updated_at but missing ALL BaseModel fields)
        migrations.AddField(
            model_name='cartitem',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
        ),
        migrations.AddField(
            model_name='cartitem',
            name='is_active',
            field=models.BooleanField(default=True, db_index=True),
        ),
        migrations.AddField(
            model_name='cartitem',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text='When this record was deactivated. Uses datetime.min for never deactivated.'
            ),
        ),
        migrations.AddField(
            model_name='cartitem',
            name='deactivation_reason',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Reason for deactivation',
                max_length=200
            ),
        ),
        migrations.AddField(
            model_name='cartitem',
            name='deactivated_by',
            field=models.ForeignKey(
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text='User who deactivated this record',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='cartitem_deactivations',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        
        # Add BaseModel indexes for all updated models
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
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_menuitem_is_active_created_at_idx "
            "ON restaurants_menuitem (is_active, created_at);",
            "DROP INDEX IF EXISTS restaurants_menuitem_is_active_created_at_idx;"
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_menusection_is_active_created_at_idx "
            "ON restaurants_menusection (is_active, created_at);",
            "DROP INDEX IF EXISTS restaurants_menusection_is_active_created_at_idx;"
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_chef_is_active_created_at_idx "
            "ON restaurants_chef (is_active, created_at);",
            "DROP INDEX IF EXISTS restaurants_chef_is_active_created_at_idx;"
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_usercart_is_active_created_at_idx "
            "ON restaurants_usercart (is_active, created_at);",
            "DROP INDEX IF EXISTS restaurants_usercart_is_active_created_at_idx;"
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_cartitem_is_active_created_at_idx "
            "ON restaurants_cartitem (is_active, created_at);",
            "DROP INDEX IF EXISTS restaurants_cartitem_is_active_created_at_idx;"
        ),
    ]