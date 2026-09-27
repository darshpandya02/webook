"""Settings for the test suite: fast password hashing, no throttling."""

from .settings import *  # noqa: F401,F403
from .settings import REST_FRAMEWORK

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
