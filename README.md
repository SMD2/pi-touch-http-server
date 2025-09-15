# Pi Touch HTTP Server

A lightweight Flask-based web server intended for a Raspberry Pi with a touch display.
It exposes simple HTTP endpoints for turning the screen on/off, starting or stopping a
Google Photos backed screensaver, and a minimal in-memory publish/subscribe message queue.

## Features
- **Display control:** `/display?cmd=on|off` uses `xset` to control DPMS state.
- **Screensaver service:** `/screensaver?cmd=on|off` fetches a random image from a
  Google Photos album named `PiTouch` and displays it using `feh`.
- **Publish/Subscribe:**
  - `POST /publish` accepts a JSON payload and enqueues it.
  - `GET /subscribe` returns and removes the oldest queued message.
- Serves `static/index.html` when visiting `/`.

## Requirements
- Python 3
- Flask
- requests
- schedule
- google-auth, google-auth-oauthlib, google-api-python-client
- System packages: `feh`, `imagemagick` (for `convert`)

These can be installed with:
```bash
pip install flask requests schedule google-auth google-auth-oauthlib google-api-python-client
```

## Running
1. Ensure you have Google Photos API credentials in `screensaver/credentials.json` and
   a writable `screensaver/` directory for tokens and downloaded images.
2. Start the server:
```bash
python server.py
```
The server listens on port **8080** on all interfaces.

## License
This project is provided as-is without warranty.
