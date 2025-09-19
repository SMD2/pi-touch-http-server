# Pi Touch HTTP Server

A lightweight Flask-based web server intended for a Raspberry Pi with a touch display.
It exposes HTTP endpoints for controlling the display power state, launching a Google
Photos Picker session, and a minimal in-memory publish/subscribe message queue.

## Features
- **Display control:** `GET /display?cmd=on|off` uses `xset` to toggle the HDMI display.
- **Google Photos Picker integration:**
  - `POST /selectPhotos` creates a Picker session, returning a `pickerUri` the user can
    open in the Google Photos app or web UI. The backend polls the session for up to
    15 minutes, following the Picker API guidance, and caches the selected media.
  - `GET /selectPhotos?sessionId=<id>` returns the cached status, including any picked
    media items once available.
- **Publish/Subscribe:**
  - `POST /publish` accepts a JSON payload and enqueues it.
  - `GET /subscribe` returns and removes the oldest queued message.
- Serves `static/index.html` when visiting `/`.

## Requirements
- Python 3
- Flask
- requests
- google-auth
- google-auth-oauthlib

Install the Python dependencies with:

```bash
pip install flask requests google-auth google-auth-oauthlib
```

## Configuring Google Photos Picker OAuth
1. Create an OAuth 2.0 Client ID (type **Desktop**) in Google Cloud Console.
2. Download the client configuration JSON and save it as `screensaver/credentials.json`.
3. Ensure the `screensaver/` directory is writable so the app can persist
   `picker_token.json` with refreshed tokens.
4. On first run you will be prompted to complete the OAuth flow. The application requests
   the `https://www.googleapis.com/auth/photospicker.mediaitems.readonly` scope.

## Running
```bash
python server.py
```

The server listens on port **8080** on all interfaces.

## Example Picker workflow

The following `curl` commands demonstrate an end-to-end session using the Picker API.

1. **Create a session** (optionally constrain the selection with `maxItemCount`):
   ```bash
   curl -sS -X POST http://<host>:8080/selectPhotos \
        -H 'Content-Type: application/json' \
        -d '{"maxItemCount": 25}'
   ```
   A successful response resembles:
   ```json
   {
     "sessionId": "41b6f2fd-bf22-4242-94e9-1b6f640a2501",
     "pickerUri": "https://photos.google.com/picker/...",
     "status": "PENDING",
     "statusEndpoint": "http://<host>:8080/selectPhotos?sessionId=41b6f2fd-bf22-4242-94e9-1b6f640a2501"
   }
   ```

2. **Share the `pickerUri`** with the user so they can finish the media selection in
   the Google Photos app or web UI.

3. **Poll for completion** (repeat until `state` becomes `COMPLETE` or `ERROR`):
   ```bash
   curl -sS "http://<host>:8080/selectPhotos?sessionId=41b6f2fd-bf22-4242-94e9-1b6f640a2501"
   ```
   While pending, the response will include metadata and the recommended polling
   cadence:
   ```json
   {
     "sessionId": "41b6f2fd-bf22-4242-94e9-1b6f640a2501",
     "state": "PENDING",
     "pollIntervalSeconds": 5.0,
     "pollingDeadline": "2024-02-21T17:05:42.123456+00:00"
   }
   ```

4. **Retrieve the selected media** once the state becomes `COMPLETE`:
   ```bash
   curl -sS "http://<host>:8080/selectPhotos?sessionId=41b6f2fd-bf22-4242-94e9-1b6f640a2501" | jq '.mediaItems'
   ```
   The array includes every chosen item with its metadata and download URLs returned
   by Google Photos Picker.

5. (Optional) **Abort a session** if needed by calling:
   ```bash
   curl -sS -X DELETE "https://photospicker.googleapis.com/v1/sessions/41b6f2fd-bf22-4242-94e9-1b6f640a2501"
   ```
   The `PhotosPickerService` automatically stops polling when the session completes or
   times out, but explicit cleanup can be useful while testing.

## License
This project is provided as-is without warranty.
