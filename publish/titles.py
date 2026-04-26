"""Random title/description/tags picker."""

from __future__ import annotations

import random
from pathlib import Path

import tomllib

DEFAULT_POOL_PATH = Path(__file__).parent / "data" / "titles.toml"
TITLE_HASHTAG_COUNT = (0, 2)  # min, max — random pick per upload (0 = clean title)


def load_pool(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_POOL_PATH
    return tomllib.loads(p.read_text())


def pick(pool: dict | None = None) -> tuple[str, str, list[str]]:
    if pool is None:
        pool = load_pool()
    title = random.choice(pool["titles"])
    title_hashtags = pool.get("title_hashtags") or []
    if title_hashtags:
        lo, hi = TITLE_HASHTAG_COUNT
        n = min(random.randint(lo, hi), len(title_hashtags))
        if n > 0:
            chosen = random.sample(title_hashtags, n)
            title = title + " " + " ".join(f"#{t}" for t in chosen)
    descriptions = pool.get("descriptions") or [""]
    description = random.choice(descriptions)
    tags = list(pool.get("tags", []))
    return title, description, tags
