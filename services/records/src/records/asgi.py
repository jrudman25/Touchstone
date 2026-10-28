"""ASGI config for the records service."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "records.settings")

application = get_asgi_application()
