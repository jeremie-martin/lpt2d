"""Process a video for publishing: rotate to 9:16 + optional music mux."""

from __future__ import annotations

import logging
import random
from pathlib import Path

from .ffmpeg import FFmpegCommand
from .metadata import VideoMetadata, load_or_probe

logger = logging.getLogger(__name__)

MUSIC_EXTENSIONS = {".m4a", ".aac", ".mp3", ".webm", ".opus", ".ogg", ".wav", ".flac"}


def pick_music(music_dir: Path) -> Path | None:
    if not music_dir.is_dir():
        return None
    tracks = sorted(p for p in music_dir.iterdir() if p.suffix.lower() in MUSIC_EXTENSIONS)
    return random.choice(tracks) if tracks else None


def process(
    input_path: Path | str,
    output_path: Path | str | None = None,
    music: bool | Path | str = False,
    music_dir: Path | str | None = None,
    rotate_cw: bool = True,
    metadata: VideoMetadata | None = None,
) -> Path:
    """Rotate to 9:16 (if needed) and optionally mux a music track.

    Args:
        input_path: source video.
        output_path: destination. Defaults to ``<input>_published.mp4`` next to the input.
        music: ``True`` to pick a random track from ``music_dir``; a path to use a
            specific track; ``False`` to keep source audio (or none).
        music_dir: where to search for tracks when ``music=True``.
        rotate_cw: clockwise vs counter-clockwise rotation when source is horizontal.
            Only matters when the source is wider than tall.
        metadata: optional pre-loaded metadata; otherwise probed via ffprobe.

    Returns:
        Path to the produced file.
    """

    src = Path(input_path)
    dst = Path(output_path) if output_path else src.with_name(src.stem + "_published.mp4")

    if metadata is None:
        metadata = load_or_probe(src)

    needs_rotate = metadata.width > metadata.height

    music_path: Path | None = None
    if music is True:
        if music_dir is None:
            logger.warning("music=True but no music_dir provided; skipping audio")
        else:
            music_path = pick_music(Path(music_dir))
            if music_path is None:
                logger.warning("No music tracks found in %s", music_dir)
    elif isinstance(music, (str, Path)) and music:
        music_path = Path(music)

    cmd = FFmpegCommand()
    if needs_rotate:
        # Modern ffmpeg (5.0+) writes Display Matrix side data when -display_rotation is
        # given as an INPUT option before -i. This is lossless (works with -c copy) and
        # YouTube/most modern players honor it.
        rot = "90" if rotate_cw else "270"
        cmd.pre("-display_rotation:v:0", rot)
        logger.info(
            "Rotating %s (%dx%d) -> %s via display_rotation=%s",
            src.name,
            metadata.width,
            metadata.height,
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
        logger.info("Adding music: %s", music_path.name)
    else:
        cmd.arg("-map", "0:v:0", "-map", "0:a?", "-c:a", "copy")

    cmd.arg("-movflags", "+faststart")
    cmd.out(dst)
    cmd.run()
    return dst
