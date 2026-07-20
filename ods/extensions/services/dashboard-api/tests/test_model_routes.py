"""Tests for dashboard-api Model Switchboard route-evidence proxy."""

from __future__ import annotations

import uuid
from typing import Any

import httpx


def _patch_router_client(monkeypatch, response: httpx.Response | None = None,
                         error: Exception | None = None):
    from routers import model_routes as mr

    calls: list[tuple[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            calls.append(("timeout", timeout))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, headers: dict[str, str]):
            calls.append(("get", {"url": url, "headers": headers}))
            if error is not None:
                raise error
            return response or httpx.Response(404, json={"error": "not_found"})

    monkeypatch.setattr(mr.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(mr, "MODEL_ROUTER_URL", "http://model-router.test")
    return calls


def test_route_evidence_requires_dashboard_auth(test_client):
    probe_id = str(uuid.uuid4())
    resp = test_client.get(f"/api/models/routes/{probe_id}")
    assert resp.status_code == 401


def test_route_evidence_rejects_invalid_probe_id(test_client):
    resp = test_client.get(
        "/api/models/routes/not-a-uuid",
        headers=test_client.auth_headers,
    )
    assert resp.status_code == 400


def test_route_evidence_proxies_with_internal_key_and_sanitizes(
    test_client,
    monkeypatch,
):
    probe_id = str(uuid.uuid4())
    monkeypatch.setenv("ODS_ROUTER_INTERNAL_KEY", "internal-secret")
    payload = {
        "probeId": probe_id,
        "requestedModel": "ods/current",
        "routedModel": "Qwen.gguf",
        "backend": "llama-server",
        "endpointId": "llama-server-default",
        "routeSeq": 12,
        "path": "/v1/chat/completions",
        "status": 200,
        "responseModel": "Qwen.gguf",
        "lemonadeRoute": "",
        "prompt": "do not expose me",
        "storedAt": 123.456,
    }
    calls = _patch_router_client(monkeypatch, httpx.Response(200, json=payload))

    resp = test_client.get(
        f"/api/models/routes/{probe_id}",
        headers=test_client.auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "probeId": probe_id,
        "requestedModel": "ods/current",
        "routedModel": "Qwen.gguf",
        "backend": "llama-server",
        "endpointId": "llama-server-default",
        "routeSeq": 12,
        "path": "/v1/chat/completions",
        "status": 200,
        "responseModel": "Qwen.gguf",
        "lemonadeRoute": "",
    }
    assert calls[1] == (
        "get",
        {
            "url": f"http://model-router.test/internal/route-evidence/{probe_id}",
            "headers": {"Authorization": "Bearer internal-secret"},
        },
    )


def test_route_evidence_preserves_not_found(test_client, monkeypatch):
    probe_id = str(uuid.uuid4())
    calls = _patch_router_client(
        monkeypatch,
        httpx.Response(404, json={"error": "not_found"}),
    )

    resp = test_client.get(
        f"/api/models/routes/{probe_id}",
        headers=test_client.auth_headers,
    )

    assert resp.status_code == 404
    assert calls[1][0] == "get"


def test_route_evidence_maps_unreachable_router_to_503(test_client, monkeypatch):
    probe_id = str(uuid.uuid4())
    _patch_router_client(monkeypatch, error=httpx.ConnectError("no route"))

    resp = test_client.get(
        f"/api/models/routes/{probe_id}",
        headers=test_client.auth_headers,
    )

    assert resp.status_code == 503


def test_route_evidence_rejects_mismatched_probe(test_client, monkeypatch):
    probe_id = str(uuid.uuid4())
    payload = {
        "probeId": str(uuid.uuid4()),
        "requestedModel": "ods/current",
        "routedModel": "Qwen.gguf",
    }
    _patch_router_client(monkeypatch, httpx.Response(200, json=payload))

    resp = test_client.get(
        f"/api/models/routes/{probe_id}",
        headers=test_client.auth_headers,
    )

    assert resp.status_code == 502
