"""ПРОДУКТ 2 — Honest Validator: честный приговор торговой стратегии.

Загрузил ряд доходностей → честный гейт скажет: РЕАЛЬНЫЙ край / САМООБМАН / мёртв — с КОНКРЕТНОЙ причиной.
Тот же движок, которым мы убили ~24 края (WTI-Brent, VRP, золото-серебро). Юр-риск НИЗШИЙ — это
информация/аналитика, не управление деньгами.

Гейт: издержки → purged/embargo CV → deflated-порог (multiple-testing) → хвост/CVaR/DD.
"""
from __future__ import annotations

import math
import statistics as st
from typing import Dict, List, Sequence

from .vendor.purged_cv import fold_sharpes

ANNUAL = 252


# ── малые помощники (как в edge_radar golden-mutation) ──
def _apply_costs(returns: Sequence[float], bps: float) -> List[float]:
    cost = 2.0 * bps / 10000.0
    return [r - cost for r in returns]


def _equity(returns: Sequence[float]) -> List[float]:
    eq, v = [], 1.0
    for r in returns:
        v *= (1.0 + r)
        eq.append(v)
    return eq


def _max_drawdown(eq: Sequence[float]) -> float:
    peak, mdd = eq[0] if eq else 1.0, 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return abs(mdd)


def _cvar(returns: Sequence[float], alpha: float = 0.05) -> float:
    if not returns:
        return 0.0
    s = sorted(returns)
    k = max(1, int(len(s) * alpha))
    return sum(s[:k]) / k


def _annual_sharpe(returns: Sequence[float]) -> float:
    if len(returns) < 2:
        return 0.0
    sd = st.pstdev(returns)
    return (st.mean(returns) / sd * math.sqrt(ANNUAL)) if sd > 1e-12 else 0.0


def _tail_adjusted_sharpe(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 4:
        return _annual_sharpe(returns)
    m = st.mean(returns)
    var = sum((r - m) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return 0.0
    sd = math.sqrt(var)
    skew = sum(((r - m) / sd) ** 3 for r in returns) / n
    kurt = sum(((r - m) / sd) ** 4 for r in returns) / n - 3.0
    sr = (m / sd) * math.sqrt(ANNUAL)
    penalty = max(0.0, -skew) * 0.1 + max(0.0, kurt) * 0.001
    return sr - abs(sr) * penalty


def _deflated_threshold(n_trials: int, alpha: float = 0.05) -> float:
    """Bonferroni-style порог: растёт с числом проверенных стратегий (multiple-testing)."""
    if n_trials <= 0:
        n_trials = 1
    try:
        return st.NormalDist().inv_cdf(1.0 - alpha / (2.0 * n_trials))
    except Exception:
        return 2.5 + 0.3 * math.log(max(1, n_trials))


def parse_returns_csv(text: str) -> List[float]:
    """Принять CSV/строки чисел → список доходностей (доля за период). Терпим к мусору."""
    out = []
    for tok in text.replace(",", "\n").replace(";", "\n").split():
        try:
            v = float(tok)
        except ValueError:
            continue
        if abs(v) > 2:                 # вероятно проценты (5 = 5%) → в долю
            v = v / 100.0
        out.append(v)
    return out


def validate(returns: Sequence[float], n_trials: int = 10, cost_bps: float = 5.0,
             k: int = 5, embargo: int = 3, max_dd: float = 0.20, max_cvar: float = 0.05) -> Dict:
    """ЧЕСТНЫЙ ПРИГОВОР стратегии. Возвращает вердикт + метрики + конкретные причины."""
    if len(returns) < 30:
        return {"verdict": "INSUFFICIENT", "reason": "мало данных (<30 точек) — честный CV невозможен",
                "n": len(returns)}

    net = _apply_costs(returns, cost_bps)
    fs = fold_sharpes(net, k, embargo)
    if not fs:
        return {"verdict": "INSUFFICIENT", "reason": "недостаточно фолдов для CV", "n": len(net)}

    median_sh = round(st.median(fs), 3)
    min_fold = round(min(fs), 3)
    threshold = round(_deflated_threshold(n_trials), 3)
    dd = round(_max_drawdown(_equity(net)), 4)
    cvar = round(_cvar(net), 4)
    adj = round(_tail_adjusted_sharpe(net), 3)
    gross = round(_annual_sharpe(returns), 3)
    net_sh = round(_annual_sharpe(net), 3)

    reasons: List[str] = []
    passed_cv = min_fold >= threshold
    passed_dd = dd <= max_dd
    passed_cvar = cvar >= -max_cvar
    if not passed_cv:
        reasons.append("худший CV-фолд %.2f < deflated-порога %.2f (не держится по всем периодам)" % (min_fold, threshold))
    if not passed_dd:
        reasons.append("просадка %.0f%% > %.0f%% (хвост несовместим с сохранностью)" % (dd * 100, max_dd * 100))
    if not passed_cvar:
        reasons.append("CVaR %.1f%% хуже −%.0f%% (тяжёлый левый хвост)" % (cvar * 100, max_cvar * 100))
    if gross - net_sh > 0.5:
        reasons.append("издержки съедают край (gross %.2f → net %.2f)" % (gross, net_sh))

    # вердикт
    if passed_cv and passed_dd and passed_cvar:
        verdict = "REAL"
        headline = "✅ Похоже на РЕАЛЬНЫЙ край — пережил честный гейт."
    elif net_sh <= 0:
        verdict = "DEAD"
        headline = "❌ Мёртв: нет края после издержек."
    elif median_sh > 0 and min_fold < 0:
        verdict = "SELF-DECEPTION"
        headline = "🔴 САМООБМАН: работает в одни периоды, теряет в другие (переподгон/режим-зависимость)."
    else:
        verdict = "BORDERLINE"
        headline = "🟡 BORDERLINE: слабо/неустойчиво — не полагаться без доп. данных."

    return {
        "verdict": verdict, "headline": headline, "reasons": reasons or ["прошёл все проверки"],
        "n": len(returns), "gross_sharpe": gross, "net_sharpe": net_sh,
        "cv_median_sharpe": median_sh, "cv_worst_fold": min_fold, "deflated_threshold": threshold,
        "max_drawdown": dd, "cvar": cvar, "tail_adj_sharpe": adj, "n_trials": n_trials,
        "note": "Survivorship: если ряд из выживших стратегий/инструментов — реальный край ещё хуже. "
                "Не инвестиционный совет.",
    }
