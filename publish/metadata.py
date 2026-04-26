"""Sidecar metadata for videos in the publish pipeline.

The sidecar is a JSON file alongside the video (``foo.mp4`` -> ``foo.mp4.json``).
Fields ``peak_s`` and ``beat_s`` are reserved for future audio/video sync work and
are unused today; they are kept here so the format does not have to change later.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class VideoMetadata:
    source: str
    fps: float
    duration_s: float
    width: int
    height: int
    scene: str | None = None
    peak_s: float | None = None
    beat_s: float | None = None
    title_hint: str | None = None
    description_hint: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def is_vertical(self) -> bool:
        return self.height >= self.width

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> VideoMetadata:
        return cls(**json.loads(path.read_text()))


def sidecar_path(video: Path) -> Path:
    return video.with_suffix(video.suffix + ".json")


def probe(video: Path) -> VideoMetadata:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    stream = data["streams"][0]
    num, den = (int(x) for x in stream["r_frame_rate"].split("/"))
    fps = num / den if den else 0.0
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0.0)
    return VideoMetadata(
        source=video.name,
        fps=fps,
        duration_s=duration,
        width=int(stream["width"]),
        height=int(stream["height"]),
    )


def load_or_probe(video: Path) -> VideoMetadata:
    side = sidecar_path(video)
    if side.exists():
        return VideoMetadata.load(side)
    return probe(video)
