from flask import Flask, request
import subprocess
import os
import screensaver

app = Flask(__name__)
service = screensaver.Screensaver()

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

if __name__ == "__main__":
    subprocess.run(['export DISPLAY=:0.0'], shell=True)
    is_debug_mode = os.environ.get('http.debug', 'false').lower() == 'true'
    app.run(debug=is_debug_mode, port=8080,host='0.0.0.0')