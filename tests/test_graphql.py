from datetime import timedelta

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from hotel.graphql.loaders import Loaders
from hotel.graphql.schema import schema
from hotel.models import Booking, BookingStatus, RoomServiceOrder

from .conftest import make_user
from .test_permissions import codes, gql

pytestmark = pytest.mark.django_db

NESTED = """
{ bookings(limit: 200) {
    id status nights
    room { number roomType { name nightlyRate } }
    guest { username fullName }
    roomService { quantity lineTotal item { name } }
    bill { total }
    charges { total }
} }
"""


def test_availability_query_matches_rest(anon, catalogue, stay):
    ci, co = stay
    r = gql(None, "query($a: Date!, $b: Date!) { availability(checkIn: $a, checkOut: $b) { roomType { name } available totalRooms stayTotal } }", {"a": ci.isoformat(), "b": co.isoformat()})
    data = r.json()["data"]["availability"]
    rest = anon.get("/api/availability", {"check_in": ci, "check_out": co}).json()["results"]
    assert [(d["roomType"]["name"], d["available"], d["stayTotal"]) for d in data] == [
        (x["room_type"]["name"], x["available"], x["quote"]["total"]) for x in rest
    ]


def test_availability_query_validates_dates(catalogue, today):
    r = gql(None, "query($a: Date!) { availability(checkIn: $a, checkOut: $a) { available } }", {"a": today.isoformat()})
    assert codes(r) == ["invalid"]


def test_mutations_run_the_same_commands(guest, staff, catalogue, today):
    create = """mutation($a: Date!, $b: Date!, $t: ID!) {
      createBooking(checkIn: $a, checkOut: $b, roomTypeId: $t) { booking { id status room { number } charges { total } } } }"""
    r = gql(guest, create, {"a": today.isoformat(), "b": (today + timedelta(days=2)).isoformat(), "t": catalogue["std"].pk})
    booking = r.json()["data"]["createBooking"]["booking"]
    assert booking["status"] == "confirmed" and booking["charges"]["total"] == "200.00"
    bid = booking["id"]

    r = gql(staff, "mutation($id: ID!) { checkIn(bookingId: $id) { booking { status } } }", {"id": bid})
    assert r.json()["data"]["checkIn"]["booking"]["status"] == "checked_in"

    r = gql(guest, "mutation($id: ID!, $i: ID!) { addRoomService(bookingId: $id, itemId: $i, quantity: 2) { booking { charges { serviceTotal total } } } }", {"id": bid, "i": catalogue["cake"].pk})
    assert r.json()["data"]["addRoomService"]["booking"]["charges"] == {"serviceTotal": "14.50", "total": "214.50"}

    r = gql(staff, "mutation($id: ID!) { checkOut(bookingId: $id) { booking { status bill { roomTotal serviceTotal total } } } }", {"id": bid})
    out = r.json()["data"]["checkOut"]["booking"]
    assert out == {"status": "checked_out", "bill": {"roomTotal": "200.00", "serviceTotal": "14.50", "total": "214.50"}}


def test_graphql_double_booking_is_a_conflict(guest, other_guest, catalogue, stay):
    q = "mutation($a: Date!, $b: Date!, $r: ID!) { createBooking(checkIn: $a, checkOut: $b, roomId: $r) { booking { id } } }"
    v = {"a": stay[0].isoformat(), "b": stay[1].isoformat(), "r": catalogue["rooms"][0].pk}
    assert "errors" not in gql(guest, q, v).json()
    assert codes(gql(other_guest, q, v)) == ["conflict"]


# --- N+1 ----------------------------------------------------------------------


def seed_bookings(catalogue, n):
    guests = [make_user(f"n{i}", "guest") for i in range(5)]
    staff = make_user("nstaff", "staff")
    rooms = catalogue["rooms"]
    items = [catalogue["coffee"], catalogue["cake"]]
    made = 0
    week = 0
    while made < n:
        for room in rooms:
            if made >= n:
                break
            b = Booking.objects.create(
                guest=guests[made % 5],
                room=room,
                check_in=_day(3 * week),
                check_out=_day(3 * week + 2),
                nightly_rate=room.room_type.nightly_rate,
                status=BookingStatus.CHECKED_IN if made % 2 else BookingStatus.CONFIRMED,
            )
            for j in range(2):
                RoomServiceOrder.objects.create(booking=b, item=items[j], quantity=1, unit_price=items[j].price, ordered_by=staff)
            made += 1
        week += 1
    return staff


def _day(offset):
    from django.utils import timezone

    return timezone.localdate() + timedelta(days=offset)


def count_queries(user, enabled: bool) -> tuple[int, int]:
    request = RequestFactory().post("/api/graphql")
    request.user = user
    request.loaders = Loaders(enabled=enabled)
    with CaptureQueriesContext(connection) as ctx:
        result = schema.execute(NESTED, context_value=request)
    assert result.errors is None, result.errors
    return len(ctx.captured_queries), len(result.data["bookings"])


@pytest.mark.parametrize("n", [10, 40])
def test_loaders_keep_query_count_constant(catalogue, n):
    staff = seed_bookings(catalogue, n)
    with_loaders, rows = count_queries(staff, enabled=True)
    without, _ = count_queries(staff, enabled=False)
    assert rows == n
    # bookings, rooms, room types, users, orders, items, bills (the role is cached on the user)
    assert with_loaders == 7, with_loaders
    # The bookings query, then per booking: room, room type, guest, orders twice
    # (roomService and charges), bill, and one item per order line (two here).
    assert without == 1 + n * 8, without


def test_loader_results_match_naive_results(catalogue):
    staff = seed_bookings(catalogue, 12)
    outputs = []
    for enabled in (True, False):
        request = RequestFactory().post("/api/graphql")
        request.user = staff
        request.loaders = Loaders(enabled=enabled)
        outputs.append(schema.execute(NESTED, context_value=request).data)
    assert outputs[0] == outputs[1]
