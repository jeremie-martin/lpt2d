"""Inbox watcher: pick up render bundles, upload to YouTube, record + delete.

The watcher is bundle-oriented. Each subdirectory of ``inbox`` is one render
bundle and contains at minimum::

    <bundle>/
      video.mp4
      params.json
      verdict.json     (optional)
      frame.shot.json  (optional)
      publish.json     (optional, per-bundle override of title/desc/tags/music)

Lifecycle markers (filesystem source of truth):

- ``<bundle>/uploaded`` — written after a successful YouTube upload; contains
  ``{"yt_id": ..., "uploaded_at": ...}``. The bundle is then bookkept in the
  ledger and the whole directory is deleted.
- ``<bundle>/failed`` — written on terminal failure (gate fail, upload error).
  A line is appended to ``failed.jsonl`` and the bundle is deleted too —
  the server keeps no archive.

Both ledgers carry the full ``params.json`` + ``verdict.json`` so analysis is
just ``jq`` or ``pandas.read_json(..., lines=True)``.

Crash safety: the order around the upload is
``upload → marker → state → rmtree → ledger``. If the watcher dies after the
marker exists but before the bundle is gone, the next tick sees the marker
and runs ``_finalize_resumed`` which rmtrees and writes a ``resumed=True``
ledger line. ``rmtree`` deliberately runs *before* the ledger append so a
persistent rmtree failure can't keep producing duplicate ledger lines tick
after tick. The duplicate-upload window is between the YouTube API returning
the id and the marker write — milliseconds, fsynced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from . import bundle as B
from . import post
from .ledger import Ledger, atomic_write_text, now_iso
from .metadata import PublishOverrides
from .state import State
from .titles import pick as pick_title_pool
from .youtube import (
    CATEGORY_FILM_ANIMATION,
    RateLimitError,
    YouTubeUploader,
)

SETTLE_SECONDS = 5.0
UploadFn = Callable[..., str]  # (processed: Path, **body) -> yt_id


class HandleResult(Enum):
    UPLOADED = "uploaded"
    RESUMED = "resumed"
    FAILED = "failed"
    THROTTLED = "throttled"


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    """Return parsed dict, or None if file is absent. Propagates JSONDecodeError."""
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_marker(bundle: Path, yt_id: str, uploaded_at: str) -> None:
    payload = json.dumps({"yt_id": yt_id, "uploaded_at": uploaded_at}, separators=(",", ":")) + "\n"
    atomic_write_text(bundle / B.MARKER_UPLOADED, payload, fsync_dir=True)


def _read_marker(bundle: Path) -> tuple[str, str | None]:
    data = json.loads((bundle / B.MARKER_UPLOADED).read_text())
    return data["yt_id"], data.get("uploaded_at")


def _resolve_metadata(overrides: PublishOverrides) -> tuple[str, str, list[str]]:
    title_default, description_default, tags_default = pick_title_pool()
    title = overrides.title_hint or title_default
    description = overrides.description_hint or description_default
    tags = overrides.tags or tags_default
    return title, description, tags


def _pending_bundles(inbox: Path) -> list[Path]:
    """Resumed (uploaded-marker) bundles come first so a throttled fresh
    bundle cannot starve the cleanup queue. ``uploaded`` takes precedence
    over ``failed`` because it represents a real YouTube id. Within each
    queue, process newest-first (LIFO)."""
    if not inbox.is_dir():
        return []
    resumed: list[tuple[float, Path]] = []
    fresh: list[tuple[float, Path]] = []
    now = time.time()
    for d in sorted(inbox.iterdir()):
        if not d.is_dir():
            continue
        # Dot-prefixed names are reserved for in-progress staging by the ship
        # script (`.staging_<name>.<pid>`). Skip them so we don't pick up a
        # half-rsynced bundle whose video.mp4 happened to be written first.
        if d.name.startswith("."):
            continue
        marker_uploaded = d / B.MARKER_UPLOADED
        if marker_uploaded.exists():
            resumed.append((marker_uploaded.stat().st_mtime, d))
            continue
        if (d / B.MARKER_FAILED).exists():
            continue
        video = d / B.VIDEO
        params = d / B.PARAMS
        if not (video.exists() and params.exists()):
            continue
        video_mtime = video.stat().st_mtime
        if (now - video_mtime) < SETTLE_SECONDS:
            continue
        fresh.append((video_mtime, d))
    sort_key = lambda item: (item[0], item[1].name)
    return (
        [d for _, d in sorted(resumed, key=sort_key, reverse=True)]
        + [d for _, d in sorted(fresh, key=sort_key, reverse=True)]
    )


def _build_upload_entry(
    bundle: Path,
    video_id: str,
    *,
    uploaded_at: str,
    title: str,
    description: str,
    tags: list[str],
    music_path: Path | None,
    music_dir: Path | None,
    privacy: str,
    params: dict[str, Any] | None,
    verdict: dict[str, Any] | None,
    processed_path: Path,
) -> dict[str, Any]:
    duration_s: float | None = None
    file_size: int | None = None
    try:
        info = post.probe(processed_path)
        duration_s = info.duration_s
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("ffprobe failed for {}: {!r}", processed_path, e)
    try:
        file_size = processed_path.stat().st_size
    except OSError:
        pass

    music_field: dict[str, str] | None = None
    if music_path is not None:
        try:
            relpath = (
                str(music_path.relative_to(music_dir)) if music_dir is not None else music_path.name
            )
        except ValueError:
            relpath = music_path.name
        music_field = {"filename": music_path.name, "relpath": relpath}

    return {
        "uploaded_at": uploaded_at,
        "youtube_id": video_id,
        "youtube_url": f"https://youtu.be/{video_id}",
        "bundle_name": bundle.name,
        "title": title,
        "description": description,
        "tags": list(tags),
        "music": music_field,
        "privacy": privacy,
        "duration_s": duration_s,
        "file_size": file_size,
        "params": params,
        "verdict": verdict,
    }


def _record_failure(
    bundle: Path,
    reason: str,
    *,
    ledger: Ledger,
    params: dict[str, Any] | None,
    verdict: dict[str, Any] | None,
) -> None:
    (bundle / B.MARKER_FAILED).write_text(reason)
    ledger.append_failure(
        {
            "failed_at": now_iso(),
            "bundle_name": bundle.name,
            "reason": reason,
            "params": params,
            "verdict": verdict,
        }
    )
    logger.error("Failed bundle {} ({}); deleting", bundle.name, reason)
    shutil.rmtree(bundle)


def _read_for_resume(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(parsed_or_None, error_repr_or_None)``. Captures parse errors
    instead of swallowing them so the resumed ledger entry preserves auditability."""
    try:
        return _read_json_optional(path), None
    except json.JSONDecodeError as e:
        return None, repr(e)


def _finalize_resumed(bundle: Path, ledger: Ledger) -> None:
    yt_id, marker_uploaded_at = _read_marker(bundle)
    params, params_err = _read_for_resume(bundle / B.PARAMS)
    verdict, verdict_err = _read_for_resume(bundle / B.VERDICT)
    entry: dict[str, Any] = {
        "uploaded_at": marker_uploaded_at or now_iso(),
        "youtube_id": yt_id,
        "youtube_url": f"https://youtu.be/{yt_id}",
        "bundle_name": bundle.name,
        "title": None,
        "description": None,
        "tags": [],
        "music": None,
        "privacy": None,
        "duration_s": None,
        "file_size": None,
        "params": params,
        "verdict": verdict,
        "resumed": True,
    }
    if params_err is not None:
        entry["params_error"] = params_err
    if verdict_err is not None:
        entry["verdict_error"] = verdict_err
    # rmtree before ledger so a persistent rmtree failure can't cause repeat
    # ticks to keep appending duplicate `resumed=True` lines.
    shutil.rmtree(bundle)
    ledger.append_upload(entry)
    logger.warning(
        "Resumed crashed upload for {} (yt_id={}); finalized + deleted", bundle.name, yt_id
    )


def _handle(
    bundle: Path,
    *,
    upload_fn: UploadFn,
    ledger: Ledger,
    state: State,
    music_dir: Path,
    privacy: str,
    min_interval: int,
) -> HandleResult:
    """Process one bundle. ``THROTTLED`` means no later fresh bundle in the
    same tick can succeed either, so the caller should break."""
    if (bundle / B.MARKER_UPLOADED).exists():
        _finalize_resumed(bundle, ledger)
        return HandleResult.RESUMED

    wait = state.seconds_until_next_allowed(min_interval)
    if wait > 0:
        logger.debug("Throttled: {} more seconds until next upload allowed", wait)
        return HandleResult.THROTTLED

    # params.json / verdict.json: missing → ok; present but unparseable → fail closed.
    try:
        params = _read_json_optional(bundle / B.PARAMS)
    except json.JSONDecodeError as e:
        _record_failure(
            bundle,
            f"params.json unreadable: {e!r}",
            ledger=ledger,
            params=None,
            verdict=None,
        )
        return HandleResult.FAILED
    try:
        verdict = _read_json_optional(bundle / B.VERDICT)
    except json.JSONDecodeError as e:
        _record_failure(
            bundle,
            f"verdict.json unreadable: {e!r}",
            ledger=ledger,
            params=params,
            verdict=None,
        )
        return HandleResult.FAILED

    def fail(reason: str) -> HandleResult:
        _record_failure(bundle, reason, ledger=ledger, params=params, verdict=verdict)
        return HandleResult.FAILED

    if verdict is not None and not verdict.get("ok", True):
        return fail("verdict.ok == false")

    overrides = PublishOverrides.from_bundle(bundle)
    title, description, tags = _resolve_metadata(overrides)

    try:
        processed, music_used = post.process(
            bundle / B.VIDEO,
            music=True,
            music_dir=music_dir,
            music_override=overrides.music,
        )
    except FileNotFoundError as e:
        # Almost always a typo in publish.json:music — keep the bad filename
        # in the failed.jsonl reason so the operator sees it directly.
        return fail(
            f"music override not found: {overrides.music!r}"
            if overrides.music
            else f"file not found: {e!r}"
        )
    except Exception as e:
        logger.exception("Post-process failed for {}", bundle.name)
        return fail(f"post-process failed: {e!r}")

    logger.info("Uploading {} as {!r}", bundle.name, title)
    try:
        yt_id = upload_fn(
            processed,
            title=title,
            description=description,
            tags=list(tags),
            privacy_status=privacy,
            category_id=CATEGORY_FILM_ANIMATION,
        )
    except RateLimitError:
        raise
    except Exception as e:
        logger.exception("Upload failed for {}", bundle.name)
        return fail(f"upload failed: {e!r}")

    # Build the ledger entry while the processed file still exists; append
    # after rmtree so a persistent rmtree failure can't produce duplicate
    # `resumed=True` lines on retry.
    uploaded_at = now_iso()
    entry = _build_upload_entry(
        bundle,
        yt_id,
        uploaded_at=uploaded_at,
        title=title,
        description=description,
        tags=list(tags),
        music_path=music_used,
        music_dir=music_dir,
        privacy=privacy,
        params=params,
        verdict=verdict,
        processed_path=processed,
    )
    _write_marker(bundle, yt_id, uploaded_at)
    state.record_upload()
    shutil.rmtree(bundle)
    ledger.append_upload(entry)
    logger.success("Uploaded {} -> https://youtu.be/{}", bundle.name, yt_id)
    return HandleResult.UPLOADED


def _build_upload_fn(
    credentials_dir: Path,
    *,
    playlist_id: str | None,
    dry_run: bool,
) -> UploadFn:
    if dry_run:
        return lambda processed, **_: f"DRYRUN-{processed.stem}"

    uploader = YouTubeUploader(credentials_dir)
    uploader.authenticate()

    def _upload(processed: Path, **body: Any) -> str:
        return uploader.upload(processed, **body, playlist_id=playlist_id)

    return _upload


def watch(
    inbox: Path,
    music_dir: Path,
    credentials_dir: Path,
    state_file: Path,
    ledger_dir: Path,
    *,
    playlist_id: str | None = None,
    privacy_status: str = "private",
    interval: int = 30,
    min_interval: int = 0,
    dry_run: bool = False,
) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(ledger_dir)
    state = State.load(state_file)
    upload_fn = _build_upload_fn(credentials_dir, playlist_id=playlist_id, dry_run=dry_run)

    if dry_run:
        logger.warning("DRY-RUN mode: uploads will NOT hit YouTube; ids will be DRYRUN-*")
    logger.info(
        "Watching {} every {}s (min_interval={}s, privacy={}, dry_run={})",
        inbox,
        interval,
        min_interval,
        privacy_status,
        dry_run,
    )

    while True:
        for bundle in _pending_bundles(inbox):
            try:
                result = _handle(
                    bundle,
                    upload_fn=upload_fn,
                    ledger=ledger,
                    state=state,
                    music_dir=music_dir,
                    privacy=privacy_status,
                    min_interval=min_interval,
                )
            except RateLimitError as e:
                wait = e.retry_after or 3600
                logger.warning("Rate-limited by YouTube: sleeping {}s", wait)
                time.sleep(wait)
                break
            except Exception:
                logger.exception("Unexpected error processing {}", bundle.name)
                continue

            if result is HandleResult.THROTTLED:
                break

        time.sleep(interval)


def process_one(
    bundle: Path,
    music_dir: Path,
    credentials_dir: Path,
    state_file: Path,
    ledger_dir: Path,
    *,
    playlist_id: str | None = None,
    privacy_status: str = "private",
    min_interval: int = 0,
    dry_run: bool = False,
) -> None:
    """One-shot: process a single bundle directory and exit."""
    ledger = Ledger(ledger_dir)
    state = State.load(state_file)
    upload_fn = _build_upload_fn(credentials_dir, playlist_id=playlist_id, dry_run=dry_run)
    _handle(
        bundle,
        upload_fn=upload_fn,
        ledger=ledger,
        state=state,
        music_dir=music_dir,
        privacy=privacy_status,
        min_interval=min_interval,
    )
