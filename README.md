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
1. Issue `POST /selectPhotos` with an optional JSON body:
   ```bash
   curl -X POST http://<host>:8080/selectPhotos \
        -H 'Content-Type: application/json' \
        -d '{"maxItemCount": 25}'
   ```
   The response contains the `pickerUri`, a `sessionId`, and a `statusEndpoint`.
2. Direct the user to open the returned `pickerUri` to choose media.
3. Poll the status endpoint (or call `GET /selectPhotos?sessionId=<id>`) to monitor the
   session. Once the user finishes picking, the response will include the selected
   media items.

## License
This project is provided as-is without warranty.
