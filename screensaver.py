import os
import random
import requests
import threading
import time
import pickle
import subprocess
import json

from google.auth.transport.requests import Request, AuthorizedSession
from google_auth_oauthlib.flow import InstalledAppFlow

# Scope used by the Google Photos Photo Picker. The picker only grants access to
# media items explicitly selected by the user, so this scope is less sensitive
# than the full library read scope that recently started to require app
# verification.
PICKER_SCOPE = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
TOKEN_PATH = "screensaver/token.pickle"
SELECTION_FILE = "screensaver/selection.json"


class Screensaver:
    """Download and display photos selected via the Google Photo Picker."""

    def __init__(self, selection_file: str = SELECTION_FILE):
        self.running = False
        self.thread = None
        self.selection_file = selection_file
        self.media_item_ids = self._load_media_item_ids()

    # ------------------------------------------------------------------ utils
    def _load_media_item_ids(self):
        if os.path.exists(self.selection_file):
            with open(self.selection_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return []

    def refresh_selection(self):
        """Open the Photo Picker and persist the chosen media item ids.

        The Photo Picker runs in the user's browser as part of the OAuth flow.
        When the user finishes selecting items, the API responds with a set of
        media item identifiers that can later be retrieved without listing the
        entire photo library.
        """

        creds = get_credentials()
        session = AuthorizedSession(creds)
        response = session.post(
            "https://photoslibrary.googleapis.com/v1/picker:pick",
            json={"maxSelect": 100},
        )
        response.raise_for_status()
        ids = [item["mediaItemId"] for item in response.json().get("mediaItems", [])]
        with open(self.selection_file, "w", encoding="utf-8") as fh:
            json.dump(ids, fh)
        self.media_item_ids = ids

    # ------------------------------------------------------------------ thread
    def _run(self):
        while self.running:
            try:
                self.get_random_photo_and_save()
            except Exception as exc:  # pragma: no cover - broad but intentional
                print(f"Screensaver error: {exc}")
            finally:
                time.sleep(120)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            print("Screensaver Service started.")

    def stop(self):
        if self.running:
            self.running = False
            self.thread.join()
            print("Screensaver Service stopped.")

    # ----------------------------------------------------------------- photos
    def get_random_photo_and_save(self):
        if not self.media_item_ids:
            print("No media selected. Run refresh_selection() to choose photos via Photo Picker.")
            return

        creds = get_credentials()
        session = AuthorizedSession(creds)
        photo_id = random.choice(self.media_item_ids)
        resp = session.get(f"https://photoslibrary.googleapis.com/v1/mediaItems/{photo_id}")
        resp.raise_for_status()
        base_url = resp.json()["baseUrl"]
        filename = "screensaver/photo.jpg"
        download_image(base_url, filename)
        displayOnScreen()


# -------------------------------------------------------------------- auth util

def get_credentials():
    """Obtain OAuth credentials for the Photo Picker."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "screensaver/credentials.json", PICKER_SCOPE
            )
            # run_local_server launches a browser which hosts the Photo Picker UI.
            creds = flow.run_local_server(port=8080)
        with open(TOKEN_PATH, "wb") as token:
            pickle.dump(creds, token)
    return creds


# ------------------------------------------------------------------ image util

def download_image(url, filename):
    full_resolution_url = url + "=d"  # Request full-resolution image
    response = requests.get(full_resolution_url)
    if response.status_code == 200:
        with open(filename, "wb") as file:
            file.write(response.content)


def displayOnScreen():
    subprocess.run(["killall", "feh"], check=False)
    # Resize image to fit 9:16 ratio
    subprocess.run(
        [
            "convert",
            "screensaver/photo.jpg",
            "-resize",
            "1920x1080^",
            "-gravity",
            "center",
            "-crop",
            "1920x1080+0+0",
            "+repage",
            "screensaver/photo.jpg",
        ],
        check=False,
    )
    subprocess.run(
        [
            "feh",
            "--fullscreen",
            "--auto-zoom",
            "--action1",
            ";killall feh",
            "--borderless",
            "--on-last-slide",
            "quit",
            "--auto-reload",
            "screensaver/photo.jpg",
            "&",
        ],
        shell=True,
        check=False,
    )
