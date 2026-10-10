from django.apps import AppConfig


class LiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "live"
    verbose_name = "Suivi en direct"

    def ready(self):
        from live import signals  # noqa: F401
