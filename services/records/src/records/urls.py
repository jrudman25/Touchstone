"""URL configuration for the records service.

``health`` is unprefixed and not proxied. Everything browser-facing lives
under /api/records/ (admin and the DRF API).
"""

from django.contrib import admin
from django.urls import include, path

from .views import health

urlpatterns = [
    path("health", health, name="health"),
    path("api/records/admin/", admin.site.urls),
    path("api/records/", include("records.api.urls")),
]
