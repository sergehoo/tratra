from django.apps import AppConfig


class LoadtestConfig(AppConfig):
    """Tests de charge (installée seulement par tratra/settings/loadtest.py) : refuse de démarrer hors environnement de mesure sûr."""
    name = "loadtest"
    verbose_name = "Tests de charge"

    def ready(self):
        from loadtest import guard

        guard.assert_safe()
