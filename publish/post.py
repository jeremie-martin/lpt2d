"""Process a video for publishing: rotate to 9:16 + optional music mux."""

from __future__ import annotations

import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .ffmpeg import FFmpegCommand

MUSIC_EXTENSIONS = {".m4a", ".aac", ".mp3", ".webm", ".opus", ".ogg", ".wav", ".flac"}


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    duration_s: float

    @property
    def needs_rotate(self) -> bool:
        return self.width > self.height


def probe(video: Path) -> VideoInfo:
    """ffprobe wrapper. Returns width/height/fps/duration."""
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
    return VideoInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps,
        duration_s=duration,
    )


def pick_music(music_dir: Path) -> Path | None:
    if not music_dir.is_dir():
        return None
    tracks = sorted(p for p in music_dir.iterdir() if p.suffix.lower() in MUSIC_EXTENSIONS)
    return random.choice(tracks) if tracks else None


def _resolve_music(
    music: bool,
    music_dir: Path | str | None,
    music_override: str | None,
) -> Path | None:
    """Pick a music track, or return None for "no audio".

    ``music_override`` (per-bundle pin) wins; missing-file fails closed.
    Else if ``music`` is True, pick a random track from ``music_dir``.
    """
    if music_override:
        if music_dir is None:
            raise ValueError(f"music_override={music_override!r} given but music_dir is None")
        candidate = Path(music_dir) / music_override
        if not candidate.is_file():
            raise FileNotFoundError(
                f"music_override {music_override!r} not found under {music_dir}"
            )
        return candidate
    if not music:
        return None
    if music_dir is None:
        logger.warning("music=True but no music_dir provided; skipping audio")
        return None
    track = pick_music(Path(music_dir))
    if track is None:
        logger.warning("No music tracks found in {}", music_dir)
    return track


def process(
    input_path: Path | str,
    output_path: Path | str | None = None,
    music: bool = False,
    music_dir: Path | str | None = None,
    music_override: str | None = None,
    rotate_cw: bool = True,
) -> tuple[Path, Path | None]:
    """Rotate to 9:16 (if needed) and optionally mux a music track.

    Returns ``(output_path, music_path_used_or_None)`` so callers can record
    the actual track that was muxed in.
    """
    src = Path(input_path)
    dst = Path(output_path) if output_path else src.with_name(src.stem + "_published.mp4")

    info = probe(src)
    music_path = _resolve_music(music, music_dir, music_override)

    cmd = FFmpegCommand()
    if info.needs_rotate:
        # Modern ffmpeg (5.0+) writes Display Matrix side data when -display_rotation is
        # given as an INPUT option before -i. Lossless (works with -c copy); YouTube honors it.
        rot = "90" if rotate_cw else "270"
        cmd.pre("-display_rotation:v:0", rot)
        logger.info(
            "Rotating {} ({}x{}) -> {} via display_rotation={}",
            src.name,
            info.width,
            info.height,
            dst.name,
            rot,
        )
    cmd.input(src)
    if music_path is not None:
        cmd.input(music_path)

    cmd.arg("-c:v", "copy")
    if music_path is not None:
        cmd.arg("-map", "0:v:0", "-map", "1:a:0")
        cmd.arg("-c:a", "aac", "-b:a", "192k")
        cmd.arg("-shortest")
        logger.info("Adding music: {}", music_path.name)
    else:
        cmd.arg("-map", "0:v:0", "-map", "0:a?", "-c:a", "copy")

    cmd.arg("-movflags", "+faststart")
    cmd.out(dst)
    cmd.run()
    return dst, music_path
