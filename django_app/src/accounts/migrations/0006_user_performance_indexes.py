# Migration to add missing User model indexes for performance (Medium Priority #3)

from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # Allow index creation outside transaction
    
    dependencies = [
        ('accounts', '0005_add_missing_basemodel_fields'),
    ]

    operations = [
        # User model indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_email "
            "ON accounts_user (email);",
            "DROP INDEX IF EXISTS idx_user_email;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_is_active_email "
            "ON accounts_user (is_active, email);",
            "DROP INDEX IF EXISTS idx_user_is_active_email;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_birth_month "
            "ON accounts_user (birth_month) WHERE birth_month IS NOT NULL;",
            "DROP INDEX IF EXISTS idx_user_birth_month;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_newsletter "
            "ON accounts_user (newsletter_subscription) WHERE newsletter_subscription = true;",
            "DROP INDEX IF EXISTS idx_user_newsletter;"
        ),
        
        # UserChatHistory indexes for performance
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userchathistory_user_created "
            "ON accounts_userchathistory (user_id, created_at DESC);",
            "DROP INDEX IF EXISTS idx_userchathistory_user_created;"
        ),
        
        # UserFavoriteRestaurant indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userfavorite_user_created "
            "ON accounts_userfavoriterestaurant (user_id, added_at DESC);",
            "DROP INDEX IF EXISTS idx_userfavorite_user_created;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userfavorite_restaurant "
            "ON accounts_userfavoriterestaurant (restaurant_id);",
            "DROP INDEX IF EXISTS idx_userfavorite_restaurant;"
        ),
    ]