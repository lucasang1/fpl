import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from config import PORT, PUBLIC_DIR
from services.fpl import fetch_standings

CACHE_SECONDS = 30
_cache: dict | None = None
_cache_expires_at = 0.0
_cache_lock = Lock()


def get_standings(*, force: bool = False) -> dict:
    global _cache, _cache_expires_at

    with _cache_lock:
        if not force and _cache is not None and time.monotonic() < _cache_expires_at:
            return _cache

        _cache = fetch_standings()
        _cache_expires_at = time.monotonic() + CACHE_SECONDS
        return _cache


class AppHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        request = urlsplit(self.path)
        if request.path != "/api/standings":
            return super().do_GET()

        try:
            force = parse_qs(request.query).get("refresh") == ["1"]
            self._send_json(get_standings(force=force))
        except Exception as error:
            self._send_json({"error": str(error)}, status=502)

    def _send_json(self, data: dict, *, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    handler = partial(AppHandler, directory=PUBLIC_DIR)
    print(f"Serving http://localhost:{PORT}")
    ThreadingHTTPServer(("", PORT), handler).serve_forever()


if __name__ == "__main__":
    main()
