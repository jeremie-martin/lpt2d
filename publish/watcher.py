"""Inbox watcher: poll for new videos, process them, upload to YouTube.

State is kept entirely in the filesystem via marker files next to each video:
- ``<video>.uploaded`` — video has been uploaded; contains the YouTube video id
- ``<video>.failed`` — video failed processing/upload; contains the error message

Successfully uploaded videos and their derivatives move to ``archive``.
Failed videos stay in the inbox alongside the marker for inspection.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from .post import process
from .titles import pick
from .youtube import (
    CATEGORY_FILM_ANIMATION,
    RateLimitError,
    UploadError,
    YouTubeUploader,
)

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}
SETTLE_SECONDS = 5.0


def _pending_videos(inbox: Path) -> list[Path]:
    out: list[Path] = []
    now = time.time()
    for p in sorted(inbox.iterdir()):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if (p.parent / (p.name + ".uploaded")).exists():
            continue
        if (p.parent / (p.name + ".failed")).exists():
            continue
        if (now - p.stat().st_mtime) < SETTLE_SECONDS:
            continue
        out.append(p)
    return out


def watch(
    inbox: Path,
    archive: Path,
    music_dir: Path,
    credentials_dir: Path,
    playlist_id: str | None = None,
    privacy_status: str = "private",
    interval: int = 30,
) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)

    uploader = YouTubeUploader(credentials_dir)
    uploader.authenticate()
    logger.info("Watching %s every %ds (archive=%s)", inbox, interval, archive)

    while True:
        for video in _pending_videos(inbox):
            try:
                logger.info("Processing %s", video.name)
                processed = process(video, music=True, music_dir=music_dir)
                title, description, tags = pick()
                logger.info("Uploading %s as %r", processed.name, title)
                video_id = uploader.upload(
                    processed,
                    title=title,
                    description=description,
                    tags=tags,
                    privacy_status=privacy_status,
                    category_id=CATEGORY_FILM_ANIMATION,
                    playlist_id=playlist_id,
                )
                logger.info("Uploaded: https://youtu.be/%s", video_id)

                marker = video.parent / (video.name + ".uploaded")
                marker.write_text(video_id)
                shutil.move(str(video), archive / video.name)
                if processed.exists():
                    shutil.move(str(processed), archive / processed.name)
                shutil.move(str(marker), archive / marker.name)
            except RateLimitError as e:
                wait = e.retry_after or 3600
                logger.warning("Rate limited, sleeping %ds", wait)
                time.sleep(wait)
                break
            except UploadError as e:
                logger.error("Upload error for %s: %s", video.name, e)
                (video.parent / (video.name + ".failed")).write_text(str(e))
            except Exception as e:
                logger.exception("Unexpected error for %s", video.name)
                (video.parent / (video.name + ".failed")).write_text(repr(e))

        time.sleep(interval)
