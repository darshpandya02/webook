from django.urls import include, path, re_path

from hotel.graphql.view import JWTGraphQLView
from hotel.spa import spa_index

urlpatterns = [
    path("api/", include("hotel.api.urls")),
    path("api/graphql", JWTGraphQLView.as_view(graphiql=True)),
    re_path(r"^(?!api/|static/).*$", spa_index),
]
