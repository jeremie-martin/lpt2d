"""Tests for the publish/ package.

Heavy bits (ffmpeg/ffprobe execution, YouTube auth) are mocked or skipped so the
suite stays fast and offline.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import pytest

from publish import titles
from publish.ffmpeg import FFmpegCommand
from publish.metadata import VideoMetadata, sidecar_path
from publish.post import MUSIC_EXTENSIONS, pick_music
from publish.watcher import _pending_videos

# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


def test_metadata_roundtrip(tmp_path: Path) -> None:
    meta = VideoMetadata(
        source="iris.mp4", fps=60.0, duration_s=12.5, width=1920, height=1080, scene="iris"
    )
    side = sidecar_path(tmp_path / "iris.mp4")
    meta.save(side)
    loaded = VideoMetadata.load(side)
    assert loaded == meta


def test_metadata_is_vertical() -> None:
    assert VideoMetadata("a.mp4", 60, 1, 1080, 1920).is_vertical
    assert VideoMetadata("a.mp4", 60, 1, 1080, 1080).is_vertical
    assert not VideoMetadata("a.mp4", 60, 1, 1920, 1080).is_vertical


def test_sidecar_path() -> None:
    assert sidecar_path(Path("foo/bar.mp4")) == Path("foo/bar.mp4.json")


# ---------------------------------------------------------------------------
# ffmpeg builder
# ---------------------------------------------------------------------------


def test_ffmpeg_builder_basic() -> None:
    cmd = (
        FFmpegCommand()
        .input("in.mp4")
        .arg("-c:v", "copy")
        .arg("-metadata:s:v:0", "rotate=90")
        .out("out.mp4")
    )
    built = cmd.build()
    assert built[0] == "ffmpeg"
    assert "-i" in built and "in.mp4" in built
    assert "-c:v" in built and "copy" in built
    assert "rotate=90" in built
    assert built[-1] == "out.mp4"


def test_ffmpeg_builder_two_inputs_and_pre_args() -> None:
    cmd = (
        FFmpegCommand()
        .pre("-display_rotation:v:0", "90")
        .input("video.mp4")
        .input("audio.aac")
        .arg("-map", "0:v:0", "-map", "1:a:0")
        .out("out.mp4")
    )
    built = cmd.build()
    # pre args come before the first -i
    assert built.index("-display_rotation:v:0") < built.index("-i")
    # both inputs present
    assert built.count("-i") == 2


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------


def test_titles_default_pool_loads() -> None:
    pool = titles.load_pool()
    assert "titles" in pool and len(pool["titles"]) > 0
    assert "tags" in pool and len(pool["tags"]) > 0


def test_titles_pick_returns_strings() -> None:
    title, description, tags = titles.pick()
    assert isinstance(title, str) and title
    assert isinstance(description, str)
    assert isinstance(tags, list) and all(isinstance(t, str) for t in tags)


def test_titles_pick_with_custom_pool() -> None:
    pool = {"titles": ["one"], "descriptions": ["d"], "tags": ["t"]}
    assert titles.pick(pool) == ("one", "d", ["t"])


# ---------------------------------------------------------------------------
# music selection
# ---------------------------------------------------------------------------


def test_pick_music_empty_dir(tmp_path: Path) -> None:
    assert pick_music(tmp_path) is None


def test_pick_music_missing_dir(tmp_path: Path) -> None:
    assert pick_music(tmp_path / "does-not-exist") is None


def test_pick_music_returns_track(tmp_path: Path) -> None:
    track = tmp_path / "song.m4a"
    track.write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignore me")
    chosen = pick_music(tmp_path)
    assert chosen == track


def test_music_extensions_include_common_formats() -> None:
    for ext in (".m4a", ".aac", ".mp3", ".webm", ".opus", ".ogg", ".wav", ".flac"):
        assert ext in MUSIC_EXTENSIONS


# ---------------------------------------------------------------------------
# watcher pending list
# ---------------------------------------------------------------------------


def _touch_old(p: Path) -> Path:
    p.write_bytes(b"")
    import os
    import time

    old = time.time() - 60
    os.utime(p, (old, old))
    return p


def test_pending_videos_filters_markers_and_settle(tmp_path: Path) -> None:
    a = _touch_old(tmp_path / "a.mp4")
    _touch_old(tmp_path / "b.mp4")
    _touch_old(tmp_path / "c.mp4")
    fresh = tmp_path / "fresh.mp4"  # not yet settled
    fresh.write_bytes(b"")
    notvideo = _touch_old(tmp_path / "readme.txt")

    # mark b uploaded, c failed
    (tmp_path / "b.mp4.uploaded").write_text("yt-id")
    (tmp_path / "c.mp4.failed").write_text("oops")

    pending = _pending_videos(tmp_path)
    assert pending == [a]
    assert fresh not in pending
    assert notvideo not in pending


# ---------------------------------------------------------------------------
# end-to-end ffprobe + ffmpeg integration (skipped when binaries are absent)
# ---------------------------------------------------------------------------


pytestmark_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


@pytestmark_ffmpeg
def test_probe_synthetic_video(tmp_path: Path) -> None:
    """Generate a tiny landscape MP4 with ffmpeg, probe it, verify aspect."""
    import subprocess

    from publish.metadata import probe

    src = tmp_path / "landscape.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
    )
    meta = probe(src)
    assert meta.width == 320
    assert meta.height == 180
    assert not meta.is_vertical
    assert meta.fps == pytest.approx(30.0)


@pytestmark_ffmpeg
def test_process_rotates_horizontal_input(tmp_path: Path) -> None:
    """Run process() on a synthetic horizontal video; verify output exists and is non-empty."""
    import subprocess

    from publish.post import process

    src = tmp_path / "landscape.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
    )
    out = process(src)
    assert out.exists()
    assert out.stat().st_size > 0
    # Verify rotation metadata was applied
    probe_out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream_tags=rotate:stream_side_data=rotation",
            "-of",
            "default=noprint_wrappers=1",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # Some ffmpeg versions report rotation as side data, others as a tag.
    assert "90" in probe_out.stdout or "rotate" in probe_out.stdout.lower()


# ---------------------------------------------------------------------------
# CLI smoke (parsing only, no execution)
# ---------------------------------------------------------------------------


def test_cli_parses_subcommands() -> None:
    from publish.cli import main

    with mock.patch("publish.post.process") as proc:
        proc.return_value = Path("/tmp/x_published.mp4")
        rc = main(["process", "/tmp/x.mp4"])
        assert rc == 0
        proc.assert_called_once()
