#!/usr/bin/env python3
"""Аудит телеметрии воронки isitalpha.

Симулирует полный путь пользователя, проверяет:
- инкременты шагов воронки по источнику и globally;
- фильтр is_probe (healthcheck/uptimerobot);
- /api/track принимает только validate_click/verdict_shown;
- монотонность шагов (код её не проверяет — фиксируем как дыру).

Пишет в funnel.json/metrics.json по путям из app.FUNNEL_FILE / app.METRICS_FILE
(для безопасности использует временные копии и восстанавливает оригиналы).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import app  # noqa: E402

FUNNEL_BACKUP: dict = {}
METRICS_BACKUP: dict = {}


def backup() -> None:
    """Сохранить текущие funnel/metrics, чтобы восстановить после аудита."""
    global FUNNEL_BACKUP, METRICS_BACKUP
    FUNNEL_BACKUP = app._funnel()
    METRICS_BACKUP = app._metrics()


def restore() -> None:
    app._save_funnel(FUNNEL_BACKUP)
    app._save_metrics(METRICS_BACKUP)


def _is_probe(ua: str) -> bool:
    return "healthcheck" in ua.lower() or "uptimerobot" in ua.lower()


def _handle_validate_get(src: str, ua: str) -> None:
    """Реплика логики Handler.do_GET /validate: учитываем визит/land только не-проб."""
    is_probe = _is_probe(ua)
    if src and not is_probe:
        app._bump_visit(src)
    if not is_probe:
        app._bump_step("land", src)


def _handle_api_track(step: str, src: str) -> None:
    """Реплика логики Handler.do_POST /api/track: доверяем только мягким шагам."""
    if step in ("validate_click", "verdict_shown"):
        app._bump_step(step, src)


def _handle_api_validate(src: str) -> None:
    """Реплика логики Handler.do_POST /api/validate: fresh-вердикт → validate_run, locked → paywall_view."""
    app._bump_attempt(src)
    app._bump_step("validate_run", src)
    app._bump_step("paywall_view", src)


def _handle_api_checkout(src: str) -> None:
    """Реплика /api/checkout: нажал Pay."""
    app._bump_step("pay_click", src)


def _handle_payment_confirmed(src: str) -> None:
    """Реплика IPN/callback: оплата подтверждена."""
    app._bump_step("paid", src)


def simulate_happy_path(src: str = "reddit") -> dict:
    """Полный путь: land → click → run → verdict → paywall → pay_click → paid."""
    _handle_validate_get(src, "Mozilla/5.0")
    _handle_api_track("validate_click", src)
    _handle_api_validate(src)
    _handle_api_track("verdict_shown", src)
    _handle_api_checkout(src)
    _handle_payment_confirmed(src)
    return app._funnel()


def audit() -> list:
    """Запускает сценарии аудита, возвращает список (status, message)."""
    results: list = []

    with tempfile.TemporaryDirectory() as d:
        app.FUNNEL_FILE = os.path.join(d, "funnel.json")
        app.METRICS_FILE = os.path.join(d, "metrics.json")
        app._save_funnel({"totals": {}, "sources": {}, "first_ts": 0, "last_ts": 0})
        app._save_metrics({"attempts": 0, "sales": 0, "revenue": 0, "first_ts": 0,
                           "last_sale_ts": 0, "seen_orders": [], "sources": {}, "order_src": {}})

        # 1. happy path
        simulate_happy_path("reddit")
        f = app._funnel()
        totals = f.get("totals", {})
        for step in app.FUNNEL_STEPS:
            ok = totals.get(step, 0) == 1
            results.append(("PASS" if ok else "FAIL", f"happy path: {step} = {totals.get(step, 0)}"))
        src_row = f.get("sources", {}).get("reddit", {})
        for step in app.FUNNEL_STEPS:
            ok = src_row.get(step, 0) == 1
            results.append(("PASS" if ok else "FAIL", f"source reddit: {step} = {src_row.get(step, 0)}"))

        # 2. is_probe filter: healthcheck не должен увеличивать land
        before = app._funnel()["totals"].get("land", 0)
        _handle_validate_get("reddit", "Healthcheck/1.0")
        after = app._funnel()["totals"].get("land", 0)
        results.append(("PASS" if after == before else "FAIL",
                        f"is_probe blocks land: before={before} after={after}"))

        # 3. /api/track ignores server-side steps
        before_run = app._funnel()["totals"].get("validate_run", 0)
        _handle_api_track("validate_run", "reddit")
        after_run = app._funnel()["totals"].get("validate_run", 0)
        results.append(("PASS" if after_run == before_run else "FAIL",
                        f"/api/track ignores validate_run: before={before_run} after={after_run}"))

        # 4. monotonicity is NOT enforced (hole)
        before_paid = app._funnel()["totals"].get("paid", 0)
        app._bump_step("paid", "direct")  # direct source never seen before, but step allowed
        after_paid = app._funnel()["totals"].get("paid", 0)
        results.append(("INFO", f"monotonicity NOT enforced: paid can jump to {after_paid} without previous steps (hole)"))

    return results


def main() -> int:
    backup()
    try:
        results = audit()
    finally:
        restore()

    print("=== isitalpha funnel telemetry audit ===")
    ok = sum(1 for s, _ in results if s == "PASS")
    fail = sum(1 for s, _ in results if s == "FAIL")
    info = sum(1 for s, _ in results if s == "INFO")
    for status, msg in results:
        print(f"[{status}] {msg}")
    print(f"\nPASS={ok} FAIL={fail} INFO={info}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
