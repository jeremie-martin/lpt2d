"""CLI for the publish pipeline. Run via ``uv run python -m publish``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

PUBLISH_HOME = Path.home() / "lpt2d-publish"
DEFAULT_INBOX = PUBLISH_HOME / "inbox"
DEFAULT_MUSIC = PUBLISH_HOME / "music"
DEFAULT_CREDENTIALS = PUBLISH_HOME / "credentials"
DEFAULT_STATE = PUBLISH_HOME / "state.json"
DEFAULT_LEDGER_DIR = PUBLISH_HOME
DEFAULT_LOG = PUBLISH_HOME / "watcher.log"


def _configure_logging(log_path: Path | None) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> <level>{level: <8}</level> {message}",
    )
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            level="INFO",
            rotation="1 day",
            retention="30 days",
            format="{time:YYYY-MM-DD HH:mm:ss} {level: <8} {message}",
        )


def _progress_writer(prefix: str = "Upload"):
    def cb(p: float) -> None:
        sys.stderr.write(f"\r{prefix}: {p * 100:5.1f}%")
        sys.stderr.flush()

    return cb


def _cmd_process(args: argparse.Namespace) -> int:
    from .post import process

    out, music_used = process(
        Path(args.input),
        output_path=Path(args.output) if args.output else None,
        music=bool(args.music),
        music_dir=Path(args.music_dir) if args.music else None,
        rotate_cw=not args.ccw,
    )
    print(out)
    if music_used is not None:
        logger.info("music: {}", music_used)
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
    """One-shot: process a single bundle directory through the full pipeline."""
    from .watcher import process_one

    bundle = Path(args.bundle).resolve()
    if not bundle.is_dir():
        logger.error("Bundle path is not a directory: {}", bundle)
        return 2

    process_one(
        bundle,
        music_dir=Path(args.music_dir),
        credentials_dir=Path(args.credentials_dir),
        state_file=Path(args.state_file),
        ledger_dir=Path(args.ledger_dir),
        playlist_id=args.playlist,
        privacy_status=args.privacy,
        min_interval=args.min_interval,
        dry_run=args.dry_run,
    )
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    from .watcher import watch

    watch(
        inbox=Path(args.inbox),
        music_dir=Path(args.music_dir),
        credentials_dir=Path(args.credentials_dir),
        state_file=Path(args.state_file),
        ledger_dir=Path(args.ledger_dir),
        playlist_id=args.playlist,
        privacy_status=args.privacy,
        interval=args.interval,
        min_interval=args.min_interval,
        dry_run=args.dry_run,
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
        "-o",
        "--output",
        default=None,
        help="Output path (default: <input>_published.mp4)",
    )
    pp.add_argument("--music", action="store_true", help="Mux a random track from --music-dir")
    pp.add_argument("--music-dir", default=str(DEFAULT_MUSIC))
    pp.add_argument(
        "--ccw",
        action="store_true",
        help="Rotate CCW instead of CW for horizontal sources",
    )
    pp.set_defaults(func=_cmd_process)

    up = sub.add_parser("upload", help="Upload a video to YouTube (no bundle/ledger).")
    up.add_argument("video")
    up.add_argument("--title", default=None)
    up.add_argument("--description", default=None)
    up.add_argument("--tags", nargs="*", default=None)
    up.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    up.add_argument("--playlist", default=None, help="Playlist id to insert into after upload")
    up.add_argument("--credentials-dir", default=str(DEFAULT_CREDENTIALS))
    up.set_defaults(func=_cmd_upload)

    pub = sub.add_parser(
        "publish",
        help="Run the full pipeline against one bundle directory (process + upload + ledger + delete).",
    )
    pub.add_argument("bundle", help="Path to bundle directory containing video.mp4 + params.json")
    pub.add_argument("--music-dir", default=str(DEFAULT_MUSIC))
    pub.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    pub.add_argument("--playlist", default=None)
    pub.add_argument("--credentials-dir", default=str(DEFAULT_CREDENTIALS))
    pub.add_argument("--state-file", default=str(DEFAULT_STATE))
    pub.add_argument("--ledger-dir", default=str(DEFAULT_LEDGER_DIR))
    pub.add_argument(
        "--min-interval",
        type=int,
        default=0,
        help="Minimum seconds between uploads (default: 0 for one-shot)",
    )
    pub.add_argument(
        "--dry-run", action="store_true", help="Do not call YouTube; emit DRYRUN-* ids"
    )
    pub.set_defaults(func=_cmd_publish)

    wc = sub.add_parser("watch", help="Watch the inbox and publish new bundles.")
    wc.add_argument("--inbox", default=str(DEFAULT_INBOX))
    wc.add_argument("--music-dir", default=str(DEFAULT_MUSIC))
    wc.add_argument("--credentials-dir", default=str(DEFAULT_CREDENTIALS))
    wc.add_argument("--state-file", default=str(DEFAULT_STATE))
    wc.add_argument("--ledger-dir", default=str(DEFAULT_LEDGER_DIR))
    wc.add_argument("--playlist", default=None)
    wc.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    wc.add_argument("--interval", type=int, default=60, help="Inbox poll interval in seconds")
    wc.add_argument(
        "--min-interval",
        type=int,
        default=3600,
        help="Minimum seconds between successful uploads (default: 3600 = 1/hour)",
    )
    wc.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call YouTube; emit DRYRUN-* ids and skip OAuth",
    )
    wc.add_argument("--log-file", default=str(DEFAULT_LOG))
    wc.set_defaults(func=_cmd_watch)

    args = parser.parse_args(argv)
    log_path = Path(getattr(args, "log_file", DEFAULT_LOG)) if args.cmd == "watch" else None
    _configure_logging(log_path)
    return args.func(args)
