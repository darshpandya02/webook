"""Count SQL queries for one nested GraphQL query, with and without the batch loaders.

Runs against the configured database inside a transaction that is rolled back,
so nothing is left behind. Usage: uv run python scripts/measure_queries.py
"""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webook.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.test import RequestFactory  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402

from hotel.graphql.loaders import Loaders  # noqa: E402
from hotel.graphql.schema import schema  # noqa: E402
from hotel.models import Booking, Item, Profile, Room, RoomServiceOrder  # noqa: E402

QUERY = """
{ bookings(limit: 200) {
    id status
    room { number roomType { name } }
    guest { username }
    roomService { quantity item { name } }
    bill { total }
    charges { total }
} }
"""


class Rollback(Exception):
    pass


def run(n: int) -> dict:
    out = {}
    try:
        with transaction.atomic():
            # A fresh guest sees only their own bookings, so the seeded rows do not count.
            User = get_user_model()
            guest = User.objects.create(username="__measure_guest")
            Profile.objects.create(user=guest, role="guest")
            rooms = list(Room.objects.filter(is_active=True))
            items = list(Item.objects.all()[:2])
            today = timezone.localdate() + timedelta(days=1000)  # clear of the demo bookings
            for i in range(n):
                room = rooms[i % len(rooms)]
                week = i // len(rooms)
                b = Booking.objects.create(
                    guest=guest, room=room, check_in=today + timedelta(days=3 * week),
                    check_out=today + timedelta(days=3 * week + 2), nightly_rate=room.room_type.nightly_rate,
                )
                for it in items:
                    RoomServiceOrder.objects.create(booking=b, item=it, quantity=1, unit_price=it.price, ordered_by=guest)
            for enabled in (True, False):
                request = RequestFactory().post("/api/graphql")
                request.user = User.objects.get(pk=guest.pk)
                request.loaders = Loaders(enabled=enabled)
                with CaptureQueriesContext(connection) as ctx:
                    result = schema.execute(QUERY, context_value=request)
                assert result.errors is None, result.errors
                assert len(result.data["bookings"]) == n
                out["with_loaders" if enabled else "without_loaders"] = len(ctx.captured_queries)
            raise Rollback
    except Rollback:
        pass
    return {"bookings": n, "order_lines_per_booking": 2, **out}


if __name__ == "__main__":
    rows = [run(n) for n in (10, 50, 200)]
    for r in rows:
        print(r)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/graphql_query_counts.json").write_text(json.dumps(rows, indent=2) + "\n")
