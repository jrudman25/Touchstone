"""Test settings for the records service.

Generates a throwaway RSA keypair in a temp dir (never touches .secrets),
defaults DJANGO_SECRET_KEY to a test value, then layers on records.settings.
Postgres credentials still come from the environment (.env locally, job env in
CI) and pytest-django uses its ``test_<db>`` database.
"""

import atexit
import os
import shutil
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_key_dir = tempfile.mkdtemp(prefix="records-test-keys-")
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_public_pem = _private_key.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
_private_path = os.path.join(_key_dir, "private.pem")
_public_path = os.path.join(_key_dir, "public.pem")
with open(_private_path, "wb") as fh:
    fh.write(_private_pem)
with open(_public_path, "wb") as fh:
    fh.write(_public_pem)
atexit.register(shutil.rmtree, _key_dir, True)

os.environ["JWT_PRIVATE_KEY_PATH"] = _private_path
os.environ["JWT_PUBLIC_KEY_PATH"] = _public_path
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DJANGO_DEBUG", "false")

# Fallbacks so tooling that only imports settings (e.g. the mypy Django plugin)
# works without .env. Real test runs take credentials from the environment
# (.env locally, job env in CI) and connect to pytest-django's test_<db>.
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "touchstone")
os.environ.setdefault("POSTGRES_USER", "touchstone")
os.environ.setdefault("POSTGRES_PASSWORD", "touchstone")

from records.settings import *  # noqa: E402, F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
