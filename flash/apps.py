from django.apps import AppConfig


class FlashConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "flash"
    verbose_name = "Tratra Flash et Smart Dispatch"

    def ready(self):
        from flash import signals  # noqa: F401  (désistement après acceptation : fait vérifiable consigné pour Tratra Trust)
