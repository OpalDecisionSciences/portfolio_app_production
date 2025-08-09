# Migration to restructure User model:
# - Change date_of_birth to birth_month (integer 1-12)
# - Split location into city, state, country fields

from django.db import migrations, models

def migrate_date_of_birth_to_month(apps, schema_editor):
    """Extract month from date_of_birth and populate birth_month"""
    User = apps.get_model('accounts', 'User')
    for user in User.objects.exclude(date_of_birth__isnull=True):
        user.birth_month = user.date_of_birth.month
        user.save(update_fields=['birth_month'])

def reverse_birth_month_to_date(apps, schema_editor):
    """Reverse migration - set arbitrary day for birth_month"""
    User = apps.get_model('accounts', 'User')
    import datetime
    for user in User.objects.exclude(birth_month__isnull=True):
        # Set to first day of the month, year 2000 as placeholder
        user.date_of_birth = datetime.date(2000, user.birth_month, 1)
        user.save(update_fields=['date_of_birth'])

def parse_location_to_fields(apps, schema_editor):
    """Parse existing location string into city, state, country"""
    User = apps.get_model('accounts', 'User')
    for user in User.objects.exclude(location=''):
        if user.location:
            # Try to parse "City, State, Country" or "City, Country" format
            parts = [p.strip() for p in user.location.split(',')]
            if len(parts) >= 3:
                user.city = parts[0]
                user.state = parts[1] 
                user.country = parts[2]
            elif len(parts) == 2:
                user.city = parts[0]
                user.country = parts[1]
                user.state = ''
            elif len(parts) == 1:
                user.city = parts[0]
                user.state = ''
                user.country = ''
            user.save(update_fields=['city', 'state', 'country'])

def combine_fields_to_location(apps, schema_editor):
    """Reverse migration - combine city, state, country back to location"""
    User = apps.get_model('accounts', 'User')
    for user in User.objects.all():
        parts = []
        if user.city:
            parts.append(user.city)
        if user.state:
            parts.append(user.state)
        if user.country:
            parts.append(user.country)
        user.location = ', '.join(parts)
        user.save(update_fields=['location'])

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