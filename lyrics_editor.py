#!/usr/bin/env python3
"""Savant local browser editor for LRC/TTML lyrics. Standard-library HTTP server."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "webui" / "index.html"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self.send_error(404, "Not found")
            return
        try:
            payload = HTML_PATH.read_bytes()
        except OSError as exc:
            self.send_error(500, f"Cannot read editor UI: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' blob: data:; media-src blob: data:; connect-src 'self'; img-src 'self' data: blob:")
        self.end_headers()
        self.wfile.write(payload)

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self.send_error(404, "Not found")
            return
        try:
            payload = HTML_PATH.read_bytes()
        except OSError as exc:
            self.send_error(500, f"Cannot read editor UI: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        # Keep local editor output readable; no request details contain user data.
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the local Savant editor in your browser.")
    parser.add_argument("--port", type=int, default=8765, help="Local port to use (default: 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser.")
    args = parser.parse_args()
    if not HTML_PATH.is_file():
        parser.error(f"Editor UI is missing: {HTML_PATH}")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        parser.error(f"Could not listen on 127.0.0.1:{args.port}: {exc}. Try --port 8766.")
    url = f"http://127.0.0.1:{args.port}/"
    print("Savant Editor")
    print(f"Open: {url}")
    print("Local-only: audio and lyric files stay in your browser. Use Ctrl+C to stop the editor.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nEditor stopped.")
    finally:
        server.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
