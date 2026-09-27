from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .. import pricing
from ..models import (
    AuditLog,
    Bill,
    Booking,
    Employee,
    EmployeeRole,
    Item,
    Profile,
    Role,
    Room,
    RoomServiceOrder,
    RoomType,
)
from ..roles import role_of

User = get_user_model()


class TokenSerializer(TokenObtainPairSerializer):
    """JWT pair with the user's role and name in the access token claims."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = role_of(user)
        token["username"] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = MeSerializer(self.user).data
        return data


class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "role"]

    def get_role(self, obj) -> str:
        return role_of(obj)

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class RegisterSerializer(serializers.Serializer):
    username = serializers.RegexField(r"^[a-zA-Z0-9_.-]{3,30}$")
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    first_name = serializers.CharField(max_length=60)
    last_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Username is taken.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, data):
        user = User.objects.create_user(
            username=data["username"],
            password=data["password"],
            first_name=data["first_name"],
            last_name=data.get("last_name", ""),
            email=data.get("email", ""),
        )
        Profile.objects.create(user=user, role=Role.GUEST)
        return user


class RoomTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomType
        fields = ["id", "name", "description", "beds", "capacity", "air_conditioned", "nightly_rate"]


class RoomSerializer(serializers.ModelSerializer):
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)

    class Meta:
        model = Room
        fields = ["id", "number", "floor", "size_sqft", "is_active", "room_type", "room_type_name"]


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ["id", "name", "category", "price", "is_available"]


class EmployeeRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeRole
        fields = ["id", "name", "base_salary"]


class EmployeeSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = Employee
        fields = ["id", "full_name", "role", "role_name", "salary", "hired_on"]


class RoomServiceOrderSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = RoomServiceOrder
        fields = ["id", "item", "item_name", "quantity", "unit_price", "line_total", "created_at"]


class BillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bill
        fields = ["id", "nights", "room_total", "service_total", "total", "issued_at"]


class GuestSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "full_name"]

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class BookingSerializer(serializers.ModelSerializer):
    """Read shape. Expects room__room_type, guest, room_service_orders__item and bill preloaded."""

    room = RoomSerializer(read_only=True)
    guest = GuestSummarySerializer(read_only=True)
    nights = serializers.IntegerField(read_only=True)
    room_service = RoomServiceOrderSerializer(source="room_service_orders", many=True, read_only=True)
    charges = serializers.SerializerMethodField()
    bill = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "status",
            "check_in",
            "check_out",
            "nights",
            "guests_count",
            "nightly_rate",
            "room",
            "guest",
            "room_service",
            "charges",
            "bill",
            "created_at",
            "checked_in_at",
            "checked_out_at",
            "cancelled_at",
        ]

    def get_charges(self, obj) -> dict:
        return pricing.quote_booking(obj).as_dict()

    def get_bill(self, obj) -> dict | None:
        # A missing reverse one-to-one raises RelatedObjectDoesNotExist, an AttributeError.
        bill = getattr(obj, "bill", None)
        return BillSerializer(bill).data if bill else None


class CreateBookingSerializer(serializers.Serializer):
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    guests_count = serializers.IntegerField(min_value=1, max_value=10, default=1)
    room = serializers.IntegerField(required=False)
    room_type = serializers.IntegerField(required=False)
    guest = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if ("room" in attrs) == ("room_type" in attrs):
            raise serializers.ValidationError("Give exactly one of room or room_type.")
        return attrs


class RoomServiceInputSerializer(serializers.Serializer):
    item = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=20, default=1)


class AvailabilityQuerySerializer(serializers.Serializer):
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    guests = serializers.IntegerField(min_value=1, max_value=10, default=1)


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default=None, read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "command", "actor", "booking", "outcome", "detail", "created_at"]
