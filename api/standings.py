import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from run import get_standings


def _parse_event(query: dict[str, list[str]]) -> int | None:
    values = query.get("event")
    if not values:
        return None
    event = int(values[0])
    if event < 1:
        raise ValueError("Gameweek must be 1 or higher")
    return event


class handler(BaseHTTPRequestHandler):
    """Serve the live standings as a Vercel Python Function."""

    def do_GET(self):
        try:
            query = parse_qs(urlsplit(self.path).query)
            data = get_standings(
                force=query.get("refresh") == ["1"],
                gameweek_id=_parse_event(query),
            )
            self._send_json(data)
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
