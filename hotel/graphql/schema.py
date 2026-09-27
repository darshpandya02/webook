"""GraphQL schema. Same domain and rules as the REST API: reads share the
selectors, writes go through the same Command objects."""

from datetime import date

import graphene
from graphene_django import DjangoObjectType
from graphql import GraphQLError

from .. import availability, commands, pricing
from ..models import Bill, Booking, Item, Room, RoomServiceOrder, RoomType
from ..roles import is_staff_role, role_of
from .loaders import Loaders


def _loaders(info) -> Loaders:
    ctx = info.context
    loaders = getattr(ctx, "loaders", None)
    if loaders is None:
        loaders = Loaders()
        ctx.loaders = loaders
    return loaders


def _user(info):
    return getattr(info.context, "user", None)


def _domain(fn):
    """Turn a command's DomainError into a GraphQL error with a machine-readable code."""

    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except commands.DomainError as exc:
            raise GraphQLError(exc.message, extensions={"code": exc.code, "status": exc.status})

    return wrapper


# --- Types --------------------------------------------------------------------


class RoomTypeType(DjangoObjectType):
    class Meta:
        model = RoomType
        name = "RoomType"
        fields = ("id", "name", "description", "beds", "capacity", "air_conditioned", "nightly_rate")


class RoomNode(DjangoObjectType):
    class Meta:
        model = Room
        name = "Room"
        fields = ("id", "number", "floor", "size_sqft", "is_active")

    room_type = graphene.Field(RoomTypeType, required=True)

    def resolve_room_type(root: Room, info):
        loaders = _loaders(info)
        return loaders.room_type.load(root.room_type_id) if loaders.enabled else root.room_type


class ItemType(DjangoObjectType):
    class Meta:
        model = Item
        name = "Item"
        fields = ("id", "name", "category", "price", "is_available")


class GuestType(graphene.ObjectType):
    class Meta:
        name = "Guest"

    id = graphene.ID(required=True)
    username = graphene.String(required=True)
    full_name = graphene.String(required=True)

    def resolve_full_name(root, info):
        return root.get_full_name() or root.username


class RoomServiceOrderType(DjangoObjectType):
    class Meta:
        model = RoomServiceOrder
        name = "RoomServiceOrder"
        fields = ("id", "quantity", "unit_price", "created_at")

    item = graphene.Field(ItemType, required=True)
    line_total = graphene.Decimal(required=True)

    def resolve_item(root: RoomServiceOrder, info):
        loaders = _loaders(info)
        return loaders.item.load(root.item_id) if loaders.enabled else root.item

    def resolve_line_total(root, info):
        return root.line_total


class BillType(DjangoObjectType):
    class Meta:
        model = Bill
        name = "Bill"
        fields = ("id", "nights", "room_total", "service_total", "total", "issued_at")


class ChargesType(graphene.ObjectType):
    class Meta:
        name = "Charges"

    nights = graphene.Int(required=True)
    nightly_rate = graphene.Decimal(required=True)
    room_total = graphene.Decimal(required=True)
    service_total = graphene.Decimal(required=True)
    total = graphene.Decimal(required=True)


class BookingType(DjangoObjectType):
    class Meta:
        model = Booking
        name = "Booking"
        fields = (
            "id",
            "check_in",
            "check_out",
            "guests_count",
            "nightly_rate",
            "created_at",
            "checked_in_at",
            "checked_out_at",
            "cancelled_at",
        )

    status = graphene.String(required=True)
    nights = graphene.Int(required=True)
    room = graphene.Field(RoomNode, required=True)
    guest = graphene.Field(GuestType, required=True)
    room_service = graphene.List(graphene.NonNull(RoomServiceOrderType), required=True)
    bill = graphene.Field(BillType)
    charges = graphene.Field(ChargesType, required=True)

    def resolve_status(root, info):
        return root.status

    def resolve_nights(root, info):
        return root.nights

    def resolve_room(root: Booking, info):
        loaders = _loaders(info)
        return loaders.room.load(root.room_id) if loaders.enabled else root.room

    def resolve_guest(root: Booking, info):
        loaders = _loaders(info)
        return loaders.user.load(root.guest_id) if loaders.enabled else root.guest

    def resolve_room_service(root: Booking, info):
        loaders = _loaders(info)
        if loaders.enabled:
            return loaders.orders_by_booking.load(root.pk)
        return list(root.room_service_orders.all())

    def resolve_bill(root: Booking, info):
        loaders = _loaders(info)
        if loaders.enabled:
            return loaders.bill_by_booking.load(root.pk)
        return Bill.objects.filter(booking_id=root.pk).first()

    def resolve_charges(root: Booking, info):
        orders = BookingType.resolve_room_service(root, info)
        q = pricing.quote(root.nightly_rate, root.nights, [(o.unit_price, o.quantity) for o in orders])
        return ChargesType(
            nights=q.nights,
            nightly_rate=q.nightly_rate,
            room_total=q.room_total,
            service_total=q.service_total,
            total=q.total,
        )


class AvailabilityType(graphene.ObjectType):
    class Meta:
        name = "Availability"

    room_type = graphene.Field(RoomTypeType, required=True)
    total_rooms = graphene.Int(required=True)
    available = graphene.Int(required=True)
    stay_total = graphene.Decimal(required=True)


class MeType(graphene.ObjectType):
    class Meta:
        name = "Me"

    id = graphene.ID(required=True)
    username = graphene.String(required=True)
    role = graphene.String(required=True)


# --- Queries ------------------------------------------------------------------


class Query(graphene.ObjectType):
    me = graphene.Field(MeType)
    room_types = graphene.List(graphene.NonNull(RoomTypeType), required=True)
    items = graphene.List(graphene.NonNull(ItemType), required=True)
    rooms = graphene.List(graphene.NonNull(RoomNode), required=True, description="Staff only.")
    availability = graphene.List(
        graphene.NonNull(AvailabilityType),
        required=True,
        check_in=graphene.Date(required=True),
        check_out=graphene.Date(required=True),
        guests=graphene.Int(default_value=1),
    )
    bookings = graphene.List(
        graphene.NonNull(BookingType),
        required=True,
        status=graphene.String(),
        limit=graphene.Int(default_value=50),
        description="Your bookings, or every booking for staff.",
    )
    booking = graphene.Field(BookingType, id=graphene.ID(required=True))

    def resolve_me(root, info):
        user = _user(info)
        if not user or not user.is_authenticated:
            return None
        return MeType(id=user.pk, username=user.username, role=role_of(user))

    def resolve_room_types(root, info):
        return RoomType.objects.all()

    def resolve_items(root, info):
        return Item.objects.filter(is_available=True)

    def resolve_rooms(root, info):
        if not is_staff_role(_user(info)):
            raise GraphQLError("Staff only.", extensions={"code": "forbidden", "status": 403})
        rooms = list(Room.objects.all())
        _loaders(info).prime_rooms(rooms)
        return rooms

    @_domain
    def resolve_availability(root, info, check_in: date, check_out: date, guests: int = 1):
        commands.validate_stay(check_in, check_out)
        out = []
        for row in availability.search(check_in, check_out, guests):
            rt = row["room_type"]
            out.append(
                AvailabilityType(
                    room_type=RoomType(**{k: rt[k] for k in ("id", "name", "description", "beds", "capacity", "air_conditioned")}, nightly_rate=rt["nightly_rate"]),
                    total_rooms=row["total_rooms"],
                    available=row["available"],
                    stay_total=row["quote"]["total"],
                )
            )
        return out

    def resolve_bookings(root, info, status=None, limit=50):
        user = _user(info)
        if not user or not user.is_authenticated:
            raise GraphQLError("Sign in first.", extensions={"code": "unauthenticated", "status": 401})
        qs = Booking.objects.all()
        if not is_staff_role(user):
            qs = qs.filter(guest=user)
        if status:
            qs = qs.filter(status=status)
        bookings = list(qs.order_by("-check_in", "-id")[: max(1, min(limit, 200))])
        _loaders(info).prime_bookings(bookings)
        return bookings

    def resolve_booking(root, info, id):
        user = _user(info)
        if not user or not user.is_authenticated:
            raise GraphQLError("Sign in first.", extensions={"code": "unauthenticated", "status": 401})
        qs = Booking.objects.filter(pk=id)
        if not is_staff_role(user):
            qs = qs.filter(guest=user)
        return qs.first()


# --- Mutations ----------------------------------------------------------------


def _fresh_booking(pk: int) -> Booking:
    return Booking.objects.get(pk=pk)


class CreateBooking(graphene.Mutation):
    class Arguments:
        check_in = graphene.Date(required=True)
        check_out = graphene.Date(required=True)
        guests_count = graphene.Int(default_value=1)
        room_id = graphene.ID()
        room_type_id = graphene.ID()

    booking = graphene.Field(BookingType, required=True)

    @_domain
    def mutate(root, info, check_in, check_out, guests_count=1, room_id=None, room_type_id=None):
        cmd = commands.CreateBooking(
            check_in=check_in,
            check_out=check_out,
            guests_count=guests_count,
            room=int(room_id) if room_id else None,
            room_type=int(room_type_id) if room_type_id else None,
        )
        booking = commands.run(cmd, _user(info))
        return CreateBooking(booking=_fresh_booking(booking.pk))


class _BookingAction(graphene.Mutation):
    class Arguments:
        booking_id = graphene.ID(required=True)

    booking = graphene.Field(BookingType, required=True)

    command_class: type = None

    @classmethod
    def mutate(cls, root, info, booking_id):
        try:
            result = commands.run(cls.command_class(booking=int(booking_id)), _user(info))
        except commands.DomainError as exc:
            raise GraphQLError(exc.message, extensions={"code": exc.code, "status": exc.status})
        pk = result.pk if isinstance(result, Booking) else result.booking_id
        return cls(booking=_fresh_booking(pk))


class CancelBooking(_BookingAction):
    command_class = commands.CancelBooking


class CheckIn(_BookingAction):
    command_class = commands.CheckIn


class CheckOut(_BookingAction):
    command_class = commands.CheckOut


class AddRoomService(graphene.Mutation):
    class Arguments:
        booking_id = graphene.ID(required=True)
        item_id = graphene.ID(required=True)
        quantity = graphene.Int(default_value=1)

    booking = graphene.Field(BookingType, required=True)

    @_domain
    def mutate(root, info, booking_id, item_id, quantity=1):
        order = commands.run(
            commands.AddRoomService(booking=int(booking_id), item=int(item_id), quantity=quantity), _user(info)
        )
        return AddRoomService(booking=_fresh_booking(order.booking_id))


class Mutation(graphene.ObjectType):
    create_booking = CreateBooking.Field()
    cancel_booking = CancelBooking.Field()
    check_in = CheckIn.Field()
    check_out = CheckOut.Field()
    add_room_service = AddRoomService.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
