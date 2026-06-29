"""Honest Validator (Продукт 2) web-приложение. Самодостаточно, чистый stdlib.
Маршруты: /validate (форма) /report (отчёт) /api/validate (вердикт). Не касается денег — только анализ.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
WEB = os.path.join(ROOT, "web")

from validator.validator import validate, parse_returns_csv      # noqa: E402

_CT = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, name):
        path = os.path.join(WEB, name)
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as f:
            self._send(200, f.read(), _CT.get(os.path.splitext(name)[1], "application/octet-stream"))

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._file("landing.html")
        if p == "/validate":
            return self._file("validate.html")
        if p == "/report":
            return self._file("report.html")
        safe = os.path.normpath(p).lstrip("/")
        if safe and os.path.isfile(os.path.join(WEB, safe)):
            return self._file(safe)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/validate":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad request"})
        rets = parse_returns_csv(body.get("returns", ""))
        n_trials = int(body.get("n_trials", 10) or 10)
        return self._send(200, validate(rets, n_trials=n_trials))

    def log_message(self, *a):
        pass


def main(port=8423):
    print("Honest Validator app: http://127.0.0.1:%d  (/validate, /report)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8423)
