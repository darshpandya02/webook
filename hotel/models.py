"""Domain model.

The entities follow the earlier Hotel-Booking-Management schema (customers, room
types, rooms, room service items and orders, bookings, employees, roles), with
the relationships made explicit and the booking invariant enforced in Postgres.
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import F, Func, Q, Value


class Role(models.TextChoices):
    GUEST = "guest", "Guest"
    STAFF = "staff", "Staff"
    ADMIN = "admin", "Admin"


class Profile(models.Model):
    """Application role and guest details for a Django auth user."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.GUEST)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=200, blank=True)

    def __str__(self) -> str:
        return f"{self.user.username} ({self.role})"


class RoomType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    beds = models.PositiveSmallIntegerField(default=1)
    capacity = models.PositiveSmallIntegerField(default=2)
    air_conditioned = models.BooleanField(default=True)
    nightly_rate = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["nightly_rate", "id"]
        constraints = [models.CheckConstraint(condition=Q(nightly_rate__gt=0), name="roomtype_rate_positive")]

    def __str__(self) -> str:
        return self.name


class Room(models.Model):
    number = models.CharField(max_length=10, unique=True)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    floor = models.PositiveSmallIntegerField(default=1)
    size_sqft = models.PositiveIntegerField(default=250)
    is_active = models.BooleanField(default=True, help_text="Inactive rooms are out of service and not bookable.")

    class Meta:
        ordering = ["number"]

    def __str__(self) -> str:
        return f"Room {self.number}"


class Item(models.Model):
    """Room service menu item."""

    name = models.CharField(max_length=80, unique=True)
    category = models.CharField(max_length=40, default="Food")
    price = models.DecimalField(max_digits=8, decimal_places=2)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [models.CheckConstraint(condition=Q(price__gt=0), name="item_price_positive")]

    def __str__(self) -> str:
        return self.name


class EmployeeRole(models.Model):
    name = models.CharField(max_length=60, unique=True)
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Employee(models.Model):
    full_name = models.CharField(max_length=100)
    role = models.ForeignKey(EmployeeRole, on_delete=models.PROTECT, related_name="employees")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="employee"
    )
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    hired_on = models.DateField()

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return self.full_name


class BookingStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Confirmed"
    CHECKED_IN = "checked_in", "Checked in"
    CHECKED_OUT = "checked_out", "Checked out"
    CANCELLED = "cancelled", "Cancelled"


# Statuses that hold a room for their date range.
ACTIVE_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN)


class Booking(models.Model):
    guest = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="bookings")
    check_in = models.DateField()
    check_out = models.DateField()
    guests_count = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=12, choices=BookingStatus.choices, default=BookingStatus.CONFIRMED)
    # Rate captured at booking time so later price changes do not alter the bill.
    nightly_rate = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-check_in", "-id"]
        indexes = [
            models.Index(fields=["room", "check_in", "check_out"], name="booking_room_dates"),
            models.Index(fields=["guest", "-check_in"], name="booking_guest"),
            models.Index(fields=["status", "check_in"], name="booking_status_checkin"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(check_out__gt=F("check_in")), name="booking_dates_ordered"),
            models.CheckConstraint(condition=Q(guests_count__gte=1), name="booking_guests_positive"),
            # No two active bookings may hold the same room on overlapping nights.
            # int8range(room_id, room_id, '[]') turns the equality into a range
            # overlap, so the constraint needs only core GiST range support and
            # no btree_gist extension. daterange(check_in, check_out) is
            # half-open ('[)'), so a check-out and a same-day check-in do not clash.
            ExclusionConstraint(
                name="booking_no_overlap",
                index_type="GIST",
                expressions=[
                    (
                        Func(F("room_id"), F("room_id"), Value("[]"), function="int8range"),
                        RangeOperators.OVERLAPS,
                    ),
                    (
                        Func(F("check_in"), F("check_out"), Value("[)"), function="daterange"),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status__in=[s.value for s in ACTIVE_STATUSES]),
                violation_error_message="Room is already booked for these dates.",
            ),
        ]

    def __str__(self) -> str:
        return f"Booking {self.pk} room {self.room_id} {self.check_in}..{self.check_out}"

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


class RoomServiceOrder(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="room_service_orders")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="orders")
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    ordered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name="order_quantity_positive")]

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class Bill(models.Model):
    """Final bill issued at check-out. One per booking."""

    booking = models.OneToOneField(Booking, on_delete=models.PROTECT, related_name="bill")
    nights = models.PositiveSmallIntegerField()
    room_total = models.DecimalField(max_digits=12, decimal_places=2)
    service_total = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")


class AuditLog(models.Model):
    """Append-only record of every booking command, successful or rejected."""

    command = models.CharField(max_length=40)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    booking = models.ForeignKey(Booking, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit")
    outcome = models.CharField(max_length=10)  # "ok" or "rejected"
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["booking", "created_at"], name="audit_booking")]
