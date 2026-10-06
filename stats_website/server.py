#!/usr/bin/env python3
"""
Lightweight HTTP Server for IRC / Discord Statistics Website
Serves the web dashboard, API endpoints, and handles on-the-fly log refreshes.
Zero external dependencies (uses standard library http.server).
"""

import sys
import os
import json
import socket
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Ensure stats_engine can be imported
STATS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STATS_DIR))
import stats_engine

WEB_DIR = STATS_DIR / "web"


class StatsHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parts = self.path.split("?", 1)
        parsed_path = parts[0].rstrip("/")
        query_string = parts[1] if len(parts) > 1 else ""

        if parsed_path == "/api/stats":
            self.handle_api_stats()
            return
        elif parsed_path == "/api/refresh":
            self.handle_api_refresh()
            return
        elif parsed_path in ("", "/index.html"):
            self.handle_index_html(query_string)
            return

        # Default static file handler
        return super().do_GET()

    def handle_index_html(self, query_string=""):
        """Serves the pre-rendered index.html with optional server-side theme selection."""
        index_path = WEB_DIR / "index.html"
        if not index_path.exists():
            stats_engine.generate_and_save_data()

        try:
            html_text = index_path.read_text(encoding="utf-8")
            if "theme=retro" in query_string:
                html_text = (
                    html_text.replace('class="theme-modern"', 'class="theme-retro"')
                    .replace('href="?theme=retro"', 'href="?theme=modern"')
                    .replace('Retro IRC Theme', 'Modern Theme')
                )
            elif "theme=modern" in query_string:
                html_text = (
                    html_text.replace('class="theme-retro"', 'class="theme-modern"')
                    .replace('href="?theme=modern"', 'href="?theme=retro"')
                    .replace('Modern Theme', 'Retro IRC Theme')
                )

            encoded = html_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(encoded)
        except Exception as e:
            self.send_error(500, f"Error rendering index.html: {e}")

    def do_POST(self):
        parsed_path = self.path.split("?")[0].rstrip("/")
        if parsed_path == "/api/refresh":
            self.handle_api_refresh()
            return
        self.send_error(404, "Endpoint not found")

    def handle_api_stats(self):
        """Returns the precomputed statistics JSON."""
        data_path = WEB_DIR / "data.json"
        if not data_path.exists():
            stats_engine.generate_and_save_data()

        try:
            with open(data_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading stats: {e}")

    def handle_api_refresh(self):
        """Re-scans chat logs and updates data.json dynamically."""
        try:
            print("[Server] Triggering statistics re-scan from log files...")
            fresh_data = stats_engine.generate_and_save_data()
            payload = json.dumps({"status": "success", "message": "Statistics refreshed", "data": fresh_data}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            err_msg = json.dumps({"status": "error", "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_msg)))
            self.end_headers()
            self.wfile.write(err_msg)

    def log_message(self, format, *args):
        # Print clean access logs
        sys.stderr.write(f"[{self.log_date_time_string()}] {args[0]} {args[1]} -> {args[2]}\n")


def is_port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def run_server(host="127.0.0.1", start_port=8080):
    port = start_port
    while is_port_in_use(port, host):
        print(f"Port {port} is currently in use. Trying {port + 1}...")
        port += 1

    # Ensure data.json exists before launching
    if not (WEB_DIR / "data.json").exists():
        print("Initial data.json not found. Generating now...")
        stats_engine.generate_and_save_data()

    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, StatsHTTPRequestHandler)
    print("\n" + "="*60)
    print(f"  IRC & Discord Stats Web Server")
    print(f"  URL: http://{host}:{port}/")
    print(f"  Serving files from: {WEB_DIR}")
    print("="*60 + "\n")
    sys.stdout.flush()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server gracefully...")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Host the Discord / IRC Stats Website")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()

    run_server(host=args.host, start_port=args.port)
