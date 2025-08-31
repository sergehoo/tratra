from django.apps import AppConfig


class HandyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'handy'

    def ready(self):
        import handy.signal
