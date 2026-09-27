"""REST controllers. Each write endpoint builds a Command and hands it to commands.run."""

from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from .. import availability, commands, pricing
from ..models import (
    ACTIVE_STATUSES,
    AuditLog,
    Booking,
    BookingStatus,
    Employee,
    EmployeeRole,
    Item,
    Room,
    RoomServiceOrder,
    RoomType,
)
from ..roles import is_staff_role
from . import serializers as s
from .permissions import IsAdmin, IsStaff, ReadPublicWriteAdmin, ReadStaffWriteAdmin


def booking_queryset():
    """Everything the booking serializer touches, in a fixed number of queries regardless of page size."""
    return Booking.objects.select_related("room__room_type", "guest", "bill").prefetch_related(
        Prefetch("room_service_orders", queryset=RoomServiceOrder.objects.select_related("item"))
    )


# --- Auth ---------------------------------------------------------------------


class LoginView(TokenObtainPairView):
    serializer_class = s.TokenSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RegisterView(generics.CreateAPIView):
    serializer_class = s.RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        return Response(s.MeSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=s.MeSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(s.MeSerializer(request.user).data)


# --- Catalogue ----------------------------------------------------------------


class RoomTypeViewSet(viewsets.ModelViewSet):
    queryset = RoomType.objects.all()
    serializer_class = s.RoomTypeSerializer
    permission_classes = [ReadPublicWriteAdmin]
    pagination_class = None


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = s.ItemSerializer
    permission_classes = [ReadPublicWriteAdmin]
    pagination_class = None


class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.select_related("room_type")
    serializer_class = s.RoomSerializer
    permission_classes = [ReadStaffWriteAdmin]
    pagination_class = None


class EmployeeRoleViewSet(viewsets.ModelViewSet):
    queryset = EmployeeRole.objects.all()
    serializer_class = s.EmployeeRoleSerializer
    permission_classes = [IsAdmin]
    pagination_class = None


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.select_related("role")
    serializer_class = s.EmployeeSerializer
    permission_classes = [IsAdmin]
    pagination_class = None


# --- Availability -------------------------------------------------------------


@extend_schema(
    parameters=[
        OpenApiParameter("check_in", str, required=True, description="YYYY-MM-DD"),
        OpenApiParameter("check_out", str, required=True, description="YYYY-MM-DD"),
        OpenApiParameter("guests", int),
    ],
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def availability_search(request):
    q = s.AvailabilityQuerySerializer(data=request.query_params)
    q.is_valid(raise_exception=True)
    ci, co = q.validated_data["check_in"], q.validated_data["check_out"]
    commands.validate_stay(ci, co)
    results = availability.search(ci, co, q.validated_data["guests"])
    return Response(
        {"check_in": ci, "check_out": co, "guests": q.validated_data["guests"], "results": results}
    )


# --- Bookings -----------------------------------------------------------------


class BookingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Guests see their own bookings; staff and admins see all of them."""

    serializer_class = s.BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = booking_queryset()
        user = self.request.user
        if not is_staff_role(user):
            qs = qs.filter(guest=user)
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        if params.get("date"):
            # Bookings in the hotel on a given night.
            qs = qs.filter(check_in__lte=params["date"], check_out__gt=params["date"])
        if params.get("q") and is_staff_role(user):
            term = params["q"]
            qs = qs.filter(
                Q(guest__username__icontains=term)
                | Q(guest__first_name__icontains=term)
                | Q(guest__last_name__icontains=term)
                | Q(room__number=term)
            )
        return qs

    def _respond(self, booking_id: int, code=status.HTTP_200_OK):
        booking = booking_queryset().get(pk=booking_id)
        return Response(s.BookingSerializer(booking).data, status=code)

    @extend_schema(request=s.CreateBookingSerializer, responses={201: s.BookingSerializer})
    def create(self, request):
        ser = s.CreateBookingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        booking = commands.run(commands.CreateBooking(**ser.validated_data), request.user)
        return self._respond(booking.pk, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.BookingSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = commands.run(commands.CancelBooking(booking=int(pk)), request.user)
        return self._respond(booking.pk)

    @extend_schema(request=None, responses=s.BookingSerializer)
    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        booking = commands.run(commands.CheckIn(booking=int(pk)), request.user)
        return self._respond(booking.pk)

    @extend_schema(request=None, responses=s.BookingSerializer)
    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, pk=None):
        bill = commands.run(commands.CheckOut(booking=int(pk)), request.user)
        return self._respond(bill.booking_id)

    @extend_schema(request=s.RoomServiceInputSerializer, responses={201: s.BookingSerializer})
    @action(detail=True, methods=["post"], url_path="room-service")
    def room_service(self, request, pk=None):
        ser = s.RoomServiceInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = commands.run(commands.AddRoomService(booking=int(pk), **ser.validated_data), request.user)
        return self._respond(order.booking_id, status.HTTP_201_CREATED)

    @extend_schema(responses=dict)
    @action(detail=True, methods=["get"])
    def bill(self, request, pk=None):
        """Running charges for an open stay, or the issued bill after check-out."""
        booking = self.get_object()
        issued = getattr(booking, "bill", None)
        lines = [
            {
                "item": o.item.name,
                "quantity": o.quantity,
                "unit_price": str(o.unit_price),
                "line_total": str(o.line_total),
            }
            for o in booking.room_service_orders.all()
        ]
        charges = pricing.quote_booking(booking).as_dict()
        return Response(
            {
                "booking": booking.pk,
                "status": booking.status,
                "room": booking.room.number,
                "guest": booking.guest.get_full_name() or booking.guest.username,
                "check_in": booking.check_in,
                "check_out": booking.check_out,
                "lines": lines,
                **charges,
                "issued": s.BillSerializer(issued).data if issued else None,
            }
        )


# --- Staff dashboard ----------------------------------------------------------


@extend_schema(parameters=[OpenApiParameter("date", str)], responses=dict)
@api_view(["GET"])
@permission_classes([IsStaff])
def occupancy(request):
    """Occupancy for a date and the next 6 days, plus today's arrivals and departures."""
    day = request.query_params.get("date")
    try:
        start = timezone.datetime.fromisoformat(day).date() if day else timezone.localdate()
    except ValueError:
        raise ValidationError({"date": "Use YYYY-MM-DD."})
    end = start + timedelta(days=7)
    rooms_total = Room.objects.filter(is_active=True).count()
    stays = list(
        Booking.objects.filter(status__in=ACTIVE_STATUSES, check_in__lt=end, check_out__gt=start).values(
            "check_in", "check_out", "status"
        )
    )
    series = []
    for i in range(7):
        d = start + timedelta(days=i)
        occupied = sum(1 for b in stays if b["check_in"] <= d < b["check_out"])
        series.append(
            {
                "date": d,
                "occupied": occupied,
                "rate": round(occupied / rooms_total, 3) if rooms_total else 0,
            }
        )
    base = booking_queryset()
    arrivals = base.filter(check_in=start, status=BookingStatus.CONFIRMED)
    # Due out today, or overdue.
    departures = base.filter(check_out__lte=start, status=BookingStatus.CHECKED_IN)
    in_house = base.filter(status=BookingStatus.CHECKED_IN)
    return Response(
        {
            "date": start,
            "rooms_total": rooms_total,
            "occupied": series[0]["occupied"],
            "occupancy_rate": series[0]["rate"],
            "series": series,
            "arrivals": s.BookingSerializer(arrivals, many=True).data,
            "departures": s.BookingSerializer(departures, many=True).data,
            "in_house": s.BookingSerializer(in_house, many=True).data,
        }
    )


class AuditLogView(generics.ListAPIView):
    serializer_class = s.AuditLogSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        if self.request.query_params.get("booking"):
            qs = qs.filter(booking_id=self.request.query_params["booking"])
        return qs


# --- Ops ----------------------------------------------------------------------


@extend_schema(responses=dict)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cur:
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
    return Response({"ok": True, "schema": schema, "rooms": Room.objects.count()})


@extend_schema(exclude=True)
@api_view(["GET", "POST"])
@authentication_classes([])  # the bearer token here is CRON_SECRET, not a JWT
@permission_classes([AllowAny])
@throttle_classes([])
def reset_demo(request):
    """Nightly demo reset, called by Vercel Cron with the CRON_SECRET bearer token."""
    secret = settings.CRON_SECRET
    if not secret or request.headers.get("Authorization") != f"Bearer {secret}":
        return Response({"detail": "Not found."}, status=404)
    from ..seed import seed

    return Response(seed(reset=True))
