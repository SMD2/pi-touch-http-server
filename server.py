import time
from flask import Flask, request, jsonify, send_from_directory
from collections import deque
import subprocess
import os
import screensaver

app = Flask(__name__)
service = screensaver.Screensaver()

# Initialize an in-memory queue using deque from collections for efficient FIFO operations.
messages_queue = deque()

@app.route('/display', methods=['GET'])
def control_display():
    cmd = request.args.get('cmd')

    if cmd == 'on':
        subprocess.run(['DISPLAY=:0 xset dpms force on'], shell=True)
    elif cmd == 'off':
        subprocess.run(['DISPLAY=:0 xset dpms force off'], shell=True)
    else:
        return "Invalid command", 400

    return f"Display turned {cmd}", 200

@app.route('/screensaver', methods=['GET'])
def control_screensaver():
    cmd = request.args.get('cmd')

    if cmd == 'on':
        #subprocess.run(['feh --fullscreen --auto-zoom --action1 ";killall feh" --borderless --on-last-slide quit --auto-reload  /opt/google-photos-screensaver/photo.jpg &'], shell=True)
        service.start()
    elif cmd == 'off':
        subprocess.run(['killall feh'], shell=True)
    else:
        return "Invalid command", 400

    return f"Screensaver turned {cmd}", 200

@app.route('/publish', methods=['POST'])
def publish():
    # Extract the JSON object from the request and add it to the queue.
    message = request.json
    messages_queue.append(message)
    return jsonify({'status': 'Message added to queue'}), 200

@app.route('/subscribe', methods=['GET'])
def subscribe():
    if messages_queue:
        # Pop the leftmost (oldest) message from the queue to process it.
        message = messages_queue.popleft()
        return jsonify(message), 200
    else:
        # If the queue is empty, inform the subscriber.
        return jsonify({'status': 'No messages in queue'}), 200

@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

if __name__ == "__main__":
    subprocess.run(['export DISPLAY=:0.0'], shell=True)
    service.start()
    app.run(debug=False, port=8080,host='0.0.0.0')