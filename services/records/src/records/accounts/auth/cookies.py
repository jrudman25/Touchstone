"""Refresh cookie helpers scoped to the auth endpoints path."""

from django.conf import settings
from rest_framework.response import Response
from rest_framework_simplejwt.settings import api_settings

from .constants import REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH


def set_refresh_cookie(response: Response, raw_refresh: str) -> None:
    """Attach the refresh token as an httpOnly, SameSite=Strict cookie."""
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        raw_refresh,
        max_age=int(api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh cookie on the client."""
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH, samesite="Strict")
