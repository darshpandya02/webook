"""Double-booking under real concurrency.

These tests use transaction=True, so every thread commits on its own Postgres
connection, exactly as separate web requests would. A barrier releases all the
threads at once so their transactions overlap.
"""

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from hotel import commands
from hotel.models import AuditLog, Booking, BookingStatus, Room, RoomType

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db(transaction=True)

THREADS = 20


def fire_in_parallel(n, fn):
    barrier = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        try:
            barrier.wait()
            results[i] = fn(i)
        except Exception as exc:  # recorded and asserted on by the caller
            results[i] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


@pytest.fixture
def hotel(db):
    rt = RoomType.objects.create(name="Standard", nightly_rate=Decimal("100.00"), capacity=2)
    rooms = [Room.objects.create(number=f"10{i}", room_type=rt) for i in range(1, 6)]
    guests = [make_user(f"guest{i}", "guest") for i in range(THREADS)]
    return rt, rooms, guests


def test_parallel_http_bookings_for_same_room_exactly_one_wins(hotel, stay):
    _, rooms, guests = hotel
    ci, co = stay
    clients = [client_for(g) for g in guests]
    body = {"check_in": ci.isoformat(), "check_out": co.isoformat(), "room": rooms[0].pk}

    results = fire_in_parallel(THREADS, lambda i: clients[i].post("/api/bookings", body, format="json"))

    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1, codes
    assert codes.count(409) == THREADS - 1, codes
    assert Booking.objects.filter(room=rooms[0], status=BookingStatus.CONFIRMED).count() == 1
    # Every attempt is audited: one success, the rest rejected.
    assert AuditLog.objects.filter(command="create_booking", outcome="ok").count() == 1
    assert AuditLog.objects.filter(command="create_booking", outcome="rejected").count() == THREADS - 1


def test_parallel_overlapping_but_not_identical_stays(hotel, stay):
    """Different, overlapping date ranges on one room: still only one wins."""
    _, rooms, guests = hotel
    ci, _ = stay

    def attempt(i):
        start = ci + timedelta(days=i % 3)
        cmd = commands.CreateBooking(check_in=start, check_out=start + timedelta(days=3), room=rooms[0].pk)
        return commands.run(cmd, guests[i])

    results = fire_in_parallel(THREADS, attempt)
    wins = [r for r in results if isinstance(r, Booking)]
    losses = [r for r in results if isinstance(r, commands.Conflict)]
    assert len(wins) == 1 and len(losses) == THREADS - 1, results


def test_parallel_room_type_bookings_fill_exactly_the_free_rooms(hotel, stay):
    rt, rooms, guests = hotel
    ci, co = stay

    def attempt(i):
        return commands.run(commands.CreateBooking(check_in=ci, check_out=co, room_type=rt.pk), guests[i])

    results = fire_in_parallel(THREADS, attempt)
    wins = [r for r in results if isinstance(r, Booking)]
    assert len(wins) == len(rooms)
    assert sorted(b.room_id for b in wins) == sorted(r.pk for r in rooms)
    assert all(isinstance(r, commands.Conflict) for r in results if not isinstance(r, Booking))


def test_parallel_bookings_for_different_rooms_all_succeed(hotel, stay):
    _, rooms, guests = hotel
    ci, co = stay
    results = fire_in_parallel(
        len(rooms),
        lambda i: commands.run(commands.CreateBooking(check_in=ci, check_out=co, room=rooms[i].pk), guests[i]),
    )
    assert all(isinstance(r, Booking) for r in results), results


def test_exclusion_constraint_is_the_backstop(hotel, stay):
    """Even code that skips the row lock and the overlap check cannot double-book."""
    _, rooms, guests = hotel
    ci, co = stay
    Booking.objects.create(guest=guests[0], room=rooms[0], check_in=ci, check_out=co, nightly_rate=100)
    with pytest.raises(IntegrityError, match="booking_no_overlap"):
        with transaction.atomic():
            Booking.objects.create(
                guest=guests[1], room=rooms[0], check_in=ci + timedelta(days=1), check_out=co + timedelta(days=1), nightly_rate=100
            )
    # Cancelled bookings do not hold the room.
    Booking.objects.update(status=BookingStatus.CANCELLED)
    Booking.objects.create(guest=guests[1], room=rooms[0], check_in=ci, check_out=co, nightly_rate=100)


def test_parallel_cancel_and_check_in_do_not_both_apply(hotel, today):
    """Row locks serialise conflicting state changes on one booking."""
    _, rooms, guests = hotel
    staff = make_user("desk", "staff")
    b = commands.run(commands.CreateBooking(check_in=today, check_out=today + timedelta(days=2), room=rooms[0].pk), guests[0])

    def attempt(i):
        if i % 2:
            return commands.run(commands.CheckIn(booking=b.pk), staff)
        return commands.run(commands.CancelBooking(booking=b.pk), guests[0])

    results = fire_in_parallel(10, attempt)
    oks = [r for r in results if isinstance(r, Booking)]
    assert len(oks) == 1
    b.refresh_from_db()
    assert b.status in (BookingStatus.CHECKED_IN, BookingStatus.CANCELLED)
