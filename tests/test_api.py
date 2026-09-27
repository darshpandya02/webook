from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from hotel import pricing
from hotel.models import AuditLog, Bill, Booking, BookingStatus

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db


def book(client, check_in, check_out, **extra):
    body = {"check_in": check_in.isoformat(), "check_out": check_out.isoformat(), **extra}
    return client.post("/api/bookings", body, format="json")


# --- Pricing ----------------------------------------------------------------


def test_quote_is_rate_times_nights_plus_room_service():
    q = pricing.quote(Decimal("129.00"), 3, [(Decimal("6.50"), 2), (Decimal("14.00"), 1)])
    assert q.room_total == Decimal("387.00")
    assert q.service_total == Decimal("27.00")
    assert q.total == Decimal("414.00")


def test_quote_rounds_half_up_to_cents():
    assert pricing.quote(Decimal("33.335"), 1).room_total == Decimal("33.34")


def test_quote_rejects_zero_nights():
    with pytest.raises(ValueError):
        pricing.quote(Decimal("100"), 0)


# --- Availability -----------------------------------------------------------


def test_availability_is_public_and_counts_free_rooms(anon, guest_client, catalogue, stay):
    ci, co = stay
    assert book(guest_client, ci, co, room=catalogue["rooms"][0].pk).status_code == 201
    r = anon.get("/api/availability", {"check_in": ci, "check_out": co, "guests": 1})
    assert r.status_code == 200
    by_name = {row["room_type"]["name"]: row for row in r.json()["results"]}
    assert by_name["Standard"]["total_rooms"] == 3
    assert by_name["Standard"]["available"] == 2
    assert by_name["Standard"]["quote"] == {
        "nights": 3,
        "nightly_rate": "100.00",
        "room_total": "300.00",
        "service_total": "0.00",
        "total": "300.00",
    }


def test_availability_filters_by_capacity(anon, catalogue, stay):
    ci, co = stay
    r = anon.get("/api/availability", {"check_in": ci, "check_out": co, "guests": 3})
    assert [row["room_type"]["name"] for row in r.json()["results"]] == ["Suite"]


def test_availability_half_open_ranges_allow_back_to_back_stays(anon, guest_client, catalogue, stay):
    ci, co = stay
    room = catalogue["rooms"][0]
    assert book(guest_client, ci, co, room=room.pk).status_code == 201
    # A stay starting on the previous guest's check-out day does not clash.
    assert book(guest_client, co, co + timedelta(days=2), room=room.pk).status_code == 201
    assert book(guest_client, ci - timedelta(days=2), ci, room=room.pk).status_code == 201


def test_availability_single_query(anon, catalogue, stay):
    ci, co = stay
    with CaptureQueriesContext(connection) as ctx:
        anon.get("/api/availability", {"check_in": ci, "check_out": co})
    assert len(ctx.captured_queries) == 1


@pytest.mark.parametrize(
    "offsets,message",
    [((3, 3), "after check-in"), ((-1, 2), "past"), ((1, 40), "30 nights"), ((400, 402), "365 days")],
)
def test_availability_validates_dates(anon, catalogue, today, offsets, message):
    r = anon.get(
        "/api/availability",
        {"check_in": today + timedelta(days=offsets[0]), "check_out": today + timedelta(days=offsets[1])},
    )
    assert r.status_code == 400
    assert message in r.json()["detail"]


def test_availability_requires_dates(anon, catalogue):
    assert anon.get("/api/availability").status_code == 400


# --- Booking lifecycle --------------------------------------------------------


def test_book_by_room_type_assigns_a_free_room(guest_client, catalogue, stay):
    ci, co = stay
    numbers = set()
    for _ in range(3):
        r = book(guest_client, ci, co, room_type=catalogue["std"].pk)
        assert r.status_code == 201
        numbers.add(r.json()["room"]["number"])
    assert numbers == {"101", "102", "103"}
    r = book(guest_client, ci, co, room_type=catalogue["std"].pk)
    assert r.status_code == 409
    assert r.json() == {"error": "conflict", "detail": "No rooms of this type left."}


def test_book_rejects_over_capacity(guest_client, catalogue, stay):
    r = book(guest_client, *stay, room_type=catalogue["std"].pk, guests_count=3)
    assert r.status_code == 400
    assert "sleeps at most 2" in r.json()["detail"]


def test_book_requires_exactly_one_of_room_or_type(guest_client, catalogue, stay):
    assert book(guest_client, *stay).status_code == 400
    assert book(guest_client, *stay, room=catalogue["rooms"][0].pk, room_type=catalogue["std"].pk).status_code == 400


def test_rate_is_captured_at_booking_time(guest_client, catalogue, stay):
    r = book(guest_client, *stay, room_type=catalogue["std"].pk)
    catalogue["std"].nightly_rate = Decimal("999.00")
    catalogue["std"].save()
    b = guest_client.get(f"/api/bookings/{r.json()['id']}").json()
    assert b["nightly_rate"] == "100.00"
    assert b["charges"]["room_total"] == "300.00"


def test_cancel_frees_the_room(guest_client, catalogue, stay):
    room = catalogue["rooms"][0]
    first = book(guest_client, *stay, room=room.pk).json()
    assert book(guest_client, *stay, room=room.pk).status_code == 409
    r = guest_client.post(f"/api/bookings/{first['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert book(guest_client, *stay, room=room.pk).status_code == 201
    # Cancelling twice is a conflict, not a silent success.
    assert guest_client.post(f"/api/bookings/{first['id']}/cancel").status_code == 409


def test_full_stay_check_in_room_service_check_out_bill(guest_client, staff_client, catalogue, today):
    b = book(guest_client, today, today + timedelta(days=2), room=catalogue["rooms"][1].pk).json()
    bid = b["id"]

    # Room service needs a checked-in stay.
    assert guest_client.post(f"/api/bookings/{bid}/room-service", {"item": catalogue["coffee"].pk}).status_code == 409

    r = staff_client.post(f"/api/bookings/{bid}/check-in")
    assert r.status_code == 200 and r.json()["status"] == "checked_in"
    assert staff_client.post(f"/api/bookings/{bid}/check-in").status_code == 409

    # Guests may order for their own stay; staff may add to any stay.
    assert guest_client.post(f"/api/bookings/{bid}/room-service", {"item": catalogue["coffee"].pk, "quantity": 2}).status_code == 201
    assert staff_client.post(f"/api/bookings/{bid}/room-service", {"item": catalogue["cake"].pk}).status_code == 201
    assert guest_client.post(f"/api/bookings/{bid}/room-service", {"item": catalogue["cake"].pk, "quantity": 50}).status_code == 400

    running = guest_client.get(f"/api/bookings/{bid}/bill").json()
    assert running["issued"] is None
    assert running["total"] == "216.25"  # 2 x 100.00 + 2 x 4.50 + 7.25

    # A checked-in booking can no longer be cancelled.
    assert guest_client.post(f"/api/bookings/{bid}/cancel").status_code == 409

    r = staff_client.post(f"/api/bookings/{bid}/check-out")
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "checked_out"
    assert out["bill"]["room_total"] == "200.00"
    assert out["bill"]["service_total"] == "16.25"
    assert out["bill"]["total"] == "216.25"
    assert Bill.objects.get(booking_id=bid).total == Decimal("216.25")
    # A checked-out booking no longer holds the room.
    assert book(guest_client, today, today + timedelta(days=2), room=catalogue["rooms"][1].pk).status_code == 201

    assert staff_client.post(f"/api/bookings/{bid}/check-out").status_code == 409


def test_check_in_only_on_or_after_arrival_day(guest_client, staff_client, catalogue, stay):
    b = book(guest_client, *stay, room=catalogue["rooms"][0].pk).json()
    r = staff_client.post(f"/api/bookings/{b['id']}/check-in")
    assert r.status_code == 409
    assert "Check-in opens on" in r.json()["detail"]


def test_audit_log_records_ok_and_rejected_commands(guest_client, staff_client, admin_client, catalogue, today):
    b = book(guest_client, today, today + timedelta(days=1), room=catalogue["rooms"][0].pk).json()
    book(guest_client, today, today + timedelta(days=1), room=catalogue["rooms"][0].pk)  # conflict
    staff_client.post(f"/api/bookings/{b['id']}/check-in")
    staff_client.post(f"/api/bookings/{b['id']}/check-out")
    rows = list(AuditLog.objects.order_by("id").values_list("command", "outcome"))
    assert rows == [
        ("create_booking", "ok"),
        ("create_booking", "rejected"),
        ("check_in", "ok"),
        ("check_out", "ok"),
    ]
    assert AuditLog.objects.get(command="check_out").detail["bill_total"] == "100.00"
    r = admin_client.get("/api/audit-log", {"booking": b["id"]})
    assert r.status_code == 200
    assert [row["command"] for row in r.json()["results"]] == ["check_out", "check_in", "create_booking"]


def test_staff_can_book_on_behalf_of_a_guest(staff_client, guest, catalogue, stay):
    r = book(staff_client, *stay, room=catalogue["rooms"][0].pk, guest=guest.pk)
    assert r.status_code == 201
    assert r.json()["guest"]["username"] == "guest"


def test_booking_list_query_count_is_constant(staff, catalogue, today):
    """The list endpoint preloads relations: the query count does not grow with rows."""
    client = client_for(staff)
    guests = [make_user(f"g{i}", "guest") for i in range(3)]

    def count():
        with CaptureQueriesContext(connection) as ctx:
            assert client.get("/api/bookings").status_code == 200
        return len(ctx.captured_queries)

    Booking.objects.create(guest=guests[0], room=catalogue["rooms"][0], check_in=today, check_out=today + timedelta(days=1), nightly_rate=100)
    small = count()
    for i, room in enumerate(catalogue["rooms"]):
        for w in range(1, 4):
            Booking.objects.create(
                guest=guests[i % 3], room=room, check_in=today + timedelta(days=7 * w), check_out=today + timedelta(days=7 * w + 2), nightly_rate=100
            )
    assert Booking.objects.count() == 13
    assert count() == small


def test_occupancy_dashboard(guest_client, staff_client, catalogue, today):
    b1 = book(guest_client, today, today + timedelta(days=2), room=catalogue["rooms"][0].pk).json()
    book(guest_client, today + timedelta(days=1), today + timedelta(days=3), room=catalogue["rooms"][1].pk)
    staff_client.post(f"/api/bookings/{b1['id']}/check-in")
    d = staff_client.get("/api/dashboard/occupancy").json()
    assert d["rooms_total"] == 4
    assert [p["occupied"] for p in d["series"][:4]] == [1, 2, 1, 0]
    assert d["occupancy_rate"] == 0.25
    assert [b["id"] for b in d["in_house"]] == [b1["id"]]
    assert d["arrivals"] == []  # the only arrival today is already checked in


def test_health_reports_schema(anon, catalogue):
    r = anon.get("/api/health")
    assert r.status_code == 200
    assert r.json()["schema"] == "webook"


def test_openapi_schema_lists_endpoints(anon):
    r = anon.get("/api/schema", {"format": "json"})
    assert r.status_code == 200
    paths = r.json()["paths"]
    for p in ["/api/availability", "/api/bookings", "/api/bookings/{id}/check-out", "/api/dashboard/occupancy"]:
        assert p in paths


def test_demo_reset_requires_cron_secret(anon, settings):
    settings.CRON_SECRET = "s3cret-value"
    assert anon.get("/api/cron/reset-demo").status_code == 404
    anon.credentials(HTTP_AUTHORIZATION="Bearer wrong")
    assert anon.get("/api/cron/reset-demo").status_code == 404
    anon.credentials(HTTP_AUTHORIZATION="Bearer s3cret-value")
    r = anon.get("/api/cron/reset-demo")
    assert r.status_code == 200 and r.json()["rooms"] == 30
