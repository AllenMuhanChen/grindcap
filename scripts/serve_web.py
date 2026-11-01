"""Serve the repo on http://localhost:8765 for the browser test (web/). Localhost only.

Plain `python -m http.server` can send .js files as text/plain on Windows (the registry decides),
and browsers refuse to run modules served that way, so the types are set here.
"""
import functools
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
         ".html": "text/html", ".png": "image/png", ".wasm": "application/wasm", ".gz": "application/gzip"}


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")   # always the files git pull brought
        super().end_headers()


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(Handler, directory=str(ROOT)))
    print("Serving http://localhost:8765/web/  (Ctrl+C or close this window to stop)")
    server.serve_forever()
