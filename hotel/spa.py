"""Serves the React single-page app shell. Hashed assets come from /static/."""

from functools import lru_cache

from django.conf import settings
from django.http import HttpResponse


def _read_index() -> str | None:
    for base in (settings.STATIC_ROOT, settings.SPA_DIST):
        path = base / "index.html"
        if path.exists():
            return path.read_text()
    return None


_cached_index = lru_cache(maxsize=1)(_read_index)


def spa_index(request):
    # Re-read on every request in development, where the build changes under us.
    html = _read_index() if settings.DEBUG else _cached_index()
    if html is None:
        return HttpResponse(
            "Front end not built. Run: cd frontend && npm install && npm run build", status=503, content_type="text/plain"
        )
    response = HttpResponse(html)
    response["Cache-Control"] = "no-cache"
    return response
