from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from ..commands import DomainError


def exception_handler(exc, context):
    """Map domain errors from commands to HTTP status codes; defer the rest to DRF."""
    if isinstance(exc, DomainError):
        return Response({"error": exc.code, "detail": exc.message}, status=exc.status)
    return drf_exception_handler(exc, context)
