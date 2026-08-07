"""The dashboard.

http.server rather than a framework, because the whole tool has no runtime dependencies and a
read-only local dashboard does not justify breaking that. Two JSON endpoints and one static page.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .models import Flake
from .report import group, weekly_digest
from .store import Store

STATIC = Path(__file__).parent / "static"


def _flake_json(flake: Flake) -> dict:
    verdict = flake.verdict
    return {
        "job_id": flake.job_id,
        "job_name": flake.job_name,
        "dimensions": flake.dimensions,
        "detected_by": flake.detected_by,
        "failed_at": flake.failed_at,
        "html_url": flake.html_url,
        "sha": flake.head_sha[:8],
        "excerpt": flake.excerpt,
        "category": verdict.category.value if verdict else None,
        "confidence": verdict.confidence if verdict else None,
        "summary": verdict.summary if verdict else "",
        "suggestion": verdict.suggestion if verdict else "",
        "classifier": verdict.classifier if verdict else "",
        "evidence": verdict.evidence if verdict else [],
    }


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quieter than the default
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/flakes":
                flakes = store.all()
                payload = {
                    "flakes": [_flake_json(f) for f in flakes],
                    "counts": store.count_by_category(),
                    "groups": {sig: len(items) for sig, items in group(flakes).items()},
                }
                self._send(200, json.dumps(payload).encode(), "application/json")
            elif self.path == "/api/report":
                body = weekly_digest(store.all())
                self._send(200, body.encode(), "text/plain; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def serve(store: Store, port: int = 8000) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    print(f"dashboard on http://127.0.0.1:{port}  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
