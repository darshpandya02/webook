"""Role lookup shared by REST permissions, GraphQL resolvers and commands."""

from .models import Profile, Role


def role_of(user) -> str:
    if user is None or not user.is_authenticated:
        return "anonymous"
    if user.is_superuser:
        return Role.ADMIN
    cached = getattr(user, "_webook_role", None)
    if cached:
        return cached
    try:
        role = user.profile.role
    except Profile.DoesNotExist:
        role = Role.GUEST
    user._webook_role = role
    return role


def is_staff_role(user) -> bool:
    return role_of(user) in (Role.STAFF, Role.ADMIN)


def is_admin_role(user) -> bool:
    return role_of(user) == Role.ADMIN
