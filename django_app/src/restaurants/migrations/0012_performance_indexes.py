# Migration to add database indexes for performance (Medium Priority #3)
# Addresses slow queries in production by adding indexes on frequently queried fields

from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # Allow index creation outside transaction
    
    dependencies = [
        ('restaurants', '0011_add_error_tracking_fields'),
    ]

    operations = [
        # Restaurant model indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_slug "
            "ON restaurants_restaurant (slug);",
            "DROP INDEX IF EXISTS idx_restaurant_slug;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_is_active_slug "
            "ON restaurants_restaurant (is_active, slug);",
            "DROP INDEX IF EXISTS idx_restaurant_is_active_slug;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_city_country "
            "ON restaurants_restaurant (city, country) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_restaurant_city_country;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_michelin_stars "
            "ON restaurants_restaurant (michelin_stars) WHERE is_active = true AND michelin_stars > 0;",
            "DROP INDEX IF EXISTS idx_restaurant_michelin_stars;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_price_range_rating "
            "ON restaurants_restaurant (price_range, rating) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_restaurant_price_range_rating;"
        ),
        
        # Error tracking indexes (now that error fields exist from migration 0011)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_has_errors "
            "ON restaurants_restaurant (has_processing_errors) WHERE has_processing_errors = true;",
            "DROP INDEX IF EXISTS idx_restaurant_has_errors;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_restaurant_data_quality "
            "ON restaurants_restaurant (data_quality_score) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_restaurant_data_quality;"
        ),
        
        # Menu and ordering indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_menuitem_section_order "
            "ON restaurants_menuitem (section_id, display_order) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_menuitem_section_order;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_menusection_restaurant_order "
            "ON restaurants_menusection (restaurant_id, display_order) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_menusection_restaurant_order;"
        ),
        
        # Cart performance indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_usercart_user_active "
            "ON restaurants_usercart (user_id) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_usercart_user_active;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_cartitem_cart_active "
            "ON restaurants_cartitem (cart_id) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_cartitem_cart_active;"
        ),
        
        # Review indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_review_restaurant_rating "
            "ON restaurants_restaurantreview (restaurant_id, rating) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_review_restaurant_rating;"
        ),
        
        # Scraping job indexes
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_scrapingjob_status_created "
            "ON restaurants_scrapingjob (status, created_at);",
            "DROP INDEX IF EXISTS idx_scrapingjob_status_created;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_imagescrapingjob_restaurant_status "
            "ON restaurants_imagescrapingjob (restaurant_id, status) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_imagescrapingjob_restaurant_status;"
        ),
    ]