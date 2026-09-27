"""Availability search.

One SQL query returns, per room type, how many active rooms have no active
booking overlapping the requested stay:

    SELECT room_type.*, COUNT(room.id) FILTER (WHERE NOT EXISTS (overlap)) ...
    GROUP BY room_type.id
"""

from datetime import date

from django.db.models import Count, Exists, OuterRef, Q

from . import pricing
from .commands import overlapping
from .models import Booking, Room, RoomType


def available_rooms(check_in: date, check_out: date, room_type_id: int | None = None):
    clash = overlapping(Booking.objects.filter(room=OuterRef("pk")), check_in, check_out)
    qs = Room.objects.filter(is_active=True).exclude(Exists(clash)).select_related("room_type")
    if room_type_id:
        qs = qs.filter(room_type_id=room_type_id)
    return qs


def search(check_in: date, check_out: date, guests: int = 1) -> list[dict]:
    clash = overlapping(Booking.objects.filter(room=OuterRef("rooms__pk")), check_in, check_out)
    types = (
        RoomType.objects.filter(capacity__gte=guests)
        .annotate(
            total_rooms=Count("rooms", filter=Q(rooms__is_active=True)),
            available=Count("rooms", filter=Q(rooms__is_active=True) & ~Exists(clash)),
        )
        .order_by("nightly_rate", "id")
    )
    nights = pricing.nights_between(check_in, check_out)
    out = []
    for t in types:
        q = pricing.quote(t.nightly_rate, nights)
        out.append(
            {
                "room_type": {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "beds": t.beds,
                    "capacity": t.capacity,
                    "air_conditioned": t.air_conditioned,
                    "nightly_rate": str(t.nightly_rate),
                },
                "total_rooms": t.total_rooms,
                "available": t.available,
                "quote": q.as_dict(),
            }
        )
    return out
