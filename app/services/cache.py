"""Thread-safe TTL cache with stale-while-error semantics and optional disk persistence.

Every lookup returns a `Fetched` carrying provenance, so the API can tell the UI whether data is
fresh, served from cache, stale (upstream failed) - or raise `DataUnavailable` if nothing exists.
Nothing is ever fabricated: if the upstream fails and there is no cached copy, callers get an error.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("courtvision.cache")


class DataUnavailable(Exception):
    """Upstream failed and no cached copy exists."""

    def __init__(self, source: str, reason: str = "") -> None:
        super().__init__(f"{source} unavailable: {reason}" if reason else f"{source} unavailable")
        self.source = source
        self.reason = reason


@dataclass
class Fetched:
    data: Any
    source: str
    status: str                      # fresh | cached | stale
    fetched_at: float
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def age_seconds(self) -> int:
        return max(0, int(time.time() - self.fetched_at))

    def meta(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "fetched_at": datetime.fromtimestamp(self.fetched_at, timezone.utc).isoformat(),
            "age_seconds": self.age_seconds,
            "error": self.error,
        }


class TTLCache:
    def __init__(self, disk_dir: Path | None = None, stale_max: int = 7 * 86400) -> None:
        self._mem: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._disk = disk_dir
        self._stale_max = stale_max
        self._fails: dict[str, tuple[float, int, str]] = {}   # key -> (retry_after, consecutive failures, last reason)
        if self._disk:
            try:
                self._disk.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._disk = None

    # -- disk ---------------------------------------------------------------
    def _path(self, key: str) -> Path | None:
        if not self._disk:
            return None
        return self._disk / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")

    def _disk_read(self, key: str) -> tuple[float, Any] | None:
        path = self._path(key)
        if not path or not path.exists():
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            if blob.get("key") != key:
                return None
            return float(blob["ts"]), blob["data"]
        except Exception:  # corrupt cache file - ignore
            return None

    def _disk_write(self, key: str, ts: float, data: Any) -> None:
        path = self._path(key)
        if not path:
            return
        try:
            path.write_text(json.dumps({"key": key, "ts": ts, "data": data}, default=str), encoding="utf-8")
        except Exception as exc:  # non-serialisable or disk full - cache is best effort
            logger.debug("disk cache write failed for %s: %s", key, exc)

    # -- core ---------------------------------------------------------------
    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get(self, key: str, ttl: int, fetcher: Callable[[], Any], source: str, persist: bool = True) -> Fetched:
        now = time.time()
        hit = self._mem.get(key)
        if hit and now - hit[0] < ttl:
            return Fetched(hit[1], source, "cached", hit[0])

        with self._lock_for(key):  # single-flight per key
            hit = self._mem.get(key)
            if hit and time.time() - hit[0] < ttl:
                return Fetched(hit[1], source, "cached", hit[0])
            retry_after, n_fail, last_reason = self._fails.get(key, (0.0, 0, ""))
            if time.time() < retry_after:                      # recently failed: don't hit a blocked/slow source again yet
                stale = hit or (self._disk_read(key) if persist else None)
                if stale and time.time() - stale[0] < self._stale_max:
                    return Fetched(stale[1], source, "stale", stale[0], error=last_reason)
                raise DataUnavailable(source, last_reason)
            try:
                data = fetcher()
                self._fails.pop(key, None)
                ts = time.time()
                self._mem[key] = (ts, data)
                if persist:
                    self._disk_write(key, ts, data)
                return Fetched(data, source, "fresh", ts)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"[:240]
                n_fail += 1
                backoff = min(300, 10 * 2 ** (n_fail - 1))      # 10s, 20s, 40s ... capped at 5 min
                self._fails[key] = (time.time() + backoff, n_fail, reason)
                logger.warning("fetch failed for %s (%s): %s - retrying in %ss", key, source, reason, backoff)
                stale = hit or (self._disk_read(key) if persist else None)
                if stale and time.time() - stale[0] < self._stale_max:
                    self._mem[key] = stale
                    return Fetched(stale[1], source, "stale", stale[0], error=reason)
                raise DataUnavailable(source, reason) from exc

    def peek(self, key: str) -> Any | None:
        hit = self._mem.get(key)
        return hit[1] if hit else None

    def clear(self) -> None:
        with self._guard:
            self._mem.clear()
