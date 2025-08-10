# Migration to add error tracking and data quality fields to Restaurant model
# These fields were added to the model in commit f8df1875 but migration was missed
# Also includes performance indexes from 0012 migration

from django.db import migrations, models

class Migration(migrations.Migration):
    atomic = False  # Allow index creation outside transaction
    
    dependencies = [
        ('restaurants', '0010_top_restaurants_recommendation_system'),
        ('restaurants', '0009_fix_basemodel_soft_delete_fields'),
    ]

    operations = [
        # Error tracking fields for Restaurant model - using SQL to handle existing fields
        migrations.RunSQL(
            """DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name = 'restaurants_restaurant' 
                              AND column_name = 'has_processing_errors') THEN
                    ALTER TABLE restaurants_restaurant 
                    ADD COLUMN has_processing_errors BOOLEAN DEFAULT FALSE NOT NULL;
                    CREATE INDEX IF NOT EXISTS restaurants_restaurant_has_processing_errors_idx 
                    ON restaurants_restaurant (has_processing_errors);
                END IF;
            END $$;""",
            "ALTER TABLE restaurants_restaurant DROP COLUMN IF EXISTS has_processing_errors;"
        ),
        
        migrations.RunSQL(
            """DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name = 'restaurants_restaurant' 
                              AND column_name = 'error_count') THEN
                    ALTER TABLE restaurants_restaurant 
                    ADD COLUMN error_count INTEGER DEFAULT 0 NOT NULL CHECK (error_count >= 0);
                END IF;
            END $$;""",
            "ALTER TABLE restaurants_restaurant DROP COLUMN IF EXISTS error_count;"
        ),
        
        migrations.RunSQL(
            """DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name = 'restaurants_restaurant' 
                              AND column_name = 'last_error_type') THEN
                    ALTER TABLE restaurants_restaurant 
                    ADD COLUMN last_error_type VARCHAR(100) DEFAULT '' NOT NULL;
                END IF;
            END $$;""",
            "ALTER TABLE restaurants_restaurant DROP COLUMN IF EXISTS last_error_type;"
        ),
        
        migrations.RunSQL(
            """DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name = 'restaurants_restaurant' 
                              AND column_name = 'last_error_at') THEN
                    ALTER TABLE restaurants_restaurant 
                    ADD COLUMN last_error_at TIMESTAMP WITH TIME ZONE;
                END IF;
            END $$;""",
            "ALTER TABLE restaurants_restaurant DROP COLUMN IF EXISTS last_error_at;"
        ),
        
        migrations.RunSQL(
            """DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name = 'restaurants_restaurant' 
                              AND column_name = 'data_quality_score') THEN
                    ALTER TABLE restaurants_restaurant 
                    ADD COLUMN data_quality_score DECIMAL(3,2) DEFAULT 1.00 NOT NULL;
                END IF;
            END $$;""",
            "ALTER TABLE restaurants_restaurant DROP COLUMN IF EXISTS data_quality_score;"
        ),
        
        # Performance indexes (originally from migration 0012)
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
        
        # Error tracking indexes (now that error fields exist from this migration)
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
            "CREATE INDEX IF NOT EXISTS idx_menuitem_section "
            "ON restaurants_menuitem (section_id) WHERE is_active = true;",
            "DROP INDEX IF EXISTS idx_menuitem_section;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_menusection_restaurant_order "
            "ON restaurants_menusection (restaurant_id, \"order\") WHERE is_active = true;",
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
        
        # Review indexes (without is_active - field doesn't exist on RestaurantReview yet)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_review_restaurant_rating "
            "ON restaurants_restaurantreview (restaurant_id, rating);",
            "DROP INDEX IF EXISTS idx_review_restaurant_rating;"
        ),
        
        # Scraping job indexes (without WHERE is_active - these models don't have BaseModel fields yet)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_scrapingjob_status_created "
            "ON restaurants_scrapingjob (status, created_at);",
            "DROP INDEX IF EXISTS idx_scrapingjob_status_created;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_imagescrapingjob_restaurant_status "
            "ON restaurants_imagescrapingjob (restaurant_id, status);",
            "DROP INDEX IF EXISTS idx_imagescrapingjob_restaurant_status;"
        ),
    ]