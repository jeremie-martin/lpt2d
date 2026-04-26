"""Persisted watcher state for rate limiting across restarts.

A single ``state.json`` under the publish home tracks the last upload time
so the rate limit (``--min-interval``) survives a watcher restart.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from .ledger import atomic_write_text, now_iso


class State:
    def __init__(self, path: Path, last_upload_at: float | None = None) -> None:
        self.path = Path(path)
        self.last_upload_at: float | None = last_upload_at

    @classmethod
    def load(cls, path: Path) -> "State":
        p = Path(path)
        if not p.exists():
            return cls(p, last_upload_at=None)
        data = json.loads(p.read_text())
        ts = data.get("last_upload_at")
        return cls(p, last_upload_at=_parse_iso(ts) if ts else None)

    def seconds_until_next_allowed(self, min_interval: int) -> int:
        if min_interval <= 0 or self.last_upload_at is None:
            return 0
        elapsed = time.time() - self.last_upload_at
        return max(0, int(min_interval - elapsed))

    def record_upload(self, ts: float | None = None) -> None:
        self.last_upload_at = ts if ts is not None else time.time()
        ts_at = self.last_upload_at
        data = {"last_upload_at": now_iso(ts_at) if ts_at is not None else None}
        atomic_write_text(self.path, json.dumps(data, indent=2))


def _parse_iso(s: str) -> float:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()
