from django.apps import AppConfig


class BackofficeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backoffice"
    verbose_name = "Back-Office Tratra"

    def ready(self):
        from backoffice import checks  # noqa: F401  (enregistre les contrôles de déploiement)
