"""Unprefixed service views (not proxied; see SPEC.md > Architecture)."""

from django.http import JsonResponse


def health(request: object) -> JsonResponse:
    """Liveness probe."""
    return JsonResponse({"status": "ok"})
