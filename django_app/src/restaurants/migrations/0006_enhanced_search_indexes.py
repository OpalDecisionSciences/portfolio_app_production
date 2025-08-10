# Production-ready migration for enhanced search performance
# Uses IF NOT EXISTS patterns to handle existing indexes gracefully
# Engineering Excellence: Idempotent, safe for re-running

from django.db import migrations, models


class Migration(migrations.Migration):
    # Set atomic=False to allow CONCURRENTLY index creation
    atomic = False

    dependencies = [
        ('restaurants', '0005_menuitem_estimated_prep_time_and_more'),
    ]

    operations = [
        # Enable PostgreSQL trigram extension for fuzzy text search (idempotent)
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            "DROP EXTENSION IF EXISTS pg_trgm;"
        ),
        
        # Full-text search indexes for Restaurant (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_search_vector "
            "ON restaurants_restaurant USING gin("
            "to_tsvector('english', name || ' ' || COALESCE(description, '') || ' ' || "
            "COALESCE(cuisine_type, '') || ' ' || city || ' ' || country));",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_search_vector;"
        ),
        
        # Trigram indexes for fuzzy search (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_name_trigram "
            "ON restaurants_restaurant USING gin(name gin_trgm_ops);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_name_trigram;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_city_trigram "
            "ON restaurants_restaurant USING gin(city gin_trgm_ops);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_city_trigram;"
        ),
        
        # Composite indexes for common query patterns (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_search_rank_idx "
            "ON restaurants_restaurant (is_active, michelin_stars, rating DESC);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_search_rank_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_location_cuisine_idx "
            "ON restaurants_restaurant (country, city, cuisine_type, is_active);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_location_cuisine_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_price_rating_idx "
            "ON restaurants_restaurant (price_range, rating, is_active);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_price_rating_idx;"
        ),
        
        # Geographic search optimization (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_restaurant_geo_idx "
            "ON restaurants_restaurant (latitude, longitude);",
            
            "DROP INDEX IF EXISTS restaurants_restaurant_geo_idx;"
        ),
        
        # Review search optimization (idempotent) - skip is_active until BaseModel migration applied
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_review_restaurant_rating_idx "
            "ON restaurants_restaurantreview (restaurant_id, rating DESC);",
            
            "DROP INDEX IF EXISTS restaurants_review_restaurant_rating_idx;"
        ),
        
        # Full-text search for reviews (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_review_content_search "
            "ON restaurants_restaurantreview USING gin("
            "to_tsvector('english', title || ' ' || COALESCE(content, '')));",
            
            "DROP INDEX IF EXISTS restaurants_review_content_search;"
        ),
        
        # Menu item search optimization (idempotent) - use correct field name section_id
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_menuitem_section_price_idx "
            "ON restaurants_menuitem (section_id, price);",
            
            "DROP INDEX IF EXISTS restaurants_menuitem_section_price_idx;"
        ),
        
        # Full-text search for menu items (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_menuitem_search "
            "ON restaurants_menuitem USING gin("
            "to_tsvector('english', name || ' ' || COALESCE(description, '')));",
            
            "DROP INDEX IF EXISTS restaurants_menuitem_search;"
        ),
        
        # Image search optimization (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_image_category_idx "
            "ON restaurants_restaurantimage (restaurant_id, ai_category, processing_status);",
            
            "DROP INDEX IF EXISTS restaurants_image_category_idx;"
        ),
        
        # Cart optimization (idempotent) - Note: cart_status field will be added in migration 0007
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_cart_user_restaurant_idx "
            "ON restaurants_usercart (user_id, restaurant_id, is_active, updated_at DESC);",
            
            "DROP INDEX IF EXISTS restaurants_cart_user_restaurant_idx;"
        ),
        
        # Scraping task optimization (idempotent)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS restaurants_scrapingbacklogtask_queue_idx "
            "ON restaurants_scrapingbacklogtask (status, task_type, priority, created_at);",
            
            "DROP INDEX IF EXISTS restaurants_scrapingbacklogtask_queue_idx;"
        ),
    ]