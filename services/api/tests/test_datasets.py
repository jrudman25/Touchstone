"""Dataset upload and preview endpoints against real Mongo + a fake records service."""

import dataclasses
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import httpx
import jwt
import pytest
from fake_records import FakeRecords
from fastapi.testclient import TestClient
from pymongo.database import Database

from eval_api.main import create_app
from eval_api.settings import Settings
from evalcore import DATASET_ROWS, RESULTS

DATASET_ID = 7
ORG_ID = 1
ROWS_URL = f"/api/eval/datasets/{DATASET_ID}/rows"


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "user_id": "7",
        "orgs": {str(ORG_ID): "editor"},
        "token_type": "access",
        "jti": "jti-123",
        "exp": now + 300,
        "iat": now,
    }
    claims.update(overrides)
    return claims


def _mint(private_pem: str, claims: dict[str, Any]) -> str:
    return jwt.encode(claims, private_pem, algorithm="RS256")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def token(rsa_keypair: tuple[str, str]) -> str:
    private, _ = rsa_keypair
    return _mint(private, _claims())


@pytest.fixture()
def client_factory(
    fake_records: FakeRecords,
) -> Callable[[Settings], AbstractContextManager[TestClient]]:
    @contextmanager
    def factory(settings: Settings) -> Iterator[TestClient]:
        app = create_app(settings, records_transport=httpx.MockTransport(fake_records.handler))
        with TestClient(app) as test_client:
            yield test_client

    return factory


def _post(
    client: TestClient,
    token: str,
    body: bytes,
    *,
    dataset_id: int = DATASET_ID,
    content_type: str = "application/x-ndjson",
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": content_type}
    response: httpx.Response = client.post(
        f"/api/eval/datasets/{dataset_id}/rows", content=body, headers=headers
    )
    return response


def _stored_rows(
    db: Database[dict[str, Any]], dataset_id: int = DATASET_ID
) -> list[dict[str, Any]]:
    return list(db[DATASET_ROWS].find({"dataset_id": dataset_id}).sort("row_index", 1))


def _seed_rows(
    db: Database[dict[str, Any]], dataset_id: int, count: int, *, start: int = 0
) -> None:
    db[DATASET_ROWS].insert_many(
        [
            {
                "dataset_id": dataset_id,
                "row_index": index,
                "input": {"question": f"q{index}", "n": index},
                "expected": f"a{index}" if index % 2 == 0 else None,
            }
            for index in range(start, start + count)
        ]
    )


# --- upload happy path -----------------------------------------------------------


def test_upload_happy_path(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    body = (
        b'{"input": {"question": "q0", "n": 0}, "expected": "a0"}\n'
        b'{"input": {"question": "q1", "flag": true}}\n'
        b'{"input": {"question": "q2", "ratio": 1.5}}\n'
    )
    response = _post(client, token, body)
    assert response.status_code == 201, response.json()
    assert response.json() == {"dataset_id": DATASET_ID, "row_count": 3}

    stored = _stored_rows(mongo_db)
    assert [doc["row_index"] for doc in stored] == [0, 1, 2]
    assert stored[0]["input"] == {"question": "q0", "n": 0}
    assert type(stored[0]["input"]["n"]) is int
    assert stored[0]["expected"] == "a0"
    assert stored[1]["input"]["flag"] is True
    assert stored[1]["expected"] is None
    assert type(stored[2]["input"]["ratio"]) is float

    assert fake_records.set_row_count_calls == [(DATASET_ID, {"row_count": 3})]
    requests = fake_records.requests
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", f"/api/records/datasets/{DATASET_ID}/"),
        ("POST", f"/api/records/datasets/{DATASET_ID}/set-row-count/"),
    ]
    for request in requests:
        assert request.headers["authorization"] == f"Bearer {token}"


@pytest.mark.parametrize(
    "content_type",
    ["application/jsonl", "application/x-ndjson; charset=utf-8", "Application/JSONL"],
)
def test_upload_accepts_media_types(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
    content_type: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    response = _post(client, token, b'{"input": {"a": 1}}\n', content_type=content_type)
    assert response.status_code == 201, response.json()


# --- auth and Django error mapping ---------------------------------------------------


def test_upload_no_token_is_401_and_records_not_called(
    client: TestClient, fake_records: FakeRecords
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    response = client.post(
        ROWS_URL,
        content=b'{"input": {"a": 1}}\n',
        headers={"Content-Type": "application/x-ndjson"},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert fake_records.requests == []


@pytest.mark.parametrize(
    "orgs",
    [{str(ORG_ID): "viewer"}, {"2": "editor"}],
    ids=["viewer", "other-org"],
)
def test_upload_role_403(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    rsa_keypair: tuple[str, str],
    orgs: dict[str, str],
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    private, _ = rsa_keypair
    response = _post(client, _mint(private, _claims(orgs=orgs)), b'{"input": {"a": 1}}\n')
    assert response.status_code == 403
    assert _stored_rows(mongo_db) == []
    assert fake_records.set_row_count_calls == []


def test_upload_dataset_not_found_passthrough(
    client: TestClient, fake_records: FakeRecords, token: str
) -> None:
    fake_records.get_statuses[DATASET_ID] = 404
    response = _post(client, token, b'{"input": {"a": 1}}\n')
    assert response.status_code == 404
    assert response.json()["detail"] == "Rejected."


def test_upload_records_403_passthrough(
    client: TestClient, fake_records: FakeRecords, token: str
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    fake_records.get_statuses[DATASET_ID] = 403
    response = _post(client, token, b'{"input": {"a": 1}}\n')
    assert response.status_code == 403


def test_upload_records_connect_error_is_502(
    client: TestClient, fake_records: FakeRecords, token: str
) -> None:
    fake_records.connect_error = True
    response = _post(client, token, b'{"input": {"a": 1}}\n')
    assert response.status_code == 502
    assert response.json() == {"detail": "Records service unavailable"}


def test_upload_row_count_already_set_is_409(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=5)
    response = _post(client, token, b'{"input": {"a": 1}}\n')
    assert response.status_code == 409
    assert response.json()["detail"] == "Dataset rows are already uploaded"
    assert _stored_rows(mongo_db) == []
    assert fake_records.set_row_count_calls == []


def test_upload_concurrent_upload_is_409_and_keeps_existing_rows(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    _seed_rows(mongo_db, DATASET_ID, 1)
    response = _post(client, token, b'{"input": {"a": 1}}\n{"input": {"a": 2}}\n')
    assert response.status_code == 409
    assert response.json()["detail"] == "Another upload for this dataset is in progress or finished"
    stored = _stored_rows(mongo_db)
    assert len(stored) == 1
    assert stored[0]["input"] == {"question": "q0", "n": 0}
    assert fake_records.set_row_count_calls == []


@pytest.mark.parametrize(
    ("set_status", "expected_status"),
    [(409, 409), (500, 502)],
    ids=["set-row-count-409", "set-row-count-500"],
)
def test_upload_compensates_when_set_row_count_fails(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
    set_status: int,
    expected_status: int,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    fake_records.set_row_count_status = set_status
    response = _post(client, token, b'{"input": {"a": 1}}\n{"input": {"a": 2}}\n')
    assert response.status_code == expected_status
    assert _stored_rows(mongo_db) == []


# --- media type, limits, validation -------------------------------------------------


def test_upload_wrong_content_type_is_415(
    client: TestClient, fake_records: FakeRecords, token: str
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    response = _post(client, token, b'{"input": {"a": 1}}\n', content_type="text/plain")
    assert response.status_code == 415


def test_upload_validation_errors_report_line_numbers(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    body = b"\n".join(
        [
            b'{"input": {"a": 1}}',  # line 1 valid
            b"[1]",  # line 2 non-object
            b'{"expected": "x"}',  # line 3 missing input
            b'{"input": {"a": 1}, "extra": 2}',  # line 4 extra key
            b'{"input": {"a": {"b": 1}}}',  # line 5 object value
            b'{"input": {"a": [1]}}',  # line 6 array value
            b'{"input": {"a": "x"}, "expected": 5}',  # line 7 non-string expected
            b"   ",  # line 8 blank
            b'{"input": {"a": \xff}}',  # line 9 invalid UTF-8
            b'{"input": {"a": 2}}',  # line 10 valid
        ]
    )
    response = _post(client, token, body)
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Invalid JSONL upload"
    errors = payload["errors"]
    assert [e["line"] for e in errors] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert errors[0]["message"]  # non-object line reports just the message
    assert errors[1]["message"].startswith("input:")
    assert errors[6]["message"] == "Blank line"
    assert errors[7]["message"] == "Line is not valid UTF-8"
    assert _stored_rows(mongo_db) == []
    assert fake_records.set_row_count_calls == []


def test_upload_empty_body_is_400(
    client: TestClient, fake_records: FakeRecords, token: str
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    response = _post(client, token, b"")
    assert response.status_code == 400
    assert response.json() == {"detail": "Upload is empty", "errors": []}


def test_upload_trailing_newline_not_an_extra_line(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    response = _post(client, token, b'{"input": {"a": 1}}\n')
    assert response.status_code == 201
    assert len(_stored_rows(mongo_db)) == 1


def test_upload_crlf_and_bom_accepted(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    body = b'\xef\xbb\xbf{"input": {"a": 1}}\r\n{"input": {"a": 2}}\r\n'
    response = _post(client, token, body)
    assert response.status_code == 201, response.json()
    stored = _stored_rows(mongo_db)
    assert [doc["input"] for doc in stored] == [{"a": 1}, {"a": 2}]


def test_upload_error_cap_is_50(client: TestClient, fake_records: FakeRecords, token: str) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    response = _post(client, token, b"\n" * 60)
    assert response.status_code == 400
    errors = response.json()["errors"]
    assert len(errors) == 50
    assert errors[-1]["line"] == 50


def test_upload_content_length_over_limit_is_413(
    client_factory: Callable[[Settings], AbstractContextManager[TestClient]],
    settings: Settings,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    small = dataclasses.replace(settings, dataset_upload_max_bytes=10)
    with client_factory(small) as client:
        response = _post(client, token, b'{"input": {"a": 1}}\n')
    assert response.status_code == 413
    assert response.json()["detail"] == "Upload exceeds 10 bytes"
    assert _stored_rows(mongo_db) == []


def test_upload_streamed_body_over_limit_is_413(
    client_factory: Callable[[Settings], AbstractContextManager[TestClient]],
    settings: Settings,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    """A chunked body without Content-Length is 413 once bytes pass the limit."""
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    small = dataclasses.replace(settings, dataset_upload_max_bytes=10)
    chunks = iter([b'{"input": {"a": 1}', b'}\n{"input": {"b": 2}}\n'])
    with client_factory(small) as client:
        response = client.post(
            ROWS_URL,
            content=chunks,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-ndjson",
            },
        )
    assert response.status_code == 413
    assert _stored_rows(mongo_db) == []


def test_upload_row_limit_is_413(
    client_factory: Callable[[Settings], AbstractContextManager[TestClient]],
    settings: Settings,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID)
    small = dataclasses.replace(settings, dataset_upload_max_rows=2)
    body = b'{"input": {"a": 1}}\n{"input": {"a": 2}}\n{"input": {"a": 3}}\n'
    with client_factory(small) as client:
        response = _post(client, token, body)
    assert response.status_code == 413
    assert response.json()["detail"] == "Upload exceeds 2 rows"
    assert _stored_rows(mongo_db) == []


# --- preview ---------------------------------------------------------------------------


def _preview_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_preview_pages_with_after_and_next_after(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=5)
    _seed_rows(mongo_db, DATASET_ID, 5)
    headers = _preview_headers(token)

    first = client.get(f"{ROWS_URL}?limit=2", headers=headers)
    assert first.status_code == 200
    assert [row["row_index"] for row in first.json()["items"]] == [0, 1]
    assert first.json()["next_after"] == 1

    second = client.get(f"{ROWS_URL}?limit=2&after=1", headers=headers)
    assert [row["row_index"] for row in second.json()["items"]] == [2, 3]
    assert second.json()["next_after"] == 3

    last = client.get(f"{ROWS_URL}?limit=2&after=3", headers=headers)
    assert [row["row_index"] for row in last.json()["items"]] == [4]
    assert last.json()["next_after"] is None


def test_preview_exact_boundary_gives_null_next_after(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=2)
    _seed_rows(mongo_db, DATASET_ID, 2)
    response = client.get(f"{ROWS_URL}?limit=2", headers=_preview_headers(token))
    assert len(response.json()["items"]) == 2
    assert response.json()["next_after"] is None


def test_preview_default_limit_is_50(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=51)
    _seed_rows(mongo_db, DATASET_ID, 51)
    response = client.get(ROWS_URL, headers=_preview_headers(token))
    items = response.json()["items"]
    assert len(items) == 50
    assert response.json()["next_after"] == 49


def test_preview_limit_over_200_is_422(
    client: TestClient, fake_records: FakeRecords, token: str
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=1)
    response = client.get(f"{ROWS_URL}?limit=201", headers=_preview_headers(token))
    assert response.status_code == 422


def test_preview_viewer_allowed_other_org_denied(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    rsa_keypair: tuple[str, str],
) -> None:
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=1)
    _seed_rows(mongo_db, DATASET_ID, 1)
    private, _ = rsa_keypair
    viewer = _mint(private, _claims(orgs={str(ORG_ID): "viewer"}))
    response = client.get(ROWS_URL, headers=_preview_headers(viewer))
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    outsider = _mint(private, _claims(orgs={"2": "owner"}))
    response = client.get(ROWS_URL, headers=_preview_headers(outsider))
    assert response.status_code == 403


def test_preview_no_token_is_401(client: TestClient) -> None:
    assert client.get(ROWS_URL).status_code == 401


def test_preview_row_count_null_returns_empty(
    client: TestClient,
    fake_records: FakeRecords,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    """Rows of an unfinished upload are never exposed while row_count is null."""
    fake_records.add_dataset(DATASET_ID, organization=ORG_ID, row_count=None)
    _seed_rows(mongo_db, DATASET_ID, 2)
    response = client.get(ROWS_URL, headers=_preview_headers(token))
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_after": None}


# --- lifespan ---------------------------------------------------------------------------


def test_lifespan_creates_mongo_indexes(
    client: TestClient, mongo_db: Database[dict[str, Any]]
) -> None:
    results_indexes = mongo_db[RESULTS].index_information()
    keys = [tuple(index["key"]) for index in results_indexes.values()]
    assert (("run_id", 1), ("model_config_id", 1), ("row_index", 1)) in keys
    rows_indexes = mongo_db[DATASET_ROWS].index_information()
    keys = [tuple(index["key"]) for index in rows_indexes.values()]
    assert (("dataset_id", 1), ("row_index", 1)) in keys
