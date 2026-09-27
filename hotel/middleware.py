import time


class ServerTimingMiddleware:
    """Adds a Server-Timing header with the time spent inside Django."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        return response
