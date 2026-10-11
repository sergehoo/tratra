from django.apps import AppConfig


class ReputationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reputation"
    verbose_name = "Évaluations mutuelles et réputation"

    def ready(self):
        from reputation import signals  # noqa: F401
