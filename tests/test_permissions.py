"""Role matrix: anonymous, guest, staff, admin across REST and GraphQL."""

from datetime import timedelta

import pytest

from .conftest import client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def guest_booking(guest_client, catalogue, today):
    r = guest_client.post(
        "/api/bookings",
        {"check_in": today.isoformat(), "check_out": (today + timedelta(days=2)).isoformat(), "room": catalogue["rooms"][0].pk},
        format="json",
    )
    assert r.status_code == 201
    return r.json()


# (method, path, body) -> expected status per role. "{b}" is a guest's booking id.
MATRIX = [
    ("get", "/api/availability?check_in={ci}&check_out={co}", None, {"anon": 200, "guest": 200, "other": 200, "staff": 200, "admin": 200}),
    ("get", "/api/room-types", None, {"anon": 200, "guest": 200, "staff": 200, "admin": 200}),
    ("post", "/api/room-types", {"name": "Loft", "nightly_rate": "300.00"}, {"anon": 401, "guest": 403, "staff": 403, "admin": 201}),
    ("get", "/api/rooms", None, {"anon": 401, "guest": 403, "staff": 200, "admin": 200}),
    ("post", "/api/items", {"name": "Tea", "price": "3.00"}, {"anon": 401, "guest": 403, "staff": 403, "admin": 201}),
    ("get", "/api/employees", None, {"anon": 401, "guest": 403, "staff": 403, "admin": 200}),
    ("get", "/api/bookings", None, {"anon": 401, "guest": 200, "staff": 200, "admin": 200}),
    ("get", "/api/bookings/{b}", None, {"anon": 401, "guest": 200, "other": 404, "staff": 200, "admin": 200}),
    ("get", "/api/bookings/{b}/bill", None, {"anon": 401, "guest": 200, "other": 404, "staff": 200}),
    ("post", "/api/bookings/{b}/check-in", None, {"anon": 401, "guest": 403, "other": 403, "staff": 200}),
    ("post", "/api/bookings/{b}/cancel", None, {"anon": 401, "other": 404, "guest": 200}),
    ("get", "/api/dashboard/occupancy", None, {"anon": 401, "guest": 403, "staff": 200, "admin": 200}),
    ("get", "/api/audit-log", None, {"anon": 401, "guest": 403, "staff": 403, "admin": 200}),
    ("get", "/api/auth/me", None, {"anon": 401, "guest": 200}),
]


@pytest.mark.parametrize("method,path,body,expected", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_role_matrix(method, path, body, expected, guest, other_guest, staff, admin, guest_booking, stay):
    users = {"anon": None, "guest": guest, "other": other_guest, "staff": staff, "admin": admin}
    url = path.format(b=guest_booking["id"], ci=stay[0], co=stay[1])
    for role, status in expected.items():
        r = getattr(client_for(users[role]), method)(url, body, format="json") if body else getattr(client_for(users[role]), method)(url)
        assert r.status_code == status, f"{role} {method} {url}: {r.status_code} {r.content[:200]}"


def test_guest_sees_only_own_bookings(guest_booking, other_guest, staff):
    assert client_for(other_guest).get("/api/bookings").json()["results"] == []
    assert [b["id"] for b in client_for(staff).get("/api/bookings").json()["results"]] == [guest_booking["id"]]


def test_guest_cannot_book_for_someone_else(guest_client, other_guest, catalogue, stay):
    r = guest_client.post(
        "/api/bookings",
        {"check_in": stay[0].isoformat(), "check_out": stay[1].isoformat(), "room": catalogue["rooms"][0].pk, "guest": other_guest.pk},
        format="json",
    )
    assert r.status_code == 403


def test_guest_cannot_order_room_service_on_another_stay(guest_booking, other_guest, staff_client, catalogue):
    staff_client.post(f"/api/bookings/{guest_booking['id']}/check-in")
    r = client_for(other_guest).post(f"/api/bookings/{guest_booking['id']}/room-service", {"item": catalogue["coffee"].pk})
    assert r.status_code == 404


def test_staff_cannot_check_out_without_check_in(guest_booking, staff_client):
    assert staff_client.post(f"/api/bookings/{guest_booking['id']}/check-out").status_code == 409


def test_invalid_and_missing_tokens(anon, catalogue):
    bad = client_for(None)
    bad.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert bad.get("/api/bookings").status_code == 401
    assert anon.get("/api/bookings").status_code == 401
    # Public reads still work without a token.
    assert anon.get("/api/room-types").status_code == 200


def test_login_returns_role_in_token_and_body(anon, staff):
    import jwt

    r = anon.post("/api/auth/login", {"username": "staff", "password": "pass-staff"}, format="json")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "staff"
    claims = jwt.decode(body["access"], options={"verify_signature": False})
    assert claims["role"] == "staff"
    assert anon.post("/api/auth/login", {"username": "staff", "password": "wrong"}, format="json").status_code == 401


def test_register_creates_a_guest(anon):
    r = anon.post(
        "/api/auth/register", {"username": "newbie", "password": "a-long-passphrase", "first_name": "New"}, format="json"
    )
    assert r.status_code == 201 and r.json()["role"] == "guest"
    assert anon.post("/api/auth/register", {"username": "newbie", "password": "a-long-passphrase", "first_name": "N"}, format="json").status_code == 400


# --- GraphQL ------------------------------------------------------------------


def gql(user, query, variables=None, token=None):
    client = client_for(user)
    if token:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client.post("/api/graphql", {"query": query, "variables": variables or {}}, format="json")


def codes(resp):
    return [e.get("extensions", {}).get("code") for e in resp.json().get("errors", [])]


def test_graphql_rooms_is_staff_only(guest, staff, catalogue):
    assert codes(gql(guest, "{ rooms { number } }")) == ["forbidden"]
    assert len(gql(staff, "{ rooms { number } }").json()["data"]["rooms"]) == 4


def test_graphql_bookings_need_auth(catalogue):
    assert codes(gql(None, "{ bookings { id } }")) == ["unauthenticated"]


def test_graphql_guest_cannot_check_in(guest, guest_booking):
    r = gql(guest, "mutation($id: ID!) { checkIn(bookingId: $id) { booking { status } } }", {"id": guest_booking["id"]})
    assert codes(r) == ["forbidden"]


def test_graphql_other_guest_cannot_see_booking(other_guest, guest_booking):
    r = gql(other_guest, "query($id: ID!) { booking(id: $id) { id } }", {"id": guest_booking["id"]})
    assert r.json()["data"]["booking"] is None


def test_graphql_rejects_bad_token(catalogue):
    r = gql(None, "{ roomTypes { name } }", token="garbage")
    assert r.status_code == 401
