# Complete BaseModel implementation for all BaseModel-inheriting models in accounts app
# Systematically adds missing BaseModel fields to maintain zero-CASCADE, zero-NULL architecture

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
import uuid
from datetime import datetime
from django.utils import timezone

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_user_performance_indexes'),
    ]

    operations = [
        # PasswordResetToken - Add missing BaseModel fields
        # Currently has: id, token, created_at, expires_at, used, ip_address, user_id
        # Missing: updated_at, is_active, deactivated_at, deactivation_reason, deactivated_by
        migrations.AddField(
            model_name='passwordresettoken',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='passwordresettoken',
            name='is_active',
            field=models.BooleanField(default=True, db_index=True),
        ),
        migrations.AddField(
            model_name='passwordresettoken',
            name='deactivated_at',
            field=models.DateTimeField(
                default=timezone.make_aware(datetime.min),
                help_text="When this record was deactivated. Uses datetime.min for never deactivated."
            ),
        ),
        migrations.AddField(
            model_name='passwordresettoken',
            name='deactivation_reason',
            field=models.CharField(
                max_length=200, 
                default='', 
                blank=True,
                help_text="Reason for deactivation"
            ),
        ),
        migrations.AddField(
            model_name='passwordresettoken',
            name='deactivated_by',
            field=models.ForeignKey(
                settings.AUTH_USER_MODEL,
                on_delete=models.PROTECT,
                related_name='passwordresettoken_deactivations',
                default=uuid.UUID('00000000-0000-0000-0000-000000000001'),
                help_text="User who deactivated this record"
            ),
        ),
    ]