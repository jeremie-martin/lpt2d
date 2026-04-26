"""Per-bundle override file for the publish pipeline.

When a bundle directory contains a ``publish.json`` file, it overrides the
random title / description / tags / music selection performed by the watcher.
All fields are optional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import bundle


@dataclass
class PublishOverrides:
    title_hint: str | None = None
    description_hint: str | None = None
    tags: list[str] = field(default_factory=list)
    music: str | None = None

    @classmethod
    def load(cls, path: Path) -> "PublishOverrides":
        data = json.loads(path.read_text())
        return cls(
            title_hint=data.get("title_hint"),
            description_hint=data.get("description_hint"),
            tags=list(data.get("tags") or []),
            music=data.get("music"),
        )

    @classmethod
    def from_bundle(cls, bundle_dir: Path) -> "PublishOverrides":
        p = bundle_dir / bundle.OVERRIDES
        return cls.load(p) if p.exists() else cls()
