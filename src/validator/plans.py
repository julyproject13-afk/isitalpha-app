"""Лестница подписки isitalpha (СТРУКТУРА, не платёжка) — фишка №1+№2 стратегии.

free → $15 разовый разбор → $9/мес мониторинг (recurring). Плюс платный research-тир
«approved with caveats» (regime-conditional). Здесь ТОЛЬКО определения тиров и какие поля
доступны на каждом — платёжные ключи/провайдер НЕ трогаем (рука владельца, отдельно).

Зачем: конкуренты все на recurring $16-80/мес (TradeZella/Edgewonk/…), наш разовый $15 не
масштабируется (LTV=$15). Мониторинг = путь к надёжной recurring-выручке.
"""
from __future__ import annotations

from typing import Dict, List

# ── тиры (id → человекочит. описание). Цены — гипотеза, тестировать (см. PMF-док). ──
PLANS: Dict[str, dict] = {
    "free": {
        "id": "free", "price_usd": 0, "recurring": None,
        "name": "Free verdict",
        "blurb": "Blunt one-word verdict + percentile. No card, no signup.",
        "fields": ["verdict", "headline", "n", "reason", "percentile", "graveyard_n"],
        "features": ["Verdict word (REAL / SELF-DECEPTION / DEAD / …)",
                     "Percentile vs the strategy graveyard",
                     "Shareable badge"],
    },
    "report": {
        "id": "report", "price_usd": 15, "recurring": None,
        "name": "Full report",
        "blurb": "One-time. Every reason + all metrics + certified downloadable report.",
        "fields": "ALL",
        "features": ["Every reason behind the verdict",
                     "Net Sharpe, worst CV fold, deflated bar, DD, CVaR, tail-adj Sharpe",
                     "Downloadable certified report with seal"],
    },
    "regime": {
        "id": "regime", "price_usd": 19, "recurring": None,
        "name": "Regime report (approved-with-caveats)",
        "blurb": "Research-tier verdict: median-fold gate + regime split. Tells you WHEN the "
                 "edge works and gives concrete stop-signals when to cut it.",
        "fields": "ALL",
        "features": ["Regime-conditional verdict (calm vs stress Sharpe)",
                     "Concrete stop-signals — when to halt / hedge the strategy",
                     "Median-fold gate (less punishing than the strict free verdict)",
                     "Everything in Full report"],
    },
    "monitor": {
        "id": "monitor", "price_usd": 9, "recurring": "monthly",
        "name": "Monitoring",
        "blurb": "$9/mo. We re-run your strategy on fresh data every month and alert you the "
                 "moment the edge starts to decay. Keeps a history of quality over time.",
        "fields": "ALL",
        "features": ["Monthly re-validation on fresh returns you add",
                     "Alert when the edge decays ('your edge is going stale')",
                     "Quality-over-time journal (trend of your Sharpe / verdict)",
                     "All report tiers included"],
    },
}

# порядок показа в UI (воронка снизу вверх по цене/ценности)
LADDER: List[str] = ["free", "report", "regime", "monitor"]


def plan(plan_id: str) -> dict:
    """Вернуть определение тира по id (или free по умолчанию)."""
    return PLANS.get(plan_id, PLANS["free"])


def is_unlocked(plan_id: str, field: str) -> bool:
    """Доступно ли поле результата на данном тире."""
    f = plan(plan_id).get("fields")
    return f == "ALL" or (isinstance(f, (list, tuple)) and field in f)


def gate_result(result: dict, plan_id: str) -> dict:
    """Отфильтровать результат под тир: free видит только free-поля + locked-флаг с апселлом.

    Платные тиры (report/regime/monitor) видят всё. INSUFFICIENT отдаём целиком (анализ не шёл).
    """
    if plan_id != "free" or result.get("verdict") == "INSUFFICIENT":
        return result
    free = plan("free")["fields"]
    g = {k: result[k] for k in free if k in result}
    g["locked"] = True
    g["upsell"] = [{"id": p, "price_usd": PLANS[p]["price_usd"], "recurring": PLANS[p]["recurring"],
                    "name": PLANS[p]["name"], "blurb": PLANS[p]["blurb"]}
                   for p in ("report", "regime", "monitor")]
    return g


def ladder_public() -> List[dict]:
    """Публичное описание лестницы для страницы цен (без внутренних полей)."""
    return [{"id": p, "price_usd": PLANS[p]["price_usd"], "recurring": PLANS[p]["recurring"],
             "name": PLANS[p]["name"], "blurb": PLANS[p]["blurb"], "features": PLANS[p]["features"]}
            for p in LADDER]
