"""Random title/description/tags picker."""

from __future__ import annotations

import random
from pathlib import Path

import tomllib

DEFAULT_POOL_PATH = Path(__file__).parent / "data" / "titles.toml"


def load_pool(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_POOL_PATH
    return tomllib.loads(p.read_text())


def pick(pool: dict | None = None) -> tuple[str, str, list[str]]:
    if pool is None:
        pool = load_pool()
    title = random.choice(pool["titles"])
    descriptions = pool.get("descriptions") or [""]
    description = random.choice(descriptions)
    tags = list(pool.get("tags", []))
    return title, description, tags
