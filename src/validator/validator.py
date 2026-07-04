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
MIN_FOR_REAL = 60        # меньше — не сертифицируем как REAL (мало данных), максимум BORDERLINE
SHARPE_CAP = 8.0         # нетто-Sharpe выше — неправдоподобно для реальной торговли -> не REAL


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


def _annual_sharpe(returns: Sequence[float], ann: int = ANNUAL) -> float:
    if len(returns) < 2:
        return 0.0
    sd = st.pstdev(returns)
    return (st.mean(returns) / sd * math.sqrt(ann)) if sd > 1e-12 else 0.0


def _tail_adjusted_sharpe(returns: Sequence[float], ann: int = ANNUAL) -> float:
    n = len(returns)
    if n < 4:
        return _annual_sharpe(returns, ann)
    m = st.mean(returns)
    var = sum((r - m) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return 0.0
    sd = math.sqrt(var)
    skew = sum(((r - m) / sd) ** 3 for r in returns) / n
    kurt = sum(((r - m) / sd) ** 4 for r in returns) / n - 3.0
    sr = (m / sd) * math.sqrt(ann)
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


def _diffs(xs: Sequence[float]) -> List[float]:
    return [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]


def data_sanity(returns: Sequence[float], ann: int = ANNUAL):
    """Защита от «арбуза на томографе»: ловит явный мусор/фейк/цены ДО вердикта.
    Возвращает (hard, soft): hard = причины ОТКЛОНИТЬ (это не ряд доходностей);
    soft = мягкие предупреждения (подозрительно-идеально, считаем с оговоркой).
    Пороги консервативны — чтобы НЕ зарубить реальную хорошую стратегию."""
    n = len(returns)
    hard: List[str] = []
    soft: List[str] = []
    if n < 2:
        return hard, soft
    sd = st.pstdev(returns)
    distinct = {round(r, 10) for r in returns}
    # 1) нет разброса — константа
    if sd < 1e-9:
        hard.append("all values are identical — a return series must vary.")
        return hard, soft
    # 2) фактически бинарный ряд (≤2 уникальных значений)
    if len(distinct) <= 2:
        hard.append("only %d distinct values — this isn't a real return stream." % len(distinct))
    # 3) постоянный шаг = выдуманная арифметическая последовательность (1,2,3…/линейный рост)
    d = _diffs(returns)
    if len(d) >= 3 and st.pstdev(d) < 1e-9:
        hard.append("values change by a constant step — a generated sequence, not returns.")
    # 4) точная короткая периодичность = сгенерировано
    if n >= 12:
        for p in range(1, min(7, n // 3) + 1):
            if all(abs(returns[i] - returns[i - p]) < 1e-9 for i in range(p, n)):
                hard.append("the series repeats every %d points — looks generated." % p)
                break
    # 5) похоже на ЦЕНЫ/эквити-кривую, а не доходности за период (порог с запасом — не задеть реальные данные)
    med_abs = st.median([abs(r) for r in returns])
    if med_abs > 0.6:
        hard.append("typical value ≈%.2f is too large for per-period returns — did you paste prices or an equity curve?" % med_abs)
    elif len(d) >= 5:
        pos = sum(1 for x in d if x > 0) / len(d)
        if pos > 0.98 or pos < 0.02:
            hard.append("the series is almost perfectly monotonic — looks like an equity curve, not per-period returns.")
    # SOFT: подозрительно «чисто» (не невозможно, но проверь данные)
    neg_frac = sum(1 for r in returns if r < 0) / n
    if neg_frac < 0.02 and st.mean(returns) > 0:
        soft.append("almost no losing periods (%.0f%%) — unusually clean; confirm these are real per-period returns." % (neg_frac * 100))
    if abs(_annual_sharpe(returns, ann)) > 12:
        soft.append("annualized Sharpe ≈%.0f is beyond what real trading sustains — double-check the data." % abs(_annual_sharpe(returns, ann)))
    if len(distinct) / n < 0.15:
        soft.append("very few distinct values (%d) for %d points — looks rounded or synthetic." % (len(distinct), n))
    return hard, soft


def validate(returns: Sequence[float], n_trials: int = 10, cost_bps: float = 5.0,
             k: int = 5, embargo: int = 3, max_dd: float = 0.20, max_cvar: float = 0.05,
             periods_per_year: int = ANNUAL) -> Dict:
    """ЧЕСТНЫЙ ПРИГОВОР стратегии. Возвращает вердикт + метрики + конкретные причины.
    periods_per_year — как часто один период: день=252, неделя=52, месяц=12 (правильная аннуализация)."""
    ann = periods_per_year if periods_per_year and periods_per_year > 0 else ANNUAL
    if len(returns) < 30:
        return {"verdict": "INSUFFICIENT", "reason": "Not enough data (<30 points) — an honest CV isn't possible.",
                "n": len(returns)}

    # «Арбуз на томографе»: сначала — похоже ли это вообще на реальный ряд доходностей?
    hard, soft = data_sanity(returns, ann)
    if hard:
        return {"verdict": "UNCLEAR",
                "headline": "⚠️ This doesn't look like a real return series — we won't guess.",
                "reason": " ".join(hard), "reasons": hard, "n": len(returns),
                "note": "Paste per-period returns (e.g. 0.012, -0.004, 0.008 …) — not prices, an equity curve, "
                        "or placeholder numbers. Not investment advice."}

    net = _apply_costs(returns, cost_bps)
    fs = fold_sharpes(net, k, embargo, ann)
    if not fs:
        return {"verdict": "INSUFFICIENT", "reason": "Not enough folds for cross-validation.", "n": len(net)}

    median_sh = round(st.median(fs), 3)
    min_fold = round(min(fs), 3)
    threshold = round(_deflated_threshold(n_trials), 3)
    dd = round(_max_drawdown(_equity(net)), 4)
    cvar = round(_cvar(net), 4)
    adj = round(_tail_adjusted_sharpe(net, ann), 3)
    gross = round(_annual_sharpe(returns, ann), 3)
    net_sh = round(_annual_sharpe(net, ann), 3)

    reasons: List[str] = []
    passed_cv = min_fold >= threshold
    passed_dd = dd <= max_dd
    passed_cvar = cvar >= -max_cvar
    if not passed_cv:
        reasons.append("Worst CV fold %.2f < deflated bar %.2f — it doesn't hold across all periods." % (min_fold, threshold))
    if not passed_dd:
        reasons.append("Drawdown %.0f%% > %.0f%% — the tail is incompatible with capital preservation." % (dd * 100, max_dd * 100))
    if not passed_cvar:
        reasons.append("CVaR %.1f%% worse than −%.0f%% — heavy left tail." % (cvar * 100, max_cvar * 100))
    if gross - net_sh > 0.5:
        reasons.append("Costs eat the edge (gross %.2f → net %.2f)." % (gross, net_sh))

    # правдоподобие: невозможно высокий Sharpe / почти нет убытков = синтетика/фейк-гладкость, НЕ сертифицируем
    neg_frac = sum(1 for r in net if r < 0) / len(net) if net else 0.0
    implausible = net_sh > SHARPE_CAP or (neg_frac < 0.01 and net_sh > 4.0)

    # verdict
    if passed_cv and passed_dd and passed_cvar:
        if implausible:                # прошло гейт, но метрики неправдоподобно высоки → НЕ фейк, но и НЕ сертифицируем REAL
            verdict = "BORDERLINE"
            headline = ("🟡 Passed every check, but the performance is unusually high (annualized Sharpe %.0f). "
                        "We can't certify it as a REAL edge from this alone — please confirm these are genuine, "
                        "per-period, out-of-sample returns (not an equity curve or synthetic)." % net_sh)
            reasons = ["Unusually high performance (Sharpe %.1f) — double-check the data is real, per-period and out-of-sample." % net_sh]
        elif len(returns) < MIN_FOR_REAL:   # прошло, но мало данных для сертификации
            verdict = "BORDERLINE"
            headline = ("🟡 Passed the checks, but too little data to certify — need at least %d points for a REAL verdict "
                        "(you have %d)." % (MIN_FOR_REAL, len(returns)))
        elif soft:                     # прошло, но данные подозрительно «чистые» → не сертифицируем как REAL
            verdict = "BORDERLINE"
            headline = ("🟡 Passed the gauntlet, but the data looks unusually clean — confirm these are real per-period "
                        "returns (not an equity curve or synthetic). Not certified as REAL.")
        else:
            verdict = "REAL"
            headline = ("✅ Looks like a REAL edge — it survived the honest gauntlet. "
                        "This checks historical robustness only — not hidden market-beta, capacity, or crisis coverage.")
    elif net_sh <= 0:
        verdict = "DEAD"
        headline = "❌ Dead: no edge left after costs."
    elif median_sh > 0 and min_fold < 0:
        verdict = "SELF-DECEPTION"
        headline = "🔴 SELF-DECEPTION: works in some periods, loses in others (overfit / regime-dependent)."
    else:
        verdict = "BORDERLINE"
        headline = "🟡 BORDERLINE: weak / unstable — don't rely on it without more data."

    out = {
        "verdict": verdict, "headline": headline, "reasons": reasons or ["Passed every check."],
        "n": len(returns), "gross_sharpe": gross, "net_sharpe": net_sh,
        "cv_median_sharpe": median_sh, "cv_worst_fold": min_fold, "deflated_threshold": threshold,
        "max_drawdown": dd, "cvar": cvar, "tail_adj_sharpe": adj, "n_trials": n_trials,
        "note": "Survivorship: if this series comes from surviving strategies/instruments, the real edge is even worse. "
                "Not investment advice.",
        "limits": "Return-only analysis: cannot see hidden market-beta (disguised long), unrealized tail risk, "
                  "capacity, or whether a real crisis was in the sample. Robustness ≠ safety.",
    }
    if soft:
        out["data_warning"] = soft      # передаём предупреждения о качестве данных в отчёт
    return out
