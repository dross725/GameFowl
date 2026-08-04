from django.apps import AppConfig

class SmartwagersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'SmartWagers'

    def ready(self):
        from . import signals  # noqa: F401

