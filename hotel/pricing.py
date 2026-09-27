"""Pricing rules. Money is Decimal throughout and rounded to cents once, at the end."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CENT = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def nights_between(check_in: date, check_out: date) -> int:
    return (check_out - check_in).days


@dataclass(frozen=True)
class Quote:
    nights: int
    nightly_rate: Decimal
    room_total: Decimal
    service_total: Decimal

    @property
    def total(self) -> Decimal:
        return to_money(self.room_total + self.service_total)

    def as_dict(self) -> dict:
        return {
            "nights": self.nights,
            "nightly_rate": str(to_money(self.nightly_rate)),
            "room_total": str(self.room_total),
            "service_total": str(self.service_total),
            "total": str(self.total),
        }


def quote(nightly_rate: Decimal, nights: int, service_lines: Iterable[tuple[Decimal, int]] = ()) -> Quote:
    """Room rate x nights plus room service lines of (unit_price, quantity)."""
    if nights < 1:
        raise ValueError("a stay is at least one night")
    room_total = to_money(Decimal(nightly_rate) * nights)
    service_total = to_money(sum((Decimal(p) * q for p, q in service_lines), Decimal("0")))
    return Quote(nights=nights, nightly_rate=Decimal(nightly_rate), room_total=room_total, service_total=service_total)


def quote_booking(booking) -> Quote:
    lines = [(o.unit_price, o.quantity) for o in booking.room_service_orders.all()]
    return quote(booking.nightly_rate, booking.nights, lines)
