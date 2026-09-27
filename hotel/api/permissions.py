from rest_framework.permissions import SAFE_METHODS, BasePermission

from ..roles import is_admin_role, is_staff_role


class IsStaff(BasePermission):
    message = "Staff only."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and is_staff_role(request.user))


class IsAdmin(BasePermission):
    message = "Admin only."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and is_admin_role(request.user))


class ReadPublicWriteAdmin(BasePermission):
    """Catalogue data: anyone may read, only admins may change it."""

    message = "Admin only."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and is_admin_role(request.user))


class ReadStaffWriteAdmin(BasePermission):
    message = "Staff only."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return is_staff_role(user)
        self.message = "Admin only."
        return is_admin_role(user)
