# Migration to restructure User model:
# - Change date_of_birth to birth_month (integer 1-12)
# - Split location into city, state, country fields

from django.db import migrations, models

def migrate_date_of_birth_to_month(apps, schema_editor):
    """No-op: No existing users to migrate"""
    pass

def reverse_birth_month_to_date(apps, schema_editor):
    """No-op: No existing users to reverse"""
    pass

def parse_location_to_fields(apps, schema_editor):
    """No-op: No existing users to migrate"""
    pass

def combine_fields_to_location(apps, schema_editor):
    """No-op: No existing users to reverse"""
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_alter_userfavoriterestaurant_restaurant'),
    ]

    operations = [
        # Add new fields first
        migrations.AddField(
            model_name='user',
            name='birth_month',
            field=models.IntegerField(
                blank=True,
                null=True,
                choices=[
                    (1, 'January'), (2, 'February'), (3, 'March'),
                    (4, 'April'), (5, 'May'), (6, 'June'),
                    (7, 'July'), (8, 'August'), (9, 'September'),
                    (10, 'October'), (11, 'November'), (12, 'December')
                ],
                help_text='Birth month for birthday greetings'
            ),
        ),
        
        migrations.AddField(
            model_name='user',
            name='city',
            field=models.CharField(
                blank=True,
                max_length=100,
                help_text='City of residence'
            ),
        ),
        
        migrations.AddField(
            model_name='user',
            name='state',
            field=models.CharField(
                blank=True,
                max_length=100,
                help_text='State/Province of residence'
            ),
        ),
        
        migrations.AddField(
            model_name='user',
            name='country',
            field=models.CharField(
                blank=True,
                max_length=100,
                help_text='Country of residence'
            ),
        ),
        
        # Migrate data
        migrations.RunPython(migrate_date_of_birth_to_month, reverse_birth_month_to_date),
        migrations.RunPython(parse_location_to_fields, combine_fields_to_location),
        
        # Remove old fields
        migrations.RemoveField(
            model_name='user',
            name='date_of_birth',
        ),
        
        migrations.RemoveField(
            model_name='user',
            name='location',
        ),
        
        # Add index for location-based queries
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['country', 'state', 'city'], name='user_location_idx'),
        ),
        
        # Add index for birthday emails
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['birth_month', 'newsletter_subscription'], name='user_birthday_newsletter_idx'),
        ),
    ]