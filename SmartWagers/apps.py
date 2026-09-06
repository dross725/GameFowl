from django.apps import AppConfig

class SmartwagersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'SmartWagers'

    def ready(self):
        from . import signals  # noqa: F401
        # Ensure User admin hides superusers even if auth.admin loads later.
        from .admin import register_hidden_superuser_user_admin
        register_hidden_superuser_user_admin()

