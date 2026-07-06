#!/usr/bin/env python3
"""ЕЖЕДНЕВНЫЙ МОНИТОР isitalpha — одна сводка для владельца (cron-совместимо).

Собирает в один текст:
  • клики/воронку (где рвётся) — из funnel.json;
  • продажи/выручку — из metrics.json;
  • точки утечки — крупнейший обрыв воронки;
  • аптайм/здоровье сайта — health_check.

ГОТОВИТ текст в формате для Telegram (HTML). НЕ ШЛЁТ САМ — это рука владельца
(или существующий мост Pulse). По умолчанию печатает в stdout. С --tg печатает
чистый HTML-блок, готовый скормить в sendMessage. Ничего необратимого не делает.

Запуск (cron, раз в сутки):
  0 8 * * * cd ~/honest-validator && /usr/bin/python3 scripts/daily_monitor.py --tg \
      >> /tmp/isitalpha_daily.log 2>&1
  # затем мост Pulse читает свежий блок и шлёт владельцу — см. QUEUE_FOR_OWNER.md

Флаги:
  --tg      вывести компактный HTML-блок для Telegram (иначе — читаемый текст)
  --no-net  не дёргать сайт (только локальные файлы), для оффлайн-прогона/тестов
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import funnel_report as FR                                      # noqa: E402

METRICS_FILE = os.path.join(ROOT, "metrics.json")


def _metrics() -> dict:
    try:
        return json.load(open(METRICS_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _health():
    """Прогон health_check. Возвращает (all_ok, короткая_строка) или (None, причина)."""
    try:
        import health_check as HC
        results = HC.run_checks()
        all_ok = all(r["ok"] for r in results)
        down = [r["path"] for r in results if not r["ok"]]
        if all_ok:
            return True, "сайт и API живы ✅"
        return False, "ПАДЕНИЯ ❌: " + ", ".join(down)
    except Exception as e:
        return None, f"health-check не выполнен ({str(e)[:60]})"


def build(no_net: bool = False) -> dict:
    """Собирает единую структуру сводки (для текста и для Telegram-HTML)."""
    f = FR.load()
    totals = f.get("totals", {}) or {}
    m = _metrics()
    sales = m.get("sales", 0)
    revenue = m.get("revenue", 0)
    attempts = m.get("attempts", 0)

    leak = FR.biggest_leak(totals)
    land = totals.get("land", 0)
    per100 = {}
    if land:
        for s in FR.STEPS:
            per100[s] = round(totals.get(s, 0) / land * 100)

    if no_net:
        health_ok, health_txt = None, "пропущено (--no-net)"
    else:
        health_ok, health_txt = _health()

    return {
        "totals": totals, "per100": per100, "land": land,
        "leak": leak, "sales": sales, "revenue": revenue, "attempts": attempts,
        "health_ok": health_ok, "health_txt": health_txt,
        "date": time.strftime("%d.%m.%Y", time.gmtime()),
    }


def as_text(d: dict) -> str:
    lines = [f"СВОДКА isitalpha — {d['date']} (UTC)", "=" * 46]
    if d["land"]:
        lines.append(f"Заходов на /validate: {d['land']}")
        p = d["per100"]
        lines.append(f"Из 100 зашедших: {p.get('validate_run',0)} запустили, "
                     f"{p.get('paywall_view',0)} до пейволла, "
                     f"{p.get('pay_click',0)} жали «оплатить», {p.get('paid',0)} оплатили.")
    else:
        lines.append("Заходов пока нет (нет данных воронки — жду трафик после деплоя).")
    if d["leak"]:
        a, b, dropped, pct = d["leak"]
        kept = f"{pct:.0f}%" if pct is not None else "—"
        lines.append(f"🔴 Рвётся: {FR.LABEL[a]} → {FR.LABEL[b]} (−{dropped}, дошло {kept})")
    lines.append(f"💰 Продаж: {d['sales']} · выручка ${d['revenue']} · попыток {d['attempts']}")
    lines.append(f"🩺 Здоровье: {d['health_txt']}")
    return "\n".join(lines)


def as_telegram_html(d: dict) -> str:
    """Компактный HTML-блок под Telegram sendMessage(parse_mode=HTML)."""
    p = d["per100"]
    leak_line = ""
    if d["leak"]:
        a, b, dropped, pct = d["leak"]
        kept = f"{pct:.0f}%" if pct is not None else "—"
        leak_line = f"\n🔴 <b>Рвётся:</b> {FR.LABEL[a]} → {FR.LABEL[b]} (−{dropped}, дошло {kept})"
    if d["land"]:
        funnel = (f"👀 Заходов: <b>{d['land']}</b>\n"
                  f"Из 100: {p.get('validate_run',0)} запуск → "
                  f"{p.get('paywall_view',0)} пейволл → "
                  f"{p.get('pay_click',0)} «оплатить» → <b>{p.get('paid',0)} оплатили</b>")
    else:
        funnel = "👀 Заходов пока нет (жду трафик после деплоя)"
    health = ("✅ сайт/API живы" if d["health_ok"] is True
              else ("❌ " + d["health_txt"] if d["health_ok"] is False else d["health_txt"]))
    return (f"📊 <b>isitalpha — дневная сводка</b> ({d['date']})\n\n"
            f"{funnel}{leak_line}\n\n"
            f"💰 Продаж: <b>{d['sales']}</b> · выручка <b>${d['revenue']}</b>\n"
            f"🩺 {health}")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    d = build(no_net="--no-net" in argv)
    print(as_telegram_html(d) if "--tg" in argv else as_text(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
