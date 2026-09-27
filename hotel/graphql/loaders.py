"""Per-request batch loaders (the DataLoader pattern, synchronous).

graphql-core resolves a list depth-first: every field of booking 1 is resolved
before booking 2. A loader therefore cannot wait for sibling keys to arrive the
way the JavaScript DataLoader does with its event-loop tick. Instead, the
resolver that returns a list *primes* the child loaders with the foreign keys
of every row in that list. The first ``load`` then fetches all primed keys in
one ``WHERE id IN (...)`` query and caches the rows for the rest of the request.

Loaders also prime each other: fetching rooms primes the room-type loader, and
fetching room service orders primes the item loader, so a nested query costs one
SQL query per level instead of one per row.
"""

from collections import defaultdict
from typing import Callable, Hashable, Iterable

from django.contrib.auth import get_user_model

from ..models import Bill, Item, Room, RoomServiceOrder, RoomType


class BatchLoader:
    def __init__(self, batch_fn: Callable[[list], dict], default=None):
        self._batch_fn = batch_fn
        self._default = default
        self._cache: dict = {}
        self._pending: set = set()
        self.batches = 0

    def prime(self, keys: Iterable[Hashable]) -> None:
        for k in keys:
            if k is not None and k not in self._cache:
                self._pending.add(k)

    def load(self, key):
        if key is None:
            return None
        if key not in self._cache:
            keys = list(self._pending | {key})
            self._pending.clear()
            found = self._batch_fn(keys)
            self.batches += 1
            for k in keys:
                self._cache[k] = found.get(k, self._default() if callable(self._default) else self._default)
        return self._cache[key]


class Loaders:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.room_type = BatchLoader(self._room_types)
        self.room = BatchLoader(self._rooms)
        self.user = BatchLoader(self._users)
        self.item = BatchLoader(self._items)
        self.orders_by_booking = BatchLoader(self._orders, default=list)
        self.bill_by_booking = BatchLoader(self._bills)

    # Priming entry points used by list resolvers.
    def prime_bookings(self, bookings) -> None:
        if not self.enabled:
            return
        self.room.prime(b.room_id for b in bookings)
        self.user.prime(b.guest_id for b in bookings)
        ids = [b.pk for b in bookings]
        self.orders_by_booking.prime(ids)
        self.bill_by_booking.prime(ids)

    def prime_rooms(self, rooms) -> None:
        if self.enabled:
            self.room_type.prime(r.room_type_id for r in rooms)

    # Batch functions: one query each.
    def _room_types(self, keys):
        return RoomType.objects.in_bulk(keys)

    def _rooms(self, keys):
        rooms = Room.objects.in_bulk(keys)
        self.prime_rooms(rooms.values())
        return rooms

    def _users(self, keys):
        return get_user_model().objects.in_bulk(keys)

    def _items(self, keys):
        return Item.objects.in_bulk(keys)

    def _orders(self, keys):
        grouped = defaultdict(list)
        orders = list(RoomServiceOrder.objects.filter(booking_id__in=keys).order_by("created_at", "id"))
        self.item.prime(o.item_id for o in orders)
        for o in orders:
            grouped[o.booking_id].append(o)
        return grouped

    def _bills(self, keys):
        return {b.booking_id: b for b in Bill.objects.filter(booking_id__in=keys)}
