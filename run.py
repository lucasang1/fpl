import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from config import PORT, PUBLIC_DIR
from services.fpl import fetch_standings

DEFAULT_CACHE_SECONDS = 30
FROZEN_CACHE_SECONDS = 60 * 60
_cache: dict[int | None, tuple[dict, float]] = {}
_cache_lock = Lock()


def _cache_seconds(data: dict) -> int:
    policy = data.get("refreshPolicy")
    if not isinstance(policy, dict):
        return DEFAULT_CACHE_SECONDS

    poll_ms = policy.get("pollMs")
    if isinstance(poll_ms, int) and poll_ms > 0:
        return max(1, poll_ms // 1000)
    return FROZEN_CACHE_SECONDS


def _parse_event(query: dict[str, list[str]]) -> int | None:
    values = query.get("event")
    if not values:
        return None
    event = int(values[0])
    if event < 1:
        raise ValueError("Gameweek must be 1 or higher")
    return event


def get_standings(*, force: bool = False, gameweek_id: int | None = None) -> dict:
    with _cache_lock:
        cached = _cache.get(gameweek_id)
        if cached and not force:
            data, expires_at = cached
            if time.monotonic() < expires_at:
                return data

        data = fetch_standings(gameweek_id=gameweek_id, read_snapshot=not force)
        _cache[gameweek_id] = (data, time.monotonic() + _cache_seconds(data))
        return data


class AppHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        request = urlsplit(self.path)
        if request.path != "/api/standings":
            return super().do_GET()

        try:
            query = parse_qs(request.query)
            force = query.get("refresh") == ["1"]
            self._send_json(
                get_standings(force=force, gameweek_id=_parse_event(query))
            )
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
