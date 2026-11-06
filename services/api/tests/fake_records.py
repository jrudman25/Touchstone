"""A fake Django records service driven through httpx.MockTransport.

Response bodies match the real ``DatasetSerializer`` contract:
``{"id", "project", "organization", "name", "row_count"}`` with
``{"detail": "..."}`` error bodies. Every request is recorded so tests can
assert on method, path, Authorization header, and JSON body.
"""

import json
import re
from typing import Any

import httpx


class FakeRecords:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.set_row_count_calls: list[tuple[int, dict[str, Any]]] = []
        self.get_bodies: dict[int, dict[str, Any]] = {}
        self.generic_bodies: dict[str, dict[int, dict[str, Any]]] = {}
        self.get_statuses: dict[int, int] = {}
        self.set_row_count_status = 200
        self.connect_error = False

    def add_dataset(
        self,
        dataset_id: int,
        *,
        organization: int = 1,
        project: int = 1,
        name: str = "ds",
        row_count: int | None = None,
    ) -> None:
        self.get_bodies[dataset_id] = {
            "id": dataset_id,
            "project": project,
            "organization": organization,
            "name": name,
            "row_count": row_count,
        }

    def add(self, collection: str, item_id: int, body: dict[str, Any]) -> None:
        self.generic_bodies.setdefault(collection, {})[item_id] = body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.connect_error:
            raise httpx.ConnectError("cannot connect", request=request)
        path = request.url.path
        generic = re.fullmatch(
            r"/api/records/(projects|prompt-versions|prompt-templates|models|providers|scorers)/(\d+)/",
            path,
        )
        if request.method == "GET" and generic:
            collection, item_id = generic.group(1), int(generic.group(2))
            body = self.generic_bodies.get(collection, {}).get(item_id)
            if body is None:
                return httpx.Response(404, json={"detail": "Not found."})
            return httpx.Response(200, json=body)
        match = re.fullmatch(r"/api/records/datasets/(\d+)/", path)
        if request.method == "GET" and match:
            dataset_id = int(match.group(1))
            status_code = self.get_statuses.get(dataset_id, 200)
            if status_code != 200:
                return httpx.Response(status_code, json={"detail": "Rejected."})
            body = self.get_bodies.get(dataset_id)
            if body is None:
                return httpx.Response(404, json={"detail": "Not found."})
            return httpx.Response(200, json=body)
        match = re.fullmatch(r"/api/records/datasets/(\d+)/set-row-count/", path)
        if request.method == "POST" and match:
            dataset_id = int(match.group(1))
            self.set_row_count_calls.append((dataset_id, json.loads(request.content)))
            if self.set_row_count_status != 200:
                return httpx.Response(self.set_row_count_status, json={"detail": "Rejected."})
            body = dict(self.get_bodies[dataset_id])
            body["row_count"] = json.loads(request.content)["row_count"]
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"detail": "Not found."})
