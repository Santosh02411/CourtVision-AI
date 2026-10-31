"""Uniform API envelope + validation helpers."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from flask import jsonify

from app.services.cache import Fetched


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", meta: dict | None = None) -> None:
        super().__init__(message)
        self.message, self.status, self.code, self.meta = message, status, code, meta or {}


def merge_meta(*parts: Fetched | dict | None) -> dict[str, Any]:
    """Collapse several provenance records into one `sources` list + an overall status."""
    sources, worst = [], "fresh"
    order = {"fresh": 0, "cached": 1, "stale": 2, "unavailable": 3}
    for p in parts:
        if p is None:
            continue
        m = p.meta() if isinstance(p, Fetched) else p
        sources.append(m)
        if order.get(m.get("status", "fresh"), 0) > order[worst]:
            worst = m["status"]
    return {"sources": sources, "status": worst}


def ok(data: Any, *, kind: str, season: str | None = None, provenance: dict | None = None,
       notes: list[str] | None = None, status: int = 200):
    """kind: live | historical | prediction | derived | model"""
    meta = {
        "kind": kind,
        "season": season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes or [],
        **(provenance or {"sources": [], "status": "fresh"}),
    }
    resp = jsonify({"ok": True, "data": data, "meta": meta})
    resp.status_code = status
    return resp


def fail(message: str, status: int, code: str, meta: dict | None = None):
    resp = jsonify({"ok": False, "error": {"code": code, "message": message}, "meta": meta or {}})
    resp.status_code = status
    return resp


def clamp_int(raw: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


class RateLimiter:
    """Tiny in-memory token bucket keyed by client address (protects the optional AI endpoint)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < 60]
        if len(hits) >= self.per_minute:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True
