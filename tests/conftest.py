from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from hotel.models import Item, Profile, Role, Room, RoomType


def make_user(username: str, role: str):
    user = get_user_model().objects.create_user(username=username, password="pass-" + username, first_name=username.title())
    Profile.objects.create(user=user, role=role)
    return user


def client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        token = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def stay(today):
    return today + timedelta(days=5), today + timedelta(days=8)


@pytest.fixture
def catalogue(db):
    std = RoomType.objects.create(name="Standard", nightly_rate=Decimal("100.00"), capacity=2)
    suite = RoomType.objects.create(name="Suite", nightly_rate=Decimal("250.00"), capacity=4)
    rooms = [Room.objects.create(number=f"10{i}", room_type=std) for i in range(1, 4)]
    rooms.append(Room.objects.create(number="201", room_type=suite))
    coffee = Item.objects.create(name="Coffee", price=Decimal("4.50"))
    cake = Item.objects.create(name="Cake", price=Decimal("7.25"))
    return {"std": std, "suite": suite, "rooms": rooms, "coffee": coffee, "cake": cake}


@pytest.fixture
def guest(db):
    return make_user("guest", Role.GUEST)


@pytest.fixture
def other_guest(db):
    return make_user("other", Role.GUEST)


@pytest.fixture
def staff(db):
    return make_user("staff", Role.STAFF)


@pytest.fixture
def admin(db):
    return make_user("admin", Role.ADMIN)


@pytest.fixture
def anon():
    return client_for(None)


@pytest.fixture
def guest_client(guest):
    return client_for(guest)


@pytest.fixture
def staff_client(staff):
    return client_for(staff)


@pytest.fixture
def admin_client(admin):
    return client_for(admin)
