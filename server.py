import uuid
from collections import deque
import subprocess

from flask import Flask, jsonify, request, send_from_directory, url_for

from screensaver import (
    CredentialConfigurationError,
    PhotosPickerApiError,
    PhotosPickerService,
    PhotosPickerServiceError,
)

app = Flask(__name__)
picker_service = PhotosPickerService()

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


@app.route('/selectPhotos', methods=['POST'])
def create_selection_session():
    payload = request.get_json(silent=True) or {}

    request_id_value = payload.get('requestId')
    if request_id_value:
        try:
            request_id_value = str(uuid.UUID(str(request_id_value)))
        except (ValueError, AttributeError):
            return jsonify({'error': 'requestId must be a valid UUID string.'}), 400

    picking_config = None
    if 'maxItemCount' in payload and payload['maxItemCount'] is not None:
        try:
            max_items = int(payload['maxItemCount'])
        except (TypeError, ValueError):
            return jsonify({'error': 'maxItemCount must be an integer.'}), 400
        if max_items < 0:
            return jsonify({'error': 'maxItemCount must be non-negative.'}), 400
        if max_items > 0:
            picking_config = {'maxItemCount': str(max_items)}

    try:
        session_data = picker_service.create_session(
            picking_config=picking_config,
            request_id=request_id_value,
        )
    except CredentialConfigurationError as exc:
        return jsonify({'error': str(exc)}), 500
    except PhotosPickerApiError as exc:
        error_payload = {'error': str(exc)}
        if exc.status:
            error_payload['status'] = exc.status
        if exc.status_code:
            error_payload['statusCode'] = exc.status_code
        if exc.details:
            error_payload['details'] = exc.details
        return jsonify(error_payload), 502
    except PhotosPickerServiceError as exc:
        return jsonify({'error': str(exc)}), 500

    status_payload = picker_service.get_status(session_data['id'])
    status_url = url_for('get_selection_session', sessionId=session_data['id'], _external=True)

    response = {
        'sessionId': session_data['id'],
        'pickerUri': session_data.get('pickerUri'),
        'expireTime': session_data.get('expireTime'),
        'status': status_payload.get('state') if status_payload else 'UNKNOWN',
        'statusEndpoint': status_url,
    }

    if status_payload:
        if status_payload.get('requestId'):
            response['requestId'] = status_payload['requestId']
        if status_payload.get('pollingDeadline'):
            response['pollingDeadline'] = status_payload['pollingDeadline']
        if status_payload.get('pollIntervalSeconds') is not None:
            response['pollIntervalSeconds'] = status_payload['pollIntervalSeconds']

    return jsonify(response), 200


@app.route('/selectPhotos', methods=['GET'])
def get_selection_session():
    session_id = request.args.get('sessionId')
    if not session_id:
        return jsonify({'error': 'sessionId query parameter is required.'}), 400

    status_payload = picker_service.get_status(session_id)
    if not status_payload:
        return jsonify({'error': 'Session not found.'}), 404

    return jsonify(status_payload), 200


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
    app.run(debug=False, port=8080, host='0.0.0.0')
