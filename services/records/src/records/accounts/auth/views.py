"""Cookie-based JWT auth views.

Django is the only token signer. Access tokens live in response bodies and
memory; refresh tokens live only in an httpOnly cookie scoped to
/api/records/auth/. simplejwt's stock views return the refresh token in the
body, so these custom views handle the cookie instead.
"""

from contextlib import suppress
from typing import cast

from django.contrib.auth import authenticate
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from records.accounts.models import User

from .constants import REFRESH_COOKIE_NAME, REFRESH_HEADER, REFRESH_HEADER_VALUE
from .cookies import clear_refresh_cookie, set_refresh_cookie
from .serializers import (
    AccessTokenSerializer,
    DetailSerializer,
    MeSerializer,
    TokenObtainRequestSerializer,
)
from .tokens import build_refresh_token


class TokenObtainView(APIView):
    """Exchange username/password for an access token + refresh cookie."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        request=TokenObtainRequestSerializer,
        responses={
            200: AccessTokenSerializer,
            400: OpenApiTypes.OBJECT,
            401: DetailSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = TokenObtainRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None or not user.is_active:
            return Response({"detail": "Invalid credentials."}, status=401)
        refresh = build_refresh_token(user)
        response = Response({"access": str(refresh.access_token)})
        set_refresh_cookie(response, str(refresh))
        return response


class TokenRefreshView(APIView):
    """Rotate the refresh cookie and return a fresh access token.

    Requires the X-Auth-Refresh: 1 header (CSRF protection on the cookie).
    The old refresh token is blacklisted under a row lock so a concurrent
    reuse of the same token cannot mint two new ones.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        request=None,
        responses={
            200: AccessTokenSerializer,
            401: DetailSerializer,
            403: DetailSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        if request.headers.get(REFRESH_HEADER) != REFRESH_HEADER_VALUE:
            return Response({"detail": "Missing refresh header."}, status=403)
        raw = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not raw:
            return Response({"detail": "Missing refresh token."}, status=401)
        try:
            # simplejwt annotates the token arg as Token but expects the raw string.
            old_refresh = RefreshToken(raw)  # type: ignore[arg-type]
        except TokenError:
            response = Response({"detail": "Invalid refresh token."}, status=401)
            clear_refresh_cookie(response)
            return response
        try:
            user_id = int(old_refresh["user_id"])
        except (KeyError, TypeError, ValueError):
            response = Response({"detail": "Invalid refresh token."}, status=401)
            clear_refresh_cookie(response)
            return response
        user = User.objects.filter(pk=user_id).first()
        if user is None or not user.is_active:
            response = Response({"detail": "User not found or inactive."}, status=401)
            clear_refresh_cookie(response)
            return response
        with transaction.atomic():
            outstanding = (
                OutstandingToken.objects.select_for_update().filter(jti=old_refresh["jti"]).first()
            )
            if outstanding is None:
                response = Response({"detail": "Unknown refresh token."}, status=401)
                clear_refresh_cookie(response)
                return response
            _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
            if not created:
                response = Response({"detail": "Refresh token already used."}, status=401)
                clear_refresh_cookie(response)
                return response
        refresh = build_refresh_token(user)
        response = Response({"access": str(refresh.access_token)})
        set_refresh_cookie(response, str(refresh))
        return response


class LogoutView(APIView):
    """Blacklist the cookie's refresh token (best effort) and clear it."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        raw = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if raw:
            with suppress(TokenError):
                RefreshToken(raw).blacklist()  # type: ignore[arg-type]
        response = Response(status=204)
        clear_refresh_cookie(response)
        return response


class MeView(APIView):
    """The SPA's identity endpoint: user id plus org memberships."""

    @extend_schema(responses={200: MeSerializer, 401: DetailSerializer})
    def get(self, request: Request) -> Response:
        user = cast("User", request.user)
        return Response(
            {
                "id": user.id,
                "username": user.get_username(),
                "organizations": [
                    {
                        "id": membership.organization_id,
                        "name": membership.organization.name,
                        "slug": membership.organization.slug,
                        "role": membership.role,
                    }
                    for membership in user.memberships.select_related("organization")
                ],
            }
        )
