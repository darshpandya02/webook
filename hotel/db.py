"""Schema bootstrap: create the app's own schema before migrations run."""

from django.conf import settings
from django.db import connections


def ensure_schema(sender=None, using="default", **kwargs) -> None:
    schema = settings.DB_SCHEMA
    with connections[using].cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
