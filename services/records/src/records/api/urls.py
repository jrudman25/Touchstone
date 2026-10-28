"""Records API URLConf.

The auth endpoints are mounted here; the DRF router for organizations,
projects, prompt versions, datasets, and provider/model/scorer configs is
added in a later step.
"""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("records.accounts.auth.urls")),
]
