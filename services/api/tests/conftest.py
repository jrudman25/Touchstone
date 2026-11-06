"""Shared eval-api test fixtures."""

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pymongo
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fake_records import FakeRecords
from fastapi.testclient import TestClient
from pymongo.database import Database

from eval_api.main import create_app
from eval_api.settings import Settings
from evalcore import DATASET_ROWS


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


@pytest.fixture(scope="session")
def mongo_url_db() -> Iterator[tuple[str, str]]:
    """A (url, database_name) pair against the Compose Mongo, dropped on teardown."""
    url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    name = f"{os.environ.get('MONGO_DB', 'touchstone')}_test_{uuid4().hex[:8]}"
    yield url, name
    client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(url)
    try:
        client.drop_database(name)
    finally:
        client.close()


@pytest.fixture()
def settings(rsa_keypair: tuple[str, str], mongo_url_db: tuple[str, str]) -> Settings:
    _, public = rsa_keypair
    url, name = mongo_url_db
    return Settings(
        jwt_public_key=public,
        mongo_url=url,
        mongo_db=name,
        records_base_url="http://records.test",
        redis_url=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        run_queue_name=f"arq:test:{uuid4().hex[:8]}",
    )


@pytest.fixture()
def mongo_db(mongo_url_db: tuple[str, str]) -> Iterator[Database[dict[str, Any]]]:
    """Sync access to the test database; clears dataset_rows per test."""
    url, name = mongo_url_db
    client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(url)
    try:
        client[name][DATASET_ROWS].delete_many({})
        yield client[name]
    finally:
        client.close()


@pytest.fixture()
def fake_records() -> FakeRecords:
    return FakeRecords()


@pytest.fixture()
def client(settings: Settings, fake_records: FakeRecords) -> Iterator[TestClient]:
    app = create_app(settings, records_transport=httpx.MockTransport(fake_records.handler))
    with TestClient(app) as test_client:
        yield test_client
