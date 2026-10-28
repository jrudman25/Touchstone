"""Auth endpoint routes, mounted under /api/records/auth/."""

from django.urls import path

from .views import LogoutView, MeView, TokenObtainView, TokenRefreshView

app_name = "auth"

urlpatterns = [
    path("token/", TokenObtainView.as_view(), name="token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
]
