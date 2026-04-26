"""CLI for the publish pipeline. Run via ``uv run python -m publish``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PUBLISH_HOME = Path.home() / "lpt2d-publish"
DEFAULT_INBOX = PUBLISH_HOME / "inbox"
DEFAULT_ARCHIVE = PUBLISH_HOME / "archive"
DEFAULT_MUSIC = PUBLISH_HOME / "music"
DEFAULT_CREDENTIALS = PUBLISH_HOME / "credentials"


def _progress_writer(prefix: str = "Upload"):
    def cb(p: float) -> None:
        sys.stderr.write(f"\r{prefix}: {p * 100:5.1f}%")
        sys.stderr.flush()

    return cb


def _resolve_metadata(video: Path) -> tuple[str, str, list[str]]:
    """Pick title/description/tags, honoring sidecar hints when present."""
    from .metadata import load_or_probe
    from .titles import pick

    meta = load_or_probe(video)
    t, d, ts = pick()
    title: str = meta.title_hint or t
    description: str = meta.description_hint or d
    tags: list[str] = meta.tags or ts
    return title, description, tags


def _cmd_process(args: argparse.Namespace) -> int:
    from .post import process

    out = process(
        Path(args.input),
        output_path=Path(args.output) if args.output else None,
        music=bool(args.music),
        music_dir=Path(args.music_dir) if args.music else None,
        rotate_cw=not args.ccw,
    )
    print(out)
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    from .titles import pick
    from .youtube import CATEGORY_FILM_ANIMATION, YouTubeUploader

    t, d, ts = pick()
    title: str = args.title or t
    description: str = args.description or d
    tags: list[str] = args.tags if args.tags is not None else ts

    uploader = YouTubeUploader(Path(args.credentials_dir))
    uploader.authenticate()

    video_id = uploader.upload(
        Path(args.video),
        title=title,
        description=description,
        tags=tags,
        privacy_status=args.privacy,
        category_id=CATEGORY_FILM_ANIMATION,
        playlist_id=args.playlist,
        progress_callback=_progress_writer(),
    )
    sys.stderr.write("\n")
    print(f"https://youtu.be/{video_id}")
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    from .post import process
    from .youtube import CATEGORY_FILM_ANIMATION, YouTubeUploader

    src = Path(args.input)
    out = process(src, music=True, music_dir=Path(args.music_dir))
    title, description, tags = _resolve_metadata(src)

    uploader = YouTubeUploader(Path(args.credentials_dir))
    uploader.authenticate()
    video_id = uploader.upload(
        out,
        title=title,
        description=description,
        tags=tags,
        privacy_status=args.privacy,
        category_id=CATEGORY_FILM_ANIMATION,
        playlist_id=args.playlist,
        progress_callback=_progress_writer(),
    )
    sys.stderr.write("\n")
    print(f"https://youtu.be/{video_id}")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    from .watcher import watch

    watch(
        inbox=Path(args.inbox),
        archive=Path(args.archive),
        music_dir=Path(args.music_dir),
        credentials_dir=Path(args.credentials_dir),
        playlist_id=args.playlist,
        privacy_status=args.privacy,
        interval=args.interval,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="publish", description="Process and publish lpt2d renders to YouTube."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("process", help="Process a single video (no upload).")
    pp.add_argument("input")
    pp.add_argument(
        "-o", "--output", default=None, help="Output path (default: <input>_published.mp4)"
    )
    pp.add_argument("--music", action="store_true", help="Mux a random track from --music-dir")
    pp.add_argument("--music-dir", default=str(DEFAULT_MUSIC))
    pp.add_argument(
        "--ccw", action="store_true", help="Rotate CCW instead of CW for horizontal sources"
    )
    pp.set_defaults(func=_cmd_process)

    up = sub.add_parser("upload", help="Upload a video to YouTube.")
    up.add_argument("video")
    up.add_argument("--title", default=None)
    up.add_argument("--description", default=None)
    up.add_argument("--tags", nargs="*", default=None)
    up.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    up.add_argument("--playlist", default=None, help="Playlist id to insert into after upload")
    up.add_argument("--credentials-dir", default=str(DEFAULT_CREDENTIALS))
    up.set_defaults(func=_cmd_upload)

    pub = sub.add_parser("publish", help="Process + upload in one shot.")
    pub.add_argument("input")
    pub.add_argument("--music-dir", default=str(DEFAULT_MUSIC))
    pub.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    pub.add_argument("--playlist", default=None)
    pub.add_argument("--credentials-dir", default=str(DEFAULT_CREDENTIALS))
    pub.set_defaults(func=_cmd_publish)

    wc = sub.add_parser("watch", help="Watch the inbox and publish new videos.")
    wc.add_argument("--inbox", default=str(DEFAULT_INBOX))
    wc.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    wc.add_argument("--music-dir", default=str(DEFAULT_MUSIC))
    wc.add_argument("--credentials-dir", default=str(DEFAULT_CREDENTIALS))
    wc.add_argument("--playlist", default=None)
    wc.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    wc.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    wc.set_defaults(func=_cmd_watch)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)
