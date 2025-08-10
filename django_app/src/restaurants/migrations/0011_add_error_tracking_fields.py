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
        # Error tracking fields for Restaurant model
        migrations.AddField(
            model_name='restaurant',
            name='has_processing_errors',
            field=models.BooleanField(
                default=False, 
                db_index=True, 
                help_text="Flag for filtering restaurants with processing errors"
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='error_count',
            field=models.PositiveIntegerField(
                default=0, 
                help_text="Total number of processing errors encountered"
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='last_error_type',
            field=models.CharField(
                max_length=100, 
                blank=True, 
                default='',
                help_text="Type of most recent error (e.g., 'scraping_failed', 'api_timeout')"
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='last_error_at',
            field=models.DateTimeField(
                null=True, 
                blank=True, 
                help_text="When the last error occurred"
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='data_quality_score',
            field=models.DecimalField(
                max_digits=3, 
                decimal_places=2, 
                default=1.00, 
                help_text="Data completeness score (0.00-1.00)"
            ),
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