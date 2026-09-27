from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("room-types", views.RoomTypeViewSet)
router.register("rooms", views.RoomViewSet)
router.register("items", views.ItemViewSet)
router.register("employee-roles", views.EmployeeRoleViewSet)
router.register("employees", views.EmployeeViewSet)
router.register("bookings", views.BookingViewSet, basename="booking")

urlpatterns = [
    path("health", views.health),
    path("auth/login", views.LoginView.as_view()),
    path("auth/refresh", TokenRefreshView.as_view()),
    path("auth/register", views.RegisterView.as_view()),
    path("auth/me", views.me),
    path("availability", views.availability_search),
    path("dashboard/occupancy", views.occupancy),
    path("audit-log", views.AuditLogView.as_view()),
    path("cron/reset-demo", views.reset_demo),
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema")),
    *router.urls,
]
