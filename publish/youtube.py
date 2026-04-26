"""YouTube API client: OAuth + resumable upload + playlist insert."""

from __future__ import annotations

import json
import logging
import pickle
from collections.abc import Callable
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

CATEGORY_FILM_ANIMATION = "1"
CATEGORY_MUSIC = "10"
CATEGORY_SCIENCE_TECH = "28"

_RATE_LIMIT_REASONS = {
    "quotaExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "dailyLimitExceeded",
}

logger = logging.getLogger(__name__)


class RateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class UploadError(RuntimeError):
    pass


class YouTubeUploader:
    def __init__(self, credentials_dir: Path | str):
        self.credentials_dir = Path(credentials_dir)
        self.client_secrets = self.credentials_dir / "client_secrets.json"
        self.token_path = self.credentials_dir / "token.pickle"
        self.youtube = None
        self._credentials = None

    @property
    def is_authenticated(self) -> bool:
        return self.youtube is not None and self._credentials is not None

    def authenticate(self, force_reauth: bool = False) -> None:
        creds = None
        if not force_reauth and self.token_path.exists():
            try:
                creds = pickle.loads(self.token_path.read_bytes())
            except Exception as e:
                logger.warning("Failed to load cached token: %s", e)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning("Token refresh failed, running OAuth flow: %s", e)
                    creds = None

            if not creds or not creds.valid:
                if not self.client_secrets.exists():
                    raise FileNotFoundError(
                        f"client_secrets.json not found at {self.client_secrets}\n"
                        "Download OAuth desktop credentials from Google Cloud Console "
                        "and place them there."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets), SCOPES)
                creds = flow.run_local_server(port=0)

            self.credentials_dir.mkdir(parents=True, exist_ok=True)
            self.token_path.write_bytes(pickle.dumps(creds))

        self._credentials = creds
        self.youtube = build("youtube", "v3", credentials=creds)

    def upload(
        self,
        video_path: Path | str,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str = "private",
        category_id: str = CATEGORY_FILM_ANIMATION,
        playlist_id: str | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> str:
        if not self.youtube:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,
        )

        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        try:
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status and progress_callback:
                    progress_callback(status.progress())
            video_id: str = response["id"]
        except HttpError as e:
            self._raise_http_error(e)
            raise  # unreachable; appeases type-checkers

        if playlist_id:
            try:
                self._add_to_playlist(video_id, playlist_id)
            except HttpError as e:
                logger.warning(
                    "Failed to add video %s to playlist %s: %s", video_id, playlist_id, e
                )

        return video_id

    def _add_to_playlist(self, video_id: str, playlist_id: str) -> None:
        assert self.youtube is not None  # caller is gated on is_authenticated
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            },
        }
        self.youtube.playlistItems().insert(part="snippet", body=body).execute()

    @staticmethod
    def _raise_http_error(e: HttpError) -> None:
        if e.resp.status == 403:
            try:
                content = json.loads(e.content.decode("utf-8"))
                for err in content.get("error", {}).get("errors", []):
                    if err.get("reason") in _RATE_LIMIT_REASONS:
                        raise RateLimitError(f"YouTube quota: {err.get('reason')}")
            except (json.JSONDecodeError, KeyError, AttributeError):
                pass
        if e.resp.status == 429:
            retry_after = e.resp.get("Retry-After")
            raise RateLimitError(
                "YouTube rate limit (429)",
                retry_after=int(retry_after) if retry_after else None,
            )
        raise UploadError(f"YouTube API error ({e.resp.status}): {e.reason}")
