#!/usr/bin/env python3
"""
Simple dev server with hot reload via Server-Sent Events.
Usage: python3 serve.py
Then open http://localhost:8080
"""

import http.server
import os
import queue
import threading
import time
import urllib.parse

PORT = 8080
WATCH_DIR = os.path.dirname(os.path.abspath(__file__))

# Each connected browser gets a queue; we push to all of them on change
_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()


def broadcast_reload():
    with _clients_lock:
        for q in _clients:
            q.put("reload")


def watch_files():
    """Poll file mtimes and broadcast when anything changes."""
    snapshot = {}

    def get_snapshot():
        result = {}
        for root, _, files in os.walk(WATCH_DIR):
            for f in files:
                if f.endswith((".html", ".css", ".js", ".svg", ".png", ".jpg")):
                    path = os.path.join(root, f)
                    try:
                        result[path] = os.path.getmtime(path)
                    except OSError:
                        pass
        return result

    snapshot = get_snapshot()
    while True:
        time.sleep(0.4)
        current = get_snapshot()
        if current != snapshot:
            snapshot = current
            print("Change detected — reloading…")
            broadcast_reload()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WATCH_DIR, **kwargs)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/reload":
            self._sse()
        else:
            super().do_GET()

    def _sse(self):
        q: queue.Queue = queue.Queue()
        with _clients_lock:
            _clients.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            while True:
                try:
                    q.get(timeout=25)
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                except queue.Empty:
                    # Keep-alive ping
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _clients_lock:
                _clients.remove(q)

    def log_message(self, fmt, *args):
        # Suppress /reload noise, show everything else
        if "/reload" not in args[0]:
            super().log_message(fmt, *args)


if __name__ == "__main__":
    watcher = threading.Thread(target=watch_files, daemon=True)
    watcher.start()

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"Serving at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
