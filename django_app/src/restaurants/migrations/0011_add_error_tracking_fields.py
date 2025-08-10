# Migration to add error tracking and data quality fields to Restaurant model
# These fields were added to the model in commit f8df1875 but migration was missed

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0010_top_restaurants_recommendation_system'),
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
    ]