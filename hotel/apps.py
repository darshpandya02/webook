from django.apps import AppConfig


class HotelConfig(AppConfig):
    name = "hotel"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.db.models.signals import pre_migrate

        from .db import ensure_schema

        pre_migrate.connect(ensure_schema, sender=self)
