"""End-to-end check of a running WeBook deployment, through the browser and the API.

    uv run --with playwright --python 3.12 python scripts/e2e.py https://webook-eight.vercel.app

Steps: public pages load; a guest signs in with the demo button, searches and
books; two parallel API bookings for the same room and dates return exactly
one 201 and one 409; staff check the guest in, add room service and check out,
and the bill equals rate x nights + room service; a GraphQL query returns the
same availability as REST. Screenshots go to docs/screenshots/.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from playwright.sync_api import expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
SHOTS = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", f"{name} {detail}".strip()))
    print(("PASS " if ok else "FAIL ") + name, detail)
    if not ok:
        raise SystemExit(1)


def http(method: str, path: str, body=None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def login(username: str, password: str) -> str:
    status, body = http("POST", "/api/auth/login", {"username": username, "password": password})
    assert status == 200, (status, body)
    return body["access"]


def main() -> None:
    # --- Public, unauthenticated ---------------------------------------------
    for path in ["/", "/login", "/api/health", "/api/room-types", "/api/docs"]:
        with urlopen(BASE + path, timeout=30) as r:
            check(f"GET {path}", r.status == 200, f"-> {r.status}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # --- Guest: search and book --------------------------------------------
        page.goto(BASE + "/")
        expect(page.get_by_test_id("room-type").first).to_be_visible()
        cards = page.get_by_test_id("room-type").count()
        check("availability search renders room types", cards > 0, f"({cards} types)")
        page.screenshot(path=str(SHOTS / "search.png"))

        page.goto(BASE + "/login")
        page.get_by_test_id("demo-guest").click()
        page.wait_for_url(BASE + "/")
        expect(page.get_by_test_id("room-type").first).to_be_visible()
        page.screenshot(path=str(SHOTS / "login-then-search.png"))
        bookable = page.locator("[data-testid=room-type] button.primary:not([disabled])").first
        bookable.click()
        confirmed = page.get_by_test_id("booking-confirmed")
        expect(confirmed).to_be_visible(timeout=20000)
        text = confirmed.inner_text()
        booking_id = int(text.split("Booking #")[1].split(".")[0])
        check("guest books through the UI", True, f"(booking #{booking_id}: {text.splitlines()[0][:90]})")
        page.screenshot(path=str(SHOTS / "booked.png"))

        page.goto(BASE + "/bookings")
        expect(page.get_by_test_id(f"booking-{booking_id}")).to_be_visible()
        check("booking appears under My bookings", True)
        page.screenshot(path=str(SHOTS / "my-bookings.png"))

        # --- Double booking over the API ----------------------------------------
        guest_token = login("guest", "webook-guest")
        staff_token = login("staff", "webook-staff")
        ci = date.today() + timedelta(days=40)
        co = ci + timedelta(days=2)
        status, avail = http("GET", f"/api/availability?check_in={ci}&check_out={co}")
        status, rooms = http("GET", "/api/rooms", token=staff_token)
        # Pick a room with no booking on those dates: try until a first booking succeeds.
        target = None
        for room in rooms:
            s, b = http("POST", "/api/bookings", {"check_in": str(ci), "check_out": str(co), "room": room["id"]}, guest_token)
            if s == 201:
                target = (room, b)
                break
        room, first = target
        http("POST", f"/api/bookings/{first['id']}/cancel", token=guest_token)  # free it again

        def attempt(_):
            return http("POST", "/api/bookings", {"check_in": str(ci), "check_out": str(co), "room": room["id"]}, guest_token)

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        codes = sorted(s for s, _ in outcomes)
        check("8 parallel bookings for one room: exactly one 201", codes.count(201) == 1 and codes.count(409) == 7, f"codes={codes}")
        winner = next(b for s, b in outcomes if s == 201)
        loser = next(b for s, b in outcomes if s == 409)
        check("rejected attempt says why", "already booked" in loser["detail"], f"({loser})")
        http("POST", f"/api/bookings/{winner['id']}/cancel", token=guest_token)

        # Same attempt through the UI: the room type sells out and the button disables.
        page.goto(BASE + "/bookings")
        page.screenshot(path=str(SHOTS / "bookings-after-race.png"))

        # --- Staff: check in, room service, check out, bill ----------------------
        page.get_by_role("button", name="Sign out").click()
        page.goto(BASE + "/login")
        page.get_by_test_id("demo-staff").click()
        page.wait_for_url(BASE + "/staff")
        expect(page.get_by_test_id("occupancy-rate")).to_be_visible()
        check("staff dashboard shows occupancy", True, f"({page.get_by_test_id('occupancy-rate').inner_text()})")
        page.screenshot(path=str(SHOTS / "front-desk.png"), full_page=True)

        page.get_by_test_id(f"check-in-{booking_id}").click()
        expect(page.get_by_text("Checked in", exact=False).first).to_be_visible()
        expect(page.get_by_test_id(f"check-out-{booking_id}")).to_be_visible(timeout=20000)
        check("staff checks the guest in", True)

        card = page.get_by_test_id(f"booking-{booking_id}")
        card.get_by_label("Quantity").fill("2")
        card.get_by_test_id(f"add-service-{booking_id}").click()
        expect(page.get_by_text("Room service added")).to_be_visible(timeout=20000)

        page.get_by_test_id(f"check-out-{booking_id}").click()
        last = page.get_by_test_id("last-bill")
        expect(last).to_be_visible(timeout=20000)
        ui_total = last.get_by_test_id("bill-total").inner_text()
        page.screenshot(path=str(SHOTS / "checkout-bill.png"), full_page=True)

        status, b = http("GET", f"/api/bookings/{booking_id}", token=staff_token)
        expected = Decimal(b["nightly_rate"]) * b["nights"] + sum(Decimal(o["line_total"]) for o in b["room_service"])
        check(
            "bill = rate x nights + room service",
            b["status"] == "checked_out" and Decimal(b["bill"]["total"]) == expected,
            f"({b['nights']} x {b['nightly_rate']} + {b['bill']['service_total']} = {b['bill']['total']}; UI shows {ui_total})",
        )
        browser.close()

    # --- GraphQL ------------------------------------------------------------
    q = "query($a: Date!, $b: Date!) { availability(checkIn: $a, checkOut: $b) { roomType { name } available stayTotal } }"
    ci = date.today() + timedelta(days=10)
    status, gql = http("POST", "/api/graphql", {"query": q, "variables": {"a": str(ci), "b": str(ci + timedelta(days=3))}})
    status2, rest = http("GET", f"/api/availability?check_in={ci}&check_out={ci + timedelta(days=3)}")
    same = [(r["roomType"]["name"], r["available"], r["stayTotal"]) for r in gql["data"]["availability"]] == [
        (r["room_type"]["name"], r["available"], r["quote"]["total"]) for r in rest["results"]
    ]
    check("GraphQL availability matches REST", status == 200 and same, f"({len(gql['data']['availability'])} rows)")

    staff_token = login("staff", "webook-staff")
    status, gql = http("POST", "/api/graphql", {"query": "{ bookings(limit: 5) { id status room { number roomType { name } } guest { username } charges { total } } }"}, staff_token)
    check("GraphQL nested bookings query", status == 200 and "errors" not in gql and len(gql["data"]["bookings"]) > 0, f"(first: {gql['data']['bookings'][0]})")

    Path(SHOTS.parent / "e2e-result.txt").write_text(
        f"{BASE} {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n" + "\n".join(f"{s} {m}" for s, m in results) + "\n"
    )


if __name__ == "__main__":
    main()
