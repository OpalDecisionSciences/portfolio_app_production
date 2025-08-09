"""
Celery configuration for portfolio_project.
"""
import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Set the default Django settings module for the 'celery' program
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')

app = Celery('portfolio_project')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps
app.autodiscover_tasks()

# Celery Beat Schedule for periodic tasks
app.conf.beat_schedule = {
    'send-birthday-emails': {
        'task': 'restaurants.tasks_birthday_emails.send_birthday_emails',
        'schedule': crontab(day_of_month=1, hour=9, minute=0),  # 1st of each month at 9 AM
        'options': {
            'queue': 'emails',
            'priority': 5,
        }
    },
    'update-top-restaurant-recommendations': {
        'task': 'restaurants.tasks_birthday_emails.update_top_restaurant_recommendations',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
        'options': {
            'queue': 'default',
            'priority': 3,
        }
    },
    'check-weather-caching': {
        'task': 'restaurants.tasks.check_weather_caching_health',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
        'options': {
            'queue': 'monitoring',
            'priority': 1,
        }
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')