import copy
import json
import logging
import os
import random
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)


class PhotosPickerServiceError(Exception):
    """Base exception raised for Photos Picker service failures."""


class CredentialConfigurationError(PhotosPickerServiceError):
    """Raised when OAuth credentials are not available."""


class PhotosPickerApiError(PhotosPickerServiceError):
    """Represents an error returned by the Google Photos Picker API."""

    def __init__(self, message: str, status_code: Optional[int] = None, status: Optional[str] = None,
                 details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.status = status
        self.details = details


@dataclass
class _SessionState:
    session: Dict[str, Any]
    state: str
    created_at: datetime
    updated_at: datetime
    last_polled_at: Optional[datetime]
    completed_at: Optional[datetime]
    media_items: List[Dict[str, Any]]
    error: Optional[Dict[str, Any]]
    deadline: datetime
    poll_interval_seconds: float
    request_id: str
    downloaded_files: List[str]


class PhotosPickerService:
    """Service wrapper around the Google Photos Picker API."""

    BASE_URL = "https://photospicker.googleapis.com/v1"
    SCOPES = ["https://www.googleapis.com/auth/photospicker.mediaitems.readonly"]
    DEFAULT_POLL_INTERVAL_SECONDS = 5.0
    MAX_POLL_DURATION = timedelta(minutes=15)
    DEFAULT_TOKEN_FILE = "picker_token.json"
    DEFAULT_OAUTH_PORT = 8090

    def __init__(self, storage_dir: str = "screensaver", credentials_file: str = "credentials.json",
                 token_file: Optional[str] = None) -> None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self._storage_dir = os.path.join(base_dir, storage_dir)
        self._credentials_path = os.path.join(self._storage_dir, credentials_file)
        token_filename = token_file or self.DEFAULT_TOKEN_FILE
        self._token_path = os.path.join(self._storage_dir, token_filename)
        os.makedirs(self._storage_dir, exist_ok=True)
        self._photos_dir = os.path.join(self._storage_dir, "photos")
        os.makedirs(self._photos_dir, exist_ok=True)

        self._cred_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._slideshow_lock = threading.Lock()
        self._slideshow_trigger = threading.Event()
        self._slideshow_stop = threading.Event()

        self._creds: Optional[Credentials] = None
        self._states: Dict[str, _SessionState] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._slideshow_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # OAuth handling
    # ------------------------------------------------------------------
    def _load_stored_credentials(self) -> Optional[Credentials]:
        if not os.path.exists(self._token_path):
            return None
        try:
            with open(self._token_path, "r", encoding="utf-8") as token_file:
                data = json.load(token_file)
            return Credentials.from_authorized_user_info(data, self.SCOPES)
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to load stored Google Photos Picker credentials: %s", exc)
            return None

    def _store_credentials(self, creds: Credentials) -> None:
        with open(self._token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    def _ensure_credentials(self) -> Credentials:
        with self._cred_lock:
            creds = self._creds
            if creds and creds.valid:
                return creds

            if not creds:
                creds = self._load_stored_credentials()

            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as exc:
                    logger.warning("Failed to refresh Google Photos Picker credentials: %s", exc)
                    creds = None

            if not creds or not creds.valid:
                if not os.path.exists(self._credentials_path):
                    raise CredentialConfigurationError(
                        f"OAuth client secrets not found at {self._credentials_path}. "
                        "Ensure the Google Photos Picker credentials are available."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self._credentials_path, self.SCOPES)
                creds = flow.run_local_server(port=self.DEFAULT_OAUTH_PORT, open_browser=False)

            self._store_credentials(creds)
            self._creds = creds
            return creds

    def _authorized_session(self) -> AuthorizedSession:
        creds = self._ensure_credentials()
        return AuthorizedSession(creds)

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _duration_to_timedelta(value: Optional[str]) -> Optional[timedelta]:
        if not value or not isinstance(value, str):
            return None
        if not value.endswith("s"):
            return None
        try:
            seconds = float(value[:-1])
        except ValueError:
            return None
        return timedelta(seconds=max(0.0, seconds))

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _register_session(self, session_data: Dict[str, Any], request_id: str,
                          poll_interval: float, deadline: datetime) -> None:
        now = self._now()
        state_value = "COMPLETE" if session_data.get("mediaItemsSet") else "PENDING"
        completed_at = now if state_value == "COMPLETE" else None
        with self._state_lock:
            self._states[session_data["id"]] = _SessionState(
                session=session_data,
                state=state_value,
                created_at=now,
                updated_at=now,
                last_polled_at=None,
                completed_at=completed_at,
                media_items=[],
                error=None,
                deadline=deadline,
                poll_interval_seconds=poll_interval,
                request_id=request_id,
                downloaded_files=[],
            )

    def _set_state(self, session_id: str, *, session: Optional[Dict[str, Any]] = None,
                   state: Optional[str] = None, media_items: Optional[List[Dict[str, Any]]] = None,
                   error: Optional[Dict[str, Any]] = None, last_polled_at: Optional[datetime] = None,
                   completed_at: Optional[datetime] = None,
                   downloaded_files: Optional[List[str]] = None) -> None:
        now = self._now()
        with self._state_lock:
            state_entry = self._states.get(session_id)
            if not state_entry:
                return
            if session is not None:
                state_entry.session = session
            if state is not None:
                state_entry.state = state
            if media_items is not None:
                state_entry.media_items = media_items
            if error is not None:
                state_entry.error = error
            if last_polled_at is not None:
                state_entry.last_polled_at = last_polled_at
            if completed_at is not None:
                state_entry.completed_at = completed_at
            if downloaded_files is not None:
                state_entry.downloaded_files = downloaded_files
            state_entry.updated_at = now

    def _serialize_state(self, session_id: str, state: _SessionState) -> Dict[str, Any]:
        def _iso(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt else None

        return {
            "sessionId": session_id,
            "state": state.state,
            "session": copy.deepcopy(state.session),
            "createdAt": _iso(state.created_at),
            "updatedAt": _iso(state.updated_at),
            "lastPolledAt": _iso(state.last_polled_at),
            "completedAt": _iso(state.completed_at),
            "pollingDeadline": _iso(state.deadline),
            "pollIntervalSeconds": state.poll_interval_seconds,
            "mediaItems": copy.deepcopy(state.media_items),
            "mediaItemsCount": len(state.media_items),
            "error": copy.deepcopy(state.error),
            "requestId": state.request_id,
            "downloadedFiles": list(state.downloaded_files),
            "downloadedFilesCount": len(state.downloaded_files),
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        session = self._authorized_session()
        url = f"{self.BASE_URL}{path}"
        kwargs.setdefault("timeout", 30)
        try:
            response = session.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise PhotosPickerServiceError(
                f"Failed to call Google Photos Picker API: {exc}" ) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": {"message": response.text or "Unknown error"}}
            error = payload.get("error", {})
            raise PhotosPickerApiError(
                error.get("message", "Google Photos Picker API error"),
                status_code=response.status_code,
                status=error.get("status"),
                details=error.get("details"),
            )

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise PhotosPickerServiceError("Failed to parse Google Photos Picker API response.") from exc

    def _fetch_media_items(self, session_id: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"sessionId": session_id, "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            data = self._request("GET", "/mediaItems", params=params)
            items.extend(data.get("mediaItems", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def _safe_fetch_media_items(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        try:
            return self._fetch_media_items(session_id)
        except PhotosPickerApiError as exc:
            if exc.status == "FAILED_PRECONDITION":
                return None
            raise

    # ------------------------------------------------------------------
    # Download handling & slideshow support
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return sanitized or "photo"

    @staticmethod
    def _extension_from_mime(mime_type: Optional[str]) -> str:
        if not mime_type:
            return ""
        if mime_type == "image/jpeg":
            return ".jpg"
        if mime_type == "image/png":
            return ".png"
        if mime_type == "image/gif":
            return ".gif"
        if mime_type in {"image/webp", "image/heic", "image/heif"}:
            return ".webp" if mime_type == "image/webp" else ".heic"
        if mime_type.startswith("video/"):
            return ".mp4"
        return ""

    def _download_media_items(self, session_id: str, media_items: List[Dict[str, Any]]) -> List[str]:
        if not media_items:
            return []

        session = self._authorized_session()
        downloaded_files: List[str] = []
        for index, item in enumerate(media_items, start=1):
            base_url = item.get("baseUrl")
            if not base_url:
                continue

            filename = item.get("filename") or f"{session_id}_{index}"
            filename = self._sanitize_filename(filename)
            if not os.path.splitext(filename)[1]:
                filename += self._extension_from_mime(item.get("mimeType"))
            file_path = os.path.join(self._photos_dir, filename)

            if os.path.exists(file_path):
                downloaded_files.append(os.path.relpath(file_path, self._storage_dir))
                continue

            download_url = f"{base_url}=d"
            try:
                response = session.get(download_url, timeout=120)
                response.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.warning("Failed to download media item %s: %s", item.get("id", "<unknown>"), exc)
                continue

            try:
                with open(file_path, "wb") as file_handle:
                    file_handle.write(response.content)
            except OSError as exc:
                logger.warning("Failed to store media item %s: %s", item.get("id", "<unknown>"), exc)
                continue

            downloaded_files.append(os.path.relpath(file_path, self._storage_dir))

        return downloaded_files

    def _list_downloaded_files(self) -> List[str]:
        try:
            entries = [
                os.path.relpath(os.path.join(self._photos_dir, entry), self._storage_dir)
                for entry in os.listdir(self._photos_dir)
                if os.path.isfile(os.path.join(self._photos_dir, entry))
            ]
        except FileNotFoundError:
            return []

        entries.sort()
        return entries

    def _choose_random_photo(self) -> Optional[str]:
        try:
            entries = [
                os.path.join(self._photos_dir, entry)
                for entry in os.listdir(self._photos_dir)
                if os.path.isfile(os.path.join(self._photos_dir, entry))
            ]
        except FileNotFoundError:
            return None

        if not entries:
            return None

        return random.choice(entries)

    @staticmethod
    def _launch_feh(photo_path: str) -> None:
        try:
            subprocess.run(["killall", "feh"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # pragma: no cover - defensive best-effort cleanup
            logger.debug("Failed to terminate existing feh instances", exc_info=True)

        cmd = [
            "feh",
            "--fullscreen",
            "--auto-zoom",
            "--borderless",
            "--quiet",
            photo_path,
        ]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logger.warning("Failed to launch feh for %s: %s", photo_path, exc)

    def _slideshow_loop(self) -> None:
        logger.info("Starting slideshow loop for Google Photos selections")
        try:
            while not self._slideshow_stop.is_set():
                triggered = self._slideshow_trigger.wait(timeout=120)
                self._slideshow_trigger.clear()

                if self._slideshow_stop.is_set():
                    break

                photo_path = self._choose_random_photo()
                if not photo_path:
                    if not triggered:
                        # No photos yet; try again on the next interval.
                        continue
                    # If triggered but nothing found, wait a short period before checking again
                    time.sleep(5)
                    continue

                self._launch_feh(photo_path)
        finally:
            logger.info("Slideshow loop terminated")

    def _start_slideshow(self) -> None:
        with self._slideshow_lock:
            if self._slideshow_thread and self._slideshow_thread.is_alive():
                self._slideshow_trigger.set()
                return

            self._slideshow_stop.clear()
            self._slideshow_trigger.set()
            thread = threading.Thread(
                target=self._slideshow_loop,
                name="photos-picker-slideshow",
                daemon=True,
            )
            self._slideshow_thread = thread
            thread.start()

    def _handle_session_completion(self, session_id: str, media_items: List[Dict[str, Any]]) -> None:
        self._download_media_items(session_id, media_items)
        all_files = self._list_downloaded_files()
        if all_files:
            self._set_state(session_id, downloaded_files=all_files)
            self._start_slideshow()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_session(self, picking_config: Optional[Dict[str, Any]] = None,
                       request_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new picking session and start polling for updates."""
        if request_id is None:
            request_id = str(uuid.uuid4())
        params = {"requestId": request_id}
        body: Dict[str, Any] = {}
        if picking_config:
            body["pickingConfig"] = picking_config

        session_data = self._request("POST", "/sessions", params=params, json=body)
        session_id = session_data.get("id")
        if not session_id:
            raise PhotosPickerServiceError("Session creation response did not include an ID.")

        polling_config = session_data.get("pollingConfig", {}) or {}
        poll_interval_td = self._duration_to_timedelta(polling_config.get("pollInterval"))
        poll_interval = poll_interval_td.total_seconds() if poll_interval_td else self.DEFAULT_POLL_INTERVAL_SECONDS
        poll_interval = max(1.0, poll_interval)

        timeout_td = self._duration_to_timedelta(polling_config.get("timeoutIn"))
        now = self._now()
        if timeout_td is None or timeout_td.total_seconds() <= 0:
            deadline = now + self.MAX_POLL_DURATION
        else:
            deadline = now + min(timeout_td, self.MAX_POLL_DURATION)

        self._register_session(session_data, request_id, poll_interval, deadline)

        if session_data.get("mediaItemsSet"):
            media_items = self._safe_fetch_media_items(session_id)
            if media_items is not None:
                self._set_state(session_id, media_items=media_items, state="COMPLETE",
                                completed_at=self._now())
                self._handle_session_completion(session_id, media_items)
        else:
            self._start_poll_thread(session_id, poll_interval, deadline)

        return session_data

    def _start_poll_thread(self, session_id: str, poll_interval: float, deadline: datetime) -> None:
        thread = threading.Thread(
            target=self._poll_session,
            args=(session_id, poll_interval, deadline),
            name=f"photos-picker-poll-{session_id}",
            daemon=True,
        )
        with self._state_lock:
            self._threads[session_id] = thread
        thread.start()

    def _poll_session(self, session_id: str, poll_interval: float, deadline: datetime) -> None:
        end_time = time.monotonic() + max(0.0, (deadline - self._now()).total_seconds())
        try:
            while time.monotonic() <= end_time:
                try:
                    session_data = self._request("GET", f"/sessions/{session_id}")
                except PhotosPickerApiError as exc:
                    error_payload = {"message": str(exc), "status": exc.status, "statusCode": exc.status_code}
                    self._set_state(session_id, state="ERROR", error=error_payload)
                    return
                except PhotosPickerServiceError as exc:
                    error_payload = {"message": str(exc)}
                    self._set_state(session_id, state="ERROR", error=error_payload)
                    return

                now = self._now()
                self._set_state(session_id, session=session_data, last_polled_at=now)

                if session_data.get("mediaItemsSet"):
                    try:
                        media_items = self._safe_fetch_media_items(session_id)
                    except PhotosPickerServiceError as exc:
                        error_payload = {"message": str(exc)}
                        self._set_state(session_id, state="ERROR", error=error_payload)
                        return

                    if media_items is not None:
                        self._set_state(session_id, state="COMPLETE", media_items=media_items,
                                        completed_at=self._now())
                        self._handle_session_completion(session_id, media_items)
                        return

                sleep_until = min(end_time - time.monotonic(), poll_interval)
                if sleep_until <= 0:
                    break
                time.sleep(sleep_until)

            self._set_state(session_id, state="TIMEOUT")
        finally:
            with self._state_lock:
                self._threads.pop(session_id, None)

    def get_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._state_lock:
            state = self._states.get(session_id)
            if not state:
                return None
            return self._serialize_state(session_id, state)

    def delete_session(self, session_id: str) -> None:
        """Delete a picking session and stop polling."""
        try:
            self._request("DELETE", f"/sessions/{session_id}")
        except PhotosPickerApiError as exc:
            if exc.status_code == 404:
                pass
            else:
                raise
        finally:
            with self._state_lock:
                self._states.pop(session_id, None)
                thread = self._threads.pop(session_id, None)
            if thread and thread.is_alive():
                # Threads will exit naturally when the state entry is removed.
                pass


# Backwards compatibility alias for existing imports.
Screensaver = PhotosPickerService
