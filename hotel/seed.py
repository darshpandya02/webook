"""Demo data. Idempotent: running it again restores the demo to a known state,
with bookings placed relative to today so the staff dashboard always has
arrivals, departures and in-house guests."""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from . import pricing
from .models import (
    AuditLog,
    Bill,
    Booking,
    BookingStatus,
    Employee,
    EmployeeRole,
    Item,
    Profile,
    Role,
    Room,
    RoomServiceOrder,
    RoomType,
)

DEMO_USERS = [
    # username, password, role, first, last
    ("guest", "webook-guest", Role.GUEST, "Grace", "Guest"),
    ("staff", "webook-staff", Role.STAFF, "Sam", "Frontdesk"),
    ("admin", "webook-admin", Role.ADMIN, "Ada", "Admin"),
]

# Room types follow the earlier project's five room types, with a family suite added.
ROOM_TYPES = [
    ("Standard Double", "Two single beds, a wardrobe and an outward-facing window.", 2, 2, "129.00"),
    ("Pool View Double", "Two single beds, a wardrobe and a pool-facing window.", 2, 2, "149.00"),
    ("Valley View Double", "Two single beds, a wardrobe and a valley-facing window.", 2, 2, "169.00"),
    ("Deluxe Pool View", "Deluxe double room with a queen bed and a pool-facing balcony.", 1, 2, "209.00"),
    ("Deluxe Valley View", "Deluxe double room with a queen bed and a valley-facing balcony.", 1, 2, "229.00"),
    ("Family Suite", "Two rooms, a queen bed and two singles, sleeps four.", 3, 4, "319.00"),
]
ROOMS_PER_TYPE = [8, 6, 5, 4, 4, 3]  # 30 rooms

ITEMS = [
    ("Chocolate Ice Cream", "Dessert", "6.50"),
    ("Cheesecake", "Dessert", "8.00"),
    ("Club Sandwich", "Food", "14.00"),
    ("Margherita Pizza", "Food", "18.00"),
    ("Caesar Salad", "Food", "12.50"),
    ("Continental Breakfast", "Food", "19.00"),
    ("Fresh Orange Juice", "Drinks", "5.50"),
    ("Coffee Pot", "Drinks", "7.00"),
    ("Sparkling Water", "Drinks", "4.00"),
    ("Laundry Bag", "Services", "25.00"),
]

EMPLOYEE_ROLES = [("Manager", "95000"), ("Front Desk", "42000"), ("Housekeeping", "36000"), ("Chef", "58000")]
EMPLOYEES = [
    ("Samuel Johnson", "Manager", "95000", 2019),
    ("Priya Nair", "Front Desk", "43500", 2022),
    ("Luis Ortega", "Front Desk", "42000", 2024),
    ("Mei Chen", "Housekeeping", "37000", 2021),
    ("Tom Walsh", "Chef", "61000", 2020),
]

EXTRA_GUESTS = [
    ("oliver", "Oliver", "Brooks"),
    ("amara", "Amara", "Okafor"),
    ("kenji", "Kenji", "Watanabe"),
    ("sofia", "Sofia", "Rossi"),
    ("liam", "Liam", "Murphy"),
    ("zara", "Zara", "Khan"),
]


def _user(username, password, role, first, last):
    User = get_user_model()
    user, _ = User.objects.get_or_create(username=username)
    user.first_name, user.last_name = first, last
    user.email = f"{username}@example.com"
    user.set_password(password)
    user.is_active = True
    user.save()
    Profile.objects.update_or_create(user=user, defaults={"role": role})
    return user


@transaction.atomic
def seed(reset: bool = True) -> dict:
    rng = random.Random(2026)
    today = timezone.localdate()
    User = get_user_model()

    if reset:
        AuditLog.objects.all().delete()
        Bill.objects.all().delete()
        RoomServiceOrder.objects.all().delete()
        Booking.objects.all().delete()
        keep = [u[0] for u in DEMO_USERS] + [g[0] for g in EXTRA_GUESTS]
        User.objects.exclude(username__in=keep).delete()

    users = {u[0]: _user(*u) for u in DEMO_USERS}
    # Extra guests have no usable password; they exist only to fill the hotel.
    guests = [users["guest"]] + [
        _user(name, None, Role.GUEST, first, last) for name, first, last in EXTRA_GUESTS
    ]

    types = []
    for name, desc, beds, cap, rate in ROOM_TYPES:
        rt, _ = RoomType.objects.update_or_create(
            name=name,
            defaults={"description": desc, "beds": beds, "capacity": cap, "air_conditioned": True, "nightly_rate": Decimal(rate)},
        )
        types.append(rt)
    RoomType.objects.exclude(name__in=[t[0] for t in ROOM_TYPES]).filter(rooms__isnull=True).delete()

    rooms = []
    n = 0
    for rt, count in zip(types, ROOMS_PER_TYPE):
        for _ in range(count):
            floor = 1 + n // 10
            number = f"{floor}{(n % 10) + 1:02d}"
            room, _ = Room.objects.update_or_create(
                number=number,
                defaults={"room_type": rt, "floor": floor, "size_sqft": 240 + 40 * types.index(rt), "is_active": True},
            )
            rooms.append(room)
            n += 1
    Room.objects.exclude(pk__in=[r.pk for r in rooms]).update(is_active=False)

    items = []
    for name, cat, price in ITEMS:
        it, _ = Item.objects.update_or_create(name=name, defaults={"category": cat, "price": Decimal(price), "is_available": True})
        items.append(it)

    roles = {}
    for name, sal in EMPLOYEE_ROLES:
        roles[name], _ = EmployeeRole.objects.update_or_create(name=name, defaults={"base_salary": Decimal(sal)})
    for full_name, role, sal, year in EMPLOYEES:
        Employee.objects.update_or_create(
            full_name=full_name,
            defaults={"role": roles[role], "salary": Decimal(sal), "hired_on": today.replace(year=year, month=3, day=1)},
        )
    Employee.objects.filter(full_name="Priya Nair").update(user=users["staff"])
    Employee.objects.filter(full_name="Samuel Johnson").update(user=users["admin"])

    staff = users["staff"]
    now = timezone.now()
    made = {"checked_out": 0, "in_house": 0, "due_out_today": 0, "arrivals_today": 0, "upcoming": 0}

    def book(guest, room, start, nights, status):
        b = Booking.objects.create(
            guest=guest,
            room=room,
            check_in=start,
            check_out=start + timedelta(days=nights),
            guests_count=min(2, room.room_type.capacity),
            nightly_rate=room.room_type.nightly_rate,
            status=status,
        )
        if status in (BookingStatus.CHECKED_IN, BookingStatus.CHECKED_OUT):
            b.checked_in_at = now - timedelta(days=max(1, (today - start).days))
            for _ in range(rng.randint(1, 3)):
                it = rng.choice(items)
                RoomServiceOrder.objects.create(booking=b, item=it, quantity=rng.randint(1, 2), unit_price=it.price, ordered_by=staff)
        if status == BookingStatus.CHECKED_OUT:
            b.checked_out_at = now - timedelta(days=max(0, (today - b.check_out).days))
            q = pricing.quote_booking(b)
            Bill.objects.create(booking=b, nights=q.nights, room_total=q.room_total, service_total=q.service_total, total=q.total, issued_by=staff)
        b.save()
        return b

    pool = rooms[:]
    rng.shuffle(pool)
    # Past stays, already billed.
    for i in range(6):
        book(guests[i % len(guests)], pool[i], today - timedelta(days=12 - i), 2 + i % 3, BookingStatus.CHECKED_OUT)
        made["checked_out"] += 1
    # In-house guests: arrived earlier, leaving later.
    for i in range(6, 12):
        book(guests[(i + 1) % len(guests)], pool[i], today - timedelta(days=1 + i % 2), 3 + i % 3, BookingStatus.CHECKED_IN)
        made["in_house"] += 1
    # Due to check out today.
    for i in range(12, 14):
        book(guests[(i + 2) % len(guests)], pool[i], today - timedelta(days=2), 2, BookingStatus.CHECKED_IN)
        made["due_out_today"] += 1
    # Arriving today, not yet checked in (the demo guest has one of these).
    for i in range(14, 18):
        book(guests[0] if i == 14 else guests[i % len(guests)], pool[i], today, 2 + i % 2, BookingStatus.CONFIRMED)
        made["arrivals_today"] += 1
    # Upcoming reservations.
    for i in range(18, 24):
        book(guests[i % len(guests)], pool[i], today + timedelta(days=3 + i % 5), 2 + i % 4, BookingStatus.CONFIRMED)
        made["upcoming"] += 1
    return {"rooms": len(rooms), "room_types": len(types), "items": len(items), "bookings": made}
