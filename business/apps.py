from django.apps import AppConfig


class BusinessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "business"
    verbose_name = "Tratra Business"

    def ready(self):
        from business import signals  # noqa: F401
