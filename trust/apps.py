from django.apps import AppConfig


class TrustConfigApp(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "trust"
    verbose_name = "Tratra Trust"

    def ready(self):
        from trust import signals  # noqa: F401  (branche la réévaluation automatique des badges)
