from django.apps import AppConfig


class BddConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'BDD'

    def ready(self):
        import BDD.signals  # Active les signaux