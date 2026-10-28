"""WSGI config for the records service."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "records.settings")

application = get_wsgi_application()
