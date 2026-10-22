"""
serve_dashboard.py — live test dashboard for run_tests.ps1 (same idea as
billing's serve_dashboard.py, without billing's sync-queue / table panels).

Serves test_dashboard.html and /api/results (= test_results.json, written by
backend/tests/conftest.py as tests finish). Picks the first free port from
8090 (billing's starts at 8080, so both can run), writes the URL to
dashboard_url.txt for run_tests.ps1, and opens the browser.
"""
import json
import os
import socket
import sys
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8090
EMPTY = {"summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "duration": 0,
                     "status": "running"}, "tests": []}


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, format, *args):
        pass  # keep the test terminal clean

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/test_dashboard.html")
                self.end_headers()
            elif self.path == "/api/results":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps(_read_results()).encode("utf-8"))
            elif self.path == "/test_dashboard.html":
                super().do_GET()
            else:
                self.send_error(404)  # serve the dashboard only, not the repo
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass


def _read_results():
    path = os.path.join(ROOT, "test_results.json")
    for _ in range(3):  # conftest replaces the file atomically; retry covers Windows locks
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return EMPTY
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return EMPTY


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def main():
    port = PORT
    while _port_in_use(port):
        port += 1
    server = HTTPServer(("localhost", port), DashboardHandler)
    url = f"http://localhost:{port}/test_dashboard.html"
    try:
        with open(os.path.join(ROOT, "dashboard_url.txt"), "w", encoding="utf-8") as f:
            f.write(url)
    except OSError:
        pass
    print(f"\n\033[92m=== BIZASSIST TASK TEST REPORT ===\033[0m\n\033[94mURL: {url}\033[0m\n")
    if os.getenv("NO_BROWSER") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
