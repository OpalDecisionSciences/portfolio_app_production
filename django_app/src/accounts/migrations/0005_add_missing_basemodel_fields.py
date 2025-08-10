# Add missing BaseModel fields to accounts tables
# Only adds fields that don't already exist

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
import uuid
from datetime import datetime
from django.utils import timezone

class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('accounts', '0004_user_birthday_location_restructure'),
    ]

    operations = [
        # UserFavoriteRestaurant is missing some BaseModel fields
        # It already has: id, added_at (as created_at), updated_at
        # Missing: is_active, deactivated_at, deactivation_reason, deactivated_by
        migrations.AddField(
            model_name='userfavoriterestaurant',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userfavoriterestaurant',
            name='deactivated_at',
            field=models.DateTimeField(default=timezone.make_aware(datetime.min)),
        ),
        migrations.AddField(
            model_name='userfavoriterestaurant',
            name='deactivation_reason',
            field=models.CharField(max_length=200, default='', blank=True),
        ),
        migrations.AddField(
            model_name='userfavoriterestaurant',
            name='deactivated_by',
            field=models.ForeignKey(
                settings.AUTH_USER_MODEL,
                on_delete=models.PROTECT,
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                related_name='userfavoriterestaurant_deactivations'
            ),
        ),
        
        # UserChatHistory - Add missing BaseModel fields
        # It has: id, session_start, but missing: created_at, updated_at, is_active, deactivated_at, deactivation_reason, deactivated_by
        # Keep both created_at (BaseModel) and session_start (business logic) fields
        migrations.AddField(
            model_name='userchathistory',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='userchathistory',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='userchathistory',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userchathistory',
            name='deactivated_at',
            field=models.DateTimeField(default=timezone.make_aware(datetime.min)),
        ),
        migrations.AddField(
            model_name='userchathistory',
            name='deactivation_reason',
            field=models.CharField(max_length=200, default='', blank=True),
        ),
        migrations.AddField(
            model_name='userchathistory',
            name='deactivated_by',
            field=models.ForeignKey(
                settings.AUTH_USER_MODEL,
                on_delete=models.PROTECT,
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                related_name='userchathistory_deactivations'
            ),
        ),
        
        # User doesn't inherit from BaseModel - no changes needed
    ]