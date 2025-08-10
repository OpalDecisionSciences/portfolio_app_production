# Generated migration to add indexes for cart_status field
# Engineering Excellence: Optimize performance for cart status queries

from django.db import migrations


class Migration(migrations.Migration):
    # Set atomic=False to allow CONCURRENTLY index creation
    atomic = False
    
    dependencies = [
        ('restaurants', '0007_add_cart_status_field'),
    ]

    operations = [
        # Update cart optimization index to include cart_status (now that field exists)
        migrations.RunSQL(
            "DROP INDEX IF EXISTS restaurants_cart_user_restaurant_idx;",
            reverse_sql="-- No reverse operation needed"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_cart_user_restaurant_status_idx "
            "ON restaurants_usercart (user_id, restaurant_id, cart_status, updated_at DESC);",
            
            "DROP INDEX IF EXISTS restaurants_cart_user_restaurant_status_idx;",
            atomic=False
        ),
        
        # Additional index for cart status queries
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_usercart_cart_status_idx "
            "ON restaurants_usercart (cart_status, is_active);",
            
            "DROP INDEX IF EXISTS restaurants_usercart_cart_status_idx;",
            atomic=False
        ),
    ]