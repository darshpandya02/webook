from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .loaders import Loaders


@method_decorator(csrf_exempt, name="dispatch")
class JWTGraphQLView(GraphQLView):
    """GraphQL over the same JWT auth as the REST API. Token auth only, so no CSRF."""

    def dispatch(self, request, *args, **kwargs):
        try:
            result = JWTAuthentication().authenticate(request)
        except AuthenticationFailed as exc:
            return JsonResponse({"errors": [{"message": str(exc.detail), "extensions": {"code": "unauthenticated"}}]}, status=401)
        request.user = result[0] if result is not None else AnonymousUser()
        request.loaders = Loaders()
        return super().dispatch(request, *args, **kwargs)
