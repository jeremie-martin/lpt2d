"""Append-only JSONL ledgers + small filesystem helpers.

Two files live under the publish home (``~/lpt2d-publish/``) by default:

- ``uploads.jsonl`` — one line per successful YouTube upload.
- ``failed.jsonl`` — one line per terminal failure (verdict gate, upload error, ...).

Each line is a complete record: the params/verdict from the bundle plus
everything decided at upload time (title, description, tags, music, youtube id).
Lines are appended atomically with ``fsync`` so a crash mid-write cannot tear
a record.

``atomic_write_text`` is shared by ``state.py`` and ``watcher.py`` for any
single-shot durable file write (state snapshot, upload marker).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso(ts: float | None = None) -> str:
    """Format a timestamp as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC). Defaults to now."""
    dt = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_text(path: Path, text: str, *, fsync_dir: bool = False) -> None:
    """Write ``text`` to ``path`` durably: temp file → fsync → os.replace.

    ``fsync_dir=True`` additionally fsyncs the parent directory, making the
    rename itself crash-durable. Use for upload markers; not needed for state
    files where a torn rename just looks like "no last_upload_at recorded yet".
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        if fsync_dir:
            dfd = os.open(str(parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    """Append a single JSON record to ``path`` and fsync to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


class Ledger:
    """Two append-only JSONL files in a directory."""

    def __init__(self, ledger_dir: Path) -> None:
        self.dir = Path(ledger_dir)
        self.uploads_path = self.dir / "uploads.jsonl"
        self.failed_path = self.dir / "failed.jsonl"

    def append_upload(self, entry: dict[str, Any]) -> None:
        append_jsonl(self.uploads_path, entry)

    def append_failure(self, entry: dict[str, Any]) -> None:
        append_jsonl(self.failed_path, entry)
