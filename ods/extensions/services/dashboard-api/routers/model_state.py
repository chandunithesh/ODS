"""Read-only Model Switchboard state endpoint (PR 1, observe mode).

Registered before the dynamic ``/api/models/{model_id}`` routes. The host
agent is the only writer of ``data/model-state.json``; this endpoint is a
sanitized reader. Malformed state is reported diagnostically — it is never
promoted, repaired, or treated as a server error.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from config import INSTALL_DIR
from security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])

_STATE_SCHEMA = "ods.model-state.v1"


def _state_path() -> Path:
    return Path(INSTALL_DIR) / "data" / "model-state.json"


def _summarize(doc: dict[str, Any]) -> dict[str, Any]:
    active = doc.get("active") if isinstance(doc.get("active"), dict) else None
    capabilities = None
    if active and isinstance(active.get("capabilities"), dict):
        capabilities = active["capabilities"]
    history = doc.get("history") if isinstance(doc.get("history"), list) else []
    return {
        "exists": True,
        "valid": True,
        "errors": [],
        "schema": doc.get("schema"),
        "seq": doc.get("seq"),
        "routeSeq": doc.get("routeSeq"),
        "operation": doc.get("operation"),
        "desired": doc.get("desired"),
        "active": active,
        "history": history,
        "historyCount": len(history),
        "availability": doc.get("availability"),
        "capabilityImpact": {
            "agentViable": bool(capabilities.get("agentViable")) if capabilities else None,
        },
    }


@router.get("/api/models/state")
async def get_model_state(api_key: str = Depends(verify_api_key)):
    """Sanitized switchboard state summary; read-only by contract."""
    path = _state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "exists": False,
            "valid": False,
            "errors": [],
            "schema": _STATE_SCHEMA,
            "seq": None,
            "routeSeq": None,
            "operation": None,
            "desired": None,
            "active": None,
            "history": [],
            "historyCount": 0,
            "availability": None,
            "capabilityImpact": {"agentViable": None},
        }
    except OSError as exc:
        logger.warning("model-state read failed: %s", exc)
        return {"exists": True, "valid": False, "errors": [f"read failed: {exc}"]}

    try:
        doc = json.loads(raw)
    except ValueError as exc:
        return {"exists": True, "valid": False, "errors": [f"not valid JSON: {exc}"]}
    if not isinstance(doc, dict) or doc.get("schema") != _STATE_SCHEMA:
        return {
            "exists": True,
            "valid": False,
            "errors": [f"unsupported or missing schema (expected {_STATE_SCHEMA})"],
        }
    return _summarize(doc)
