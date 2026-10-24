from django.apps import AppConfig


class HandyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'handy'

    def ready(self):
        import handy.signal
        from handy import eligibility_sync

        eligibility_sync.connect()   # copie calculée de l'éligibilité, recalculée dans la transaction de chaque changement
