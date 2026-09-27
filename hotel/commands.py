"""Booking operations as Command objects.

Every state change to a booking goes through a Command: CreateBooking,
CancelBooking, CheckIn, CheckOut and AddRoomService. The REST views and the
GraphQL mutations only build a command and hand it to ``run``; they contain no
business rules of their own, so both APIs behave identically.

``run`` executes the command inside one database transaction and writes an
AuditLog row in that same transaction. If the command is rejected, the
transaction rolls back and a "rejected" audit row is written on its own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, ClassVar, Optional

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import pricing
from .models import (
    ACTIVE_STATUSES,
    AuditLog,
    Bill,
    Booking,
    BookingStatus,
    Item,
    Role,
    Room,
    RoomServiceOrder,
)
from .roles import role_of

MAX_NIGHTS = 30
MAX_DAYS_AHEAD = 365
MAX_ITEM_QUANTITY = 20


# --- Errors -------------------------------------------------------------------


class DomainError(Exception):
    status = 400
    code = "invalid"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationFailed(DomainError):
    status, code = 400, "invalid"


class Forbidden(DomainError):
    status, code = 403, "forbidden"


class NotFound(DomainError):
    status, code = 404, "not_found"


class Conflict(DomainError):
    status, code = 409, "conflict"


# --- Base ---------------------------------------------------------------------


class Command:
    name: ClassVar[str]

    def execute(self, actor) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def audit_detail(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in asdict(self).items()}

    def booking_id(self) -> Optional[int]:
        return getattr(self, "booking", None)


def run(command: Command, actor):
    """Invoke a command: one transaction, one audit row."""
    try:
        with transaction.atomic():
            result = command.execute(actor)
            booking = result if isinstance(result, Booking) else getattr(result, "booking", None)
            AuditLog.objects.create(
                command=command.name,
                actor=actor if actor and actor.is_authenticated else None,
                booking=booking,
                outcome="ok",
                detail=command.audit_detail(),
            )
        return result
    except DomainError as exc:
        booking_id = command.booking_id()
        AuditLog.objects.create(
            command=command.name,
            actor=actor if actor and actor.is_authenticated else None,
            booking_id=booking_id if booking_id and Booking.objects.filter(pk=booking_id).exists() else None,
            outcome="rejected",
            detail={**command.audit_detail(), "error": exc.code, "message": exc.message},
        )
        raise


# --- Helpers ------------------------------------------------------------------


def _require_authenticated(actor) -> str:
    if actor is None or not actor.is_authenticated:
        raise Forbidden("Sign in first.")
    return role_of(actor)


def _require_staff(actor) -> str:
    role = _require_authenticated(actor)
    if role not in (Role.STAFF, Role.ADMIN):
        raise Forbidden("Staff only.")
    return role


def _load_booking_for_update(booking_id: int) -> Booking:
    try:
        return Booking.objects.select_for_update().select_related("room").get(pk=booking_id)
    except Booking.DoesNotExist:
        raise NotFound("Booking not found.")


def _check_owner_or_staff(actor, booking: Booking) -> None:
    role = _require_authenticated(actor)
    if role == Role.GUEST and booking.guest_id != actor.pk:
        # Do not reveal that someone else's booking exists.
        raise NotFound("Booking not found.")


def validate_stay(check_in: date, check_out: date, today: Optional[date] = None) -> None:
    today = today or timezone.localdate()
    if check_out <= check_in:
        raise ValidationFailed("Check-out must be after check-in.")
    if check_in < today:
        raise ValidationFailed("Check-in cannot be in the past.")
    if (check_out - check_in).days > MAX_NIGHTS:
        raise ValidationFailed(f"Stays are limited to {MAX_NIGHTS} nights.")
    if check_in > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationFailed(f"Bookings open {MAX_DAYS_AHEAD} days ahead.")


def overlapping(qs, check_in: date, check_out: date):
    """Active bookings whose [check_in, check_out) overlaps the given stay."""
    return qs.filter(status__in=ACTIVE_STATUSES, check_in__lt=check_out, check_out__gt=check_in)


# --- Commands -----------------------------------------------------------------


@dataclass
class CreateBooking(Command):
    name: ClassVar[str] = "create_booking"

    check_in: date
    check_out: date
    guests_count: int = 1
    room: Optional[int] = None
    room_type: Optional[int] = None
    guest: Optional[int] = None  # staff may book on behalf of a guest

    def booking_id(self) -> Optional[int]:
        return None

    def execute(self, actor) -> Booking:
        role = _require_authenticated(actor)
        validate_stay(self.check_in, self.check_out)
        if self.guests_count < 1:
            raise ValidationFailed("At least one guest.")
        if (self.room is None) == (self.room_type is None):
            raise ValidationFailed("Give exactly one of room or room_type.")

        guest = actor
        if self.guest is not None and self.guest != actor.pk:
            if role == Role.GUEST:
                raise Forbidden("Guests can only book for themselves.")
            guest = get_user_model().objects.filter(pk=self.guest).first()
            if guest is None:
                raise NotFound("Guest not found.")

        # Lock the candidate room rows. A concurrent booking for the same room
        # waits here until this transaction commits, then sees its row in the
        # overlap check below. The exclusion constraint is the backstop.
        candidates = Room.objects.select_for_update().filter(is_active=True).select_related("room_type")
        if self.room is not None:
            candidates = candidates.filter(pk=self.room)
        else:
            candidates = candidates.filter(room_type_id=self.room_type)
        rooms = list(candidates.order_by("number"))
        if not rooms:
            raise NotFound("Room not found.")
        if rooms[0].room_type.capacity < self.guests_count:
            raise ValidationFailed(f"{rooms[0].room_type.name} sleeps at most {rooms[0].room_type.capacity}.")

        taken = set(
            overlapping(Booking.objects.filter(room__in=rooms), self.check_in, self.check_out).values_list(
                "room_id", flat=True
            )
        )
        free = [r for r in rooms if r.pk not in taken]
        if not free:
            raise Conflict("Room is already booked for these dates." if self.room else "No rooms of this type left.")
        room = free[0]

        try:
            with transaction.atomic():
                booking = Booking.objects.create(
                    guest=guest,
                    room=room,
                    check_in=self.check_in,
                    check_out=self.check_out,
                    guests_count=self.guests_count,
                    nightly_rate=room.room_type.nightly_rate,
                )
        except IntegrityError as exc:
            if "booking_no_overlap" in str(exc):
                raise Conflict("Room is already booked for these dates.")
            raise
        self.room = room.pk
        return booking


@dataclass
class CancelBooking(Command):
    name: ClassVar[str] = "cancel_booking"
    booking: int

    def execute(self, actor) -> Booking:
        booking = _load_booking_for_update(self.booking)
        _check_owner_or_staff(actor, booking)
        if booking.status != BookingStatus.CONFIRMED:
            raise Conflict(f"A {booking.get_status_display().lower()} booking cannot be cancelled.")
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=["status", "cancelled_at"])
        return booking


@dataclass
class CheckIn(Command):
    name: ClassVar[str] = "check_in"
    booking: int

    def execute(self, actor) -> Booking:
        _require_staff(actor)
        booking = _load_booking_for_update(self.booking)
        if booking.status != BookingStatus.CONFIRMED:
            raise Conflict(f"Booking is {booking.get_status_display().lower()}, not confirmed.")
        today = timezone.localdate()
        if today < booking.check_in:
            raise Conflict(f"Check-in opens on {booking.check_in.isoformat()}.")
        if today >= booking.check_out:
            raise Conflict("The stay has already ended.")
        booking.status = BookingStatus.CHECKED_IN
        booking.checked_in_at = timezone.now()
        booking.save(update_fields=["status", "checked_in_at"])
        return booking


@dataclass
class AddRoomService(Command):
    name: ClassVar[str] = "add_room_service"
    booking: int
    item: int
    quantity: int = 1

    def execute(self, actor) -> RoomServiceOrder:
        booking = _load_booking_for_update(self.booking)
        _check_owner_or_staff(actor, booking)
        if booking.status != BookingStatus.CHECKED_IN:
            raise Conflict("Room service is only for checked-in guests.")
        if not 1 <= self.quantity <= MAX_ITEM_QUANTITY:
            raise ValidationFailed(f"Quantity must be 1 to {MAX_ITEM_QUANTITY}.")
        item = Item.objects.filter(pk=self.item, is_available=True).first()
        if item is None:
            raise NotFound("Item not available.")
        return RoomServiceOrder.objects.create(
            booking=booking, item=item, quantity=self.quantity, unit_price=item.price, ordered_by=actor
        )


@dataclass
class CheckOut(Command):
    name: ClassVar[str] = "check_out"
    booking: int
    bill_total: Optional[str] = field(default=None)

    def execute(self, actor) -> Bill:
        _require_staff(actor)
        booking = _load_booking_for_update(self.booking)
        if booking.status != BookingStatus.CHECKED_IN:
            raise Conflict(f"Booking is {booking.get_status_display().lower()}, not checked in.")
        q = pricing.quote_booking(booking)
        booking.status = BookingStatus.CHECKED_OUT
        booking.checked_out_at = timezone.now()
        booking.save(update_fields=["status", "checked_out_at"])
        bill = Bill.objects.create(
            booking=booking,
            nights=q.nights,
            room_total=q.room_total,
            service_total=q.service_total,
            total=q.total,
            issued_by=actor,
        )
        self.bill_total = str(q.total)
        return bill
