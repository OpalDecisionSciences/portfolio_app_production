# Add missing BaseModel fields to accounts tables
# Simple fix: add the fields that the models expect

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
        # Add BaseModel fields to UserChatHistory
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

        # Add BaseModel fields to UserFavoriteRestaurant  
        migrations.AddField(
            model_name='userfavoriterestaurant',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
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
    ]