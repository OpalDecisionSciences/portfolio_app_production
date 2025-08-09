# Migration to add Top Restaurants Recommendation system for homepage featured restaurants
# This is for system-wide top recommendations, not user-specific personalized recommendations

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
import uuid

class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0009_fix_basemodel_soft_delete_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Main recommendation model for system-generated TOP restaurant recommendations
        migrations.CreateModel(
            name='RestaurantRecommendation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                
                # Recommendation metrics
                ('recommendation_score', models.FloatField(
                    default=0.0,
                    help_text='Combined recommendation score (0.0-1.0)'
                )),
                ('click_through_rate', models.FloatField(
                    default=0.0,
                    help_text='Percentage of users who clicked on this recommendation'
                )),
                ('user_rating_average', models.FloatField(
                    default=0.0,
                    help_text='Average user rating for this restaurant'
                )),
                ('total_favorites_count', models.IntegerField(
                    default=0,
                    help_text='Total number of users who favorited this restaurant'
                )),
                ('total_views_count', models.IntegerField(
                    default=0,
                    help_text='Total number of times this restaurant was viewed'
                )),
                ('michelin_boost', models.FloatField(
                    default=0.0,
                    help_text='Boost score for Michelin stars (0.1 per star)'
                )),
                
                # Algorithm metadata
                ('algorithm_version', models.CharField(
                    max_length=20,
                    default='v1.0',
                    help_text='Algorithm version used to calculate this score'
                )),
                ('last_calculated', models.DateTimeField(
                    auto_now=True,
                    help_text='When this recommendation score was last calculated'
                )),
                
                # Regional/Contextual data
                ('city', models.CharField(
                    max_length=100,
                    blank=True,
                    db_index=True,
                    help_text='City for regional recommendations'
                )),
                ('state', models.CharField(
                    max_length=100,
                    blank=True,
                    help_text='State/Province for regional recommendations'
                )),
                ('country', models.CharField(
                    max_length=100,
                    blank=True,
                    db_index=True,
                    help_text='Country for regional recommendations'
                )),
                
                # Display configuration
                ('is_featured_homepage', models.BooleanField(
                    default=False,
                    db_index=True,
                    help_text='Show on homepage featured section'
                )),
                ('homepage_order', models.IntegerField(
                    default=999,
                    help_text='Display order on homepage (lower = higher priority)'
                )),
                ('is_regional_featured', models.BooleanField(
                    default=False,
                    help_text='Featured in regional recommendations'
                )),
                
                # Foreign keys
                ('restaurant', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='recommendation_data',
                    to='restaurants.restaurant'
                )),
            ],
            options={
                'ordering': ['-recommendation_score', 'homepage_order'],
                'indexes': [
                    models.Index(fields=['is_featured_homepage', '-recommendation_score'], name='featured_homepage_idx'),
                    models.Index(fields=['country', 'city', '-recommendation_score'], name='regional_recommendations_idx'),
                    models.Index(fields=['algorithm_version', 'last_calculated'], name='algorithm_version_idx'),
                ],
            },
        ),
        
        # Track user interactions with recommendations for algorithm improvement
        migrations.CreateModel(
            name='UserRecommendationInteraction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                
                ('interaction_type', models.CharField(
                    max_length=20,
                    choices=[
                        ('impression', 'Shown to User'),
                        ('viewed', 'Viewed Details'),
                        ('clicked', 'Clicked Through'),
                        ('favorited', 'Added to Favorites'),
                        ('visited', 'Visited Restaurant'),
                        ('dismissed', 'Dismissed/Hidden'),
                    ],
                    db_index=True
                )),
                
                ('interaction_context', models.CharField(
                    max_length=50,
                    choices=[
                        ('homepage_featured', 'Homepage Featured Section'),
                        ('homepage_sidebar', 'Homepage Sidebar'),
                        ('search_results', 'Search Results'),
                        ('recommendation_api', 'Recommendation API'),
                        ('email_campaign', 'Email Campaign'),
                        ('personalized_page', 'Personalized Recommendations Page'),
                    ],
                    default='homepage_featured'
                )),
                
                ('session_id', models.CharField(
                    max_length=100,
                    blank=True,
                    help_text='Session identifier for tracking user journey'
                )),
                
                ('recommendation_score_at_time', models.FloatField(
                    null=True,
                    blank=True,
                    help_text='The recommendation score when this interaction occurred'
                )),
                
                # Foreign keys
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='recommendation_interactions',
                    to=settings.AUTH_USER_MODEL
                )),
                ('restaurant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='user_interactions',
                    to='restaurants.restaurant'
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['user', 'interaction_type', '-created_at'], name='user_interaction_idx'),
                    models.Index(fields=['restaurant', 'interaction_type'], name='restaurant_interaction_idx'),
                    models.Index(fields=['session_id', 'created_at'], name='session_tracking_idx'),
                    models.Index(fields=['interaction_context', 'created_at'], name='context_tracking_idx'),
                ],
            },
        ),
        
        # Add unique constraint to prevent duplicate interactions
        migrations.AddConstraint(
            model_name='userrecommendationinteraction',
            constraint=models.UniqueConstraint(
                fields=['user', 'restaurant', 'interaction_type', 'session_id'],
                name='unique_user_restaurant_interaction_per_session'
            ),
        ),
    ]