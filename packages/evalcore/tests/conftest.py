"""Shared evalcore test fixtures."""

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pymongo
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def mongo_database() -> Iterator[tuple[str, str]]:
    """A (url, database_name) pair against the Compose Mongo, dropped on teardown."""
    url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    name = f"{os.environ.get('MONGO_DB', 'touchstone')}_test_{uuid4().hex[:8]}"
    yield url, name
    client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(url)
    try:
        client.drop_database(name)
    finally:
        client.close()


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[str, str]:
    """An ephemeral (private_pem, public_pem) keypair for signing test tokens."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public
