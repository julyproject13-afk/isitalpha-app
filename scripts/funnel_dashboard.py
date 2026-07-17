#!/usr/bin/env python3
"""Генератор мини-дашборда воронки isitalpha.

Читает funnel.json и metrics.json, пишет web/funnel_dashboard.html.
Статический HTML — без секретов, можно открывать локально или раздать через nginx.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNNEL_FILE = os.environ.get("FUNNEL", ROOT / "funnel.json")
METRICS_FILE = ROOT / "metrics.json"
OUT_FILE = ROOT / "web" / "funnel_dashboard.html"

STEPS = ("land", "example_click", "validate_click", "validate_run", "verdict_shown",
         "paywall_view", "pay_click", "paid")
LABEL = {
    "land": "Зашли на /validate",
    "example_click": "Нажали «попробовать пример»",
    "validate_click": "Нажали «получить вердикт»",
    "validate_run": "Запустили валидацию",
    "verdict_shown": "Увидели вердикт",
    "paywall_view": "Упёрлись в пейволл",
    "pay_click": "Нажали «оплатить»",
    "paid": "Оплатили",
}


def load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _pct(a, b):
    if not b:
        return None
    return round(a / b * 100, 2)


def build_html(funnel: dict, metrics: dict) -> str:
    totals = funnel.get("totals", {})
    land = totals.get("land", 1) or 1

    rows = []
    for step in STEPS:
        val = totals.get(step, 0) or 0
        pct_land = _pct(val, land)
        rows.append((LABEL[step], val, pct_land))

    conv_rows = []
    for i in range(1, len(STEPS)):
        pstep, cstep = STEPS[i - 1], STEPS[i]
        pv = totals.get(pstep, 0) or 0
        cv = totals.get(cstep, 0) or 0
        pct = _pct(cv, pv)
        drop = _pct(pv - cv, pv)
        conv_rows.append((LABEL[pstep], LABEL[cstep], pv, cv, pct, drop))

    src_rows = []
    for name, c in (funnel.get("sources") or {}).items():
        ld = c.get("land", 0) or 0
        run = c.get("validate_run", 0) or 0
        pw = c.get("paywall_view", 0) or 0
        paid = c.get("paid", 0) or 0
        src_rows.append((
            name,
            ld,
            _pct(run, ld),
            _pct(pw, ld),
            _pct(paid, ld),
        ))
    src_rows.sort(key=lambda x: x[1], reverse=True)

    attempts = metrics.get("attempts", 0)
    sales = metrics.get("sales", 0)
    revenue = metrics.get("revenue", 0)
    cr_overall = _pct(sales, attempts)

    rows_html = "\n".join(
        f"<tr><td>{name}</td><td>{n}</td><td>{pct if pct is not None else '—'}%</td></tr>"
        for name, n, pct in rows
    )
    conv_html = "\n".join(
        f"<tr><td>{a}</td><td>{b}</td><td>{pv}</td><td>{cv}</td><td>{pct if pct is not None else '—'}%</td><td>{drop if drop is not None else '—'}%</td></tr>"
        for a, b, pv, cv, pct, drop in conv_rows
    )
    src_html = "\n".join(
        f"<tr><td>{n}</td><td>{ld}</td><td>{r if r is not None else '—'}%</td><td>{p if p is not None else '—'}%</td><td>{paid if paid is not None else '—'}%</td></tr>"
        for n, ld, r, p, paid in src_rows
    )

    warning = ""
    if land <= 2:
        warning = "<p class='warn'>⚠️ Данных почти нет — это dev/тестовый набор. Живые цифры нужно брать с сервера (/opt/isitalpha/funnel.json).</p>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>isitalpha — воронка</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; background: #0f1115; color: #e8e8e8; }}
  h1, h2 {{ color: #fff; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 900px; margin: 1rem 0; }}
  th, td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a2d35; text-align: left; }}
  th {{ color: #9aa0a6; font-weight: 600; }}
  tr:hover {{ background: #1a1d24; }}
  .warn {{ color: #f9ab00; background: #2a2208; padding: 0.75rem; border-radius: 6px; max-width: 900px; }}
  .metric {{ display: inline-block; margin-right: 2rem; }}
  .metric b {{ font-size: 1.4rem; color: #fff; }}
</style>
</head>
<body>
  <h1>isitalpha — воронка (funnel.json)</h1>
  {warning}
  <div>
    <span class="metric"><b>{attempts}</b><br>попыток</span>
    <span class="metric"><b>{sales}</b><br>продаж</span>
    <span class="metric"><b>${revenue}</b><br>выручка</span>
    <span class="metric"><b>{cr_overall if cr_overall is not None else '—'}%</b><br>CR попытка→продажа</span>
  </div>

  <h2>Сколько дошло до каждого шага</h2>
  <table>
    <tr><th>Шаг</th><th>Кол-во</th><th>% от land</th></tr>
    {rows_html}
  </table>

  <h2>Конверсия шаг → шаг (где утекают)</h2>
  <table>
    <tr><th>Из</th><th>В</th><th>Было</th><th>Стало</th><th>Конверсия</th><th>Отвал</th></tr>
    {conv_html}
  </table>

  <h2>По каналам (utm_source)</h2>
  <table>
    <tr><th>Канал</th><th>land</th><th>→ run</th><th>→ paywall</th><th>→ paid</th></tr>
    {src_html}
  </table>

  <p><small>Обновляется: python3 scripts/funnel_dashboard.py</small></p>
</body>
</html>"""


def main() -> int:
    funnel = load_json(FUNNEL_FILE)
    metrics = load_json(METRICS_FILE)
    html = build_html(funnel, metrics)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Дашборд записан: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
