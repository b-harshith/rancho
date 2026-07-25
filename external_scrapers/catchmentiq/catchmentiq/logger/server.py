from flask import Flask, render_template
from flask_sock import Sock
import json
import logging

# Disable default flask logging to keep stdout clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__, template_folder='templates')
sock = Sock(app)

# Track active WebSocket connections
clients = set()

@sock.route('/ws')
def ws_handler(ws):
    clients.add(ws)
    try:
        # Keep connection open
        while True:
            # We can optionally receive messages, but this is read-only for now
            data = ws.receive()
            if data is None:
                break
    except Exception:
        pass
    finally:
        clients.discard(ws)

@app.route('/')
def index():
    return render_template('dashboard.html')

def broadcast(message_dict: dict):
    """Broadcasting utility to send a message to all connected clients."""
    payload = json.dumps(message_dict)
    disconnected = []
    for client in list(clients):
        try:
            client.send(payload)
        except Exception:
            disconnected.append(client)
    for d in disconnected:
        clients.discard(d)
