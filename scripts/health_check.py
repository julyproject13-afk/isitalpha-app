#!/usr/bin/env python3
"""АПТАЙМ / ЗДОРОВЬЕ isitalpha — жив ли сайт и отвечают ли ключевые эндпоинты.

Проверяет набор URL на 200 (или ожидаемый код) и печатает сводку.
Ничего не меняет и не шлёт — только читает. Cron-совместимо (exit-код 0=всё ок, 1=есть падения).

Проверяем:
  GET  /              — лендинг жив (200)
  GET  /validate      — страница проверки жива (200)
  GET  /api/plans     — API отвечает JSON (200)
  GET  /api/badge.svg?verdict=REAL — публичный бейдж рендерит SVG (200)
  POST /api/validate  — движок отвечает вердиктом (200, verdict в JSON)

Запуск:
  python3 scripts/health_check.py                         # база https://isitalpha.com
  BASE_URL=http://127.0.0.1:8423 python3 scripts/health_check.py
  python3 scripts/health_check.py --json
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("BASE_URL", os.environ.get("SITE_URL", "https://isitalpha.com")).rstrip("/")
TIMEOUT = float(os.environ.get("HEALTH_TIMEOUT", "12"))

# (метод, путь, ожид.код, тело-для-POST, ключ-который-должен-быть-в-JSON-ответе)
CHECKS = [
    ("GET", "/", 200, None, None),
    ("GET", "/validate", 200, None, None),
    ("GET", "/api/plans", 200, None, "plans"),
    ("GET", "/api/badge.svg?verdict=REAL&pct=88&n=5763", 200, None, None),
    ("POST", "/api/validate", 200,
     {"returns": ",".join(["0.004", "-0.002", "0.006"] * 15), "n_trials": 1},
     "verdict"),
]


def _probe(method, path, expect, body, need_key):
    """Возвращает dict со статусом одной проверки."""
    url = BASE + path
    t0 = time.time()
    try:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"User-Agent": "isitalpha-healthcheck/1.0"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            code = r.getcode()
            raw = r.read()
        ms = int((time.time() - t0) * 1000)
        ok = (code == expect)
        detail = ""
        if ok and need_key:
            try:
                if need_key not in json.loads(raw):
                    ok, detail = False, f"нет ключа '{need_key}' в ответе"
            except Exception:
                ok, detail = False, "ответ не JSON"
        return {"method": method, "path": path, "code": code, "expect": expect,
                "ms": ms, "ok": ok, "detail": detail}
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t0) * 1000)
        return {"method": method, "path": path, "code": e.code, "expect": expect,
                "ms": ms, "ok": False, "detail": f"HTTP {e.code}"}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"method": method, "path": path, "code": 0, "expect": expect,
                "ms": ms, "ok": False, "detail": str(e)[:80]}


def run_checks():
    return [_probe(*c) for c in CHECKS]


def summarize(results: list) -> tuple:
    """Возвращает (all_ok, текст-сводка)."""
    all_ok = all(r["ok"] for r in results)
    lines = [f"АПТАЙМ isitalpha — {BASE}", "-" * 46]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        extra = f"  ({r['detail']})" if r["detail"] else ""
        lines.append(f"  {mark} {r['method']:<4} {r['path']:<38} "
                     f"{r['code']}/{r['expect']}  {r['ms']}ms{extra}")
    lines.append("-" * 46)
    lines.append("ИТОГ: " + ("всё живо ✅" if all_ok else "ЕСТЬ ПАДЕНИЯ ❌ — проверь сервер"))
    return all_ok, "\n".join(lines)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    results = run_checks()
    if "--json" in argv:
        print(json.dumps({"base": BASE, "all_ok": all(r["ok"] for r in results),
                          "checks": results}, ensure_ascii=False, indent=2))
    else:
        all_ok, txt = summarize(results)
        print(txt)
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
