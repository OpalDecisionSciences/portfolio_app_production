# Migration to add missing User model indexes for performance (Medium Priority #3)
# Addresses slow queries in production by adding indexes on frequently queried fields

from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # Allow index creation outside transaction
    
    dependencies = [
        ('accounts', '0004_user_birthday_location_restructure'),
    ]

    operations = [
        # User model indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_email "
            "ON accounts_user (email);",
            "DROP INDEX IF EXISTS idx_user_email;",
            atomic=False
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_is_active_email "
            "ON accounts_user (is_active, email);",
            "DROP INDEX IF EXISTS idx_user_is_active_email;",
            atomic=False
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_birth_month "
            "ON accounts_user (birth_month) WHERE birth_month IS NOT NULL;",
            "DROP INDEX IF EXISTS idx_user_birth_month;",
            atomic=False
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_user_newsletter "
            "ON accounts_user (newsletter_subscription) WHERE newsletter_subscription = true;",
            "DROP INDEX IF EXISTS idx_user_newsletter;",
            atomic=False
        ),
        
        # UserChatHistory indexes for performance
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userchathistory_user_created "
            "ON accounts_userchathistory (user_id, created_at DESC);",
            "DROP INDEX IF EXISTS idx_userchathistory_user_created;",
            atomic=False
        ),
        
        # UserFavoriteRestaurant indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userfavorite_user_created "
            "ON accounts_userfavoriterestaurant (user_id, created_at DESC);",
            "DROP INDEX IF EXISTS idx_userfavorite_user_created;",
            atomic=False
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userfavorite_restaurant "
            "ON accounts_userfavoriterestaurant (restaurant_id);",
            "DROP INDEX IF EXISTS idx_userfavorite_restaurant;",
            atomic=False
        ),
    ]