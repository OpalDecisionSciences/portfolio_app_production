# Migration to add missing User model indexes for performance (Medium Priority #3)
# Addresses slow queries in production by adding indexes on frequently queried fields

from django.db import migrations, connection

def create_index_if_column_exists(apps, schema_editor, table_name, index_name, index_sql, drop_sql):
    """Create index only if the required columns exist"""
    # Check if created_at column exists using schema_editor connection
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = %s AND column_name = %s
            );
        """, [table_name, 'created_at'])
        
        column_exists = cursor.fetchone()[0]
        
        if 'created_at' in index_sql and not column_exists:
            print(f"Skipping index {index_name} - created_at column does not exist in {table_name}")
            return
        
        # Execute the index creation
        cursor.execute(index_sql)

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
        
        # UserChatHistory indexes for performance - conditional on created_at column existing
        migrations.RunPython(
            lambda apps, schema_editor: create_index_if_column_exists(
                apps, schema_editor,
                'accounts_userchathistory',
                'idx_userchathistory_user_created',
                "CREATE INDEX IF NOT EXISTS idx_userchathistory_user_created ON accounts_userchathistory (user_id, created_at DESC);",
                "DROP INDEX IF EXISTS idx_userchathistory_user_created;"
            ),
            migrations.RunPython.noop
        ),
        
        # UserFavoriteRestaurant indexes - conditional on created_at column existing
        migrations.RunPython(
            lambda apps, schema_editor: create_index_if_column_exists(
                apps, schema_editor,
                'accounts_userfavoriterestaurant', 
                'idx_userfavorite_user_created',
                "CREATE INDEX IF NOT EXISTS idx_userfavorite_user_created ON accounts_userfavoriterestaurant (user_id, created_at DESC);",
                "DROP INDEX IF EXISTS idx_userfavorite_user_created;"
            ),
            migrations.RunPython.noop
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_userfavorite_restaurant "
            "ON accounts_userfavoriterestaurant (restaurant_id);",
            "DROP INDEX IF EXISTS idx_userfavorite_restaurant;"
        ),
    ]