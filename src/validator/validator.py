"""ПРОДУКТ 2 — Honest Validator: честный приговор торговой стратегии.

Загрузил ряд доходностей → честный гейт скажет: РЕАЛЬНЫЙ край / САМООБМАН / мёртв — с КОНКРЕТНОЙ причиной.
Тот же движок, которым мы убили ~24 края (WTI-Brent, VRP, золото-серебро). Юр-риск НИЗШИЙ — это
информация/аналитика, не управление деньгами.

Гейт: издержки → purged/embargo CV → deflated-порог (multiple-testing) → хвост/CVaR/DD.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import statistics as st
from typing import Dict, List, Sequence

from .vendor.purged_cv import fold_sharpes

ANNUAL = 252

# ── «Кладбище краёв»: распределение net-Sharpe 5763 реально протестированных стратегий (для перцентиля) ──
_GRAVE = None


def _grave_percentile(net_sharpe: float):
    """Процент кладбища, который бьёт стратегия с данным net-Sharpe. None — если данных нет."""
    global _GRAVE
    if _GRAVE is None:
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graveyard_dist.json")
            _GRAVE = sorted(json.load(open(p)).get("sharpes", []))
        except Exception:
            _GRAVE = []
    if not _GRAVE:
        return None, 0
    idx = bisect.bisect_left(_GRAVE, net_sharpe)
    return round(100.0 * idx / len(_GRAVE), 1), len(_GRAVE)
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


def parse_returns_csv(text) -> List[float]:
    """Принять CSV/строки чисел → список доходностей (доля за период). Терпим к мусору.

    Принимаем не только строку. Квант, дёргающий API из кода, естественно пришлёт
    JSON-массив: {"returns": [0.01, -0.005, ...]}. Раньше на этом падал .replace
    у списка — AttributeError, обработчик умирал, nginx отдавал 502. Снаружи это
    выглядит как «сайт не работает», причём именно у технической аудитории.
    """
    if isinstance(text, (list, tuple)):
        out = []
        for item in text:
            if isinstance(item, bool):        # True/False доходностью не считаем
                continue
            if isinstance(item, (int, float)):
                v = float(item)
            else:
                try:
                    v = float(str(item).strip())
                except (TypeError, ValueError):
                    continue
            if abs(v) > 2:                    # вероятно проценты (5 = 5%) → в долю
                v = v / 100.0
            out.append(v)
        return out
    if text is None:
        return []
    if not isinstance(text, str):
        text = str(text)

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
    pct, gn = _grave_percentile(net_sh)   # 🎣 фишка: перцентиль против 5763 убитых стратегий
    if pct is not None:
        out["percentile"] = pct
        out["graveyard_n"] = gn
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ПЛАТНЫЙ ТИР «одобрено с оговорками» — regime-conditional вердикт.
# Прокинут из research_judge (golden-mutation): гейт по МЕДИАНЕ фолдов (не min) +
# режим-гейт. В продукте у клиента НЕТ параллельного VIX, поэтому режим определяем
# честно ИЗ САМОГО РЯДА: периоды высокой собственной волатильности = «стресс».
# Это отдельный, БОЛЕЕ МЯГКИЙ судья: строгий validate() говорит REAL/SELF-DECEPTION
# для широкой публики (min-fold пугает намеренно); regime_judge даёт нюанс —
# «край реальный, но только в спокойном режиме + вот стоп-сигналы».
# ══════════════════════════════════════════════════════════════════════════════

def _regime_split_self(net: Sequence[float], window: int = 20, calm_q: float = 0.66):
    """Разбить ряд на СПОКОЙНЫЕ/СТРЕССОВЫЕ периоды по СОБСТВЕННОЙ скользящей волатильности.

    Без внешнего VIX: считаем rolling-std на трейлинг-окне (только прошлое, без look-ahead),
    порог = квантиль calm_q этих значений. Период 'стресс', если его трейлинг-vol в верхнем хвосте.
    Возвращает (calm, stress, threshold_used) или (None, None, None) если данных мало.
    """
    n = len(net)
    if n < window * 3:
        return None, None, None
    rolls: List[float] = []
    for i in range(n):
        a = max(0, i - window)
        seg = net[a:i]                       # только ПРОШЛОЕ до периода i
        rolls.append(st.pstdev(seg) if len(seg) >= 2 else 0.0)
    valid = sorted(r for r in rolls[window:] if r > 0)
    if len(valid) < 5:
        return None, None, None
    thr = valid[min(len(valid) - 1, int(len(valid) * calm_q))]
    calm, stress = [], []
    for i in range(window, n):
        (stress if rolls[i] > thr else calm).append(net[i])
    return calm, stress, round(thr, 6)


def regime_judge(returns: Sequence[float], vix: "Sequence[float] | None" = None,
                 n_trials: int = 10, cost_bps: float = 5.0, k: int = 5, embargo: int = 3,
                 max_dd: float = 0.20, max_cvar: float = 0.05,
                 vix_calm: float = 25.0, periods_per_year: int = ANNUAL) -> Dict:
    """RESEARCH-тир вердикта (платный «approved with caveats»).

    Отличия от строгого validate(): (1) главный CV-гейт = МЕДИАНА фолдов, не min;
    (2) режим-гейт — Sharpe отдельно в спокойном и стрессовом режиме. Если край держится
    в спокойном, но валится в стрессе → REGIME-CONDITIONAL (реальный, но не тейл-хедж) +
    конкретные СТОП-СИГНАЛЫ. Режим берём из внешнего vix, а без него — из собственной vol ряда.
    """
    ann = periods_per_year if periods_per_year and periods_per_year > 0 else ANNUAL
    if len(returns) < 30:
        return {"verdict": "INSUFFICIENT", "tier": "regime",
                "reason": "Not enough data (<30 points) — an honest CV isn't possible.", "n": len(returns)}

    hard, soft = data_sanity(returns, ann)
    if hard:
        return {"verdict": "UNCLEAR", "tier": "regime",
                "headline": "⚠️ This doesn't look like a real return series — we won't guess.",
                "reason": " ".join(hard), "reasons": hard, "n": len(returns),
                "note": "Paste per-period returns, not prices/equity/placeholders. Not investment advice."}

    net = _apply_costs(returns, cost_bps)
    fs = fold_sharpes(net, k, embargo, ann)
    if not fs:
        return {"verdict": "INSUFFICIENT", "tier": "regime",
                "reason": "Not enough folds for cross-validation.", "n": len(net)}

    median_fold = round(st.median(fs), 3)
    min_fold = round(min(fs), 3)
    threshold = round(_deflated_threshold(n_trials), 3)
    dd = round(_max_drawdown(_equity(net)), 4)
    cvar = round(_cvar(net), 4)
    net_sh = round(_annual_sharpe(net, ann), 3)
    gross = round(_annual_sharpe(returns, ann), 3)

    passed_cv = median_fold >= threshold        # ← МЕДИАНА (мягче min), правка research_judge
    passed_dd = dd <= max_dd
    passed_cvar = cvar >= -max_cvar
    worst_fold_warn = min_fold < 0

    # ── режим-гейт ──
    calm_sh = stress_sh = None
    regime = None
    regime_source = None
    if vix is not None:
        calm_r, stress_r = [], []
        for r, v in zip(net, vix):
            if v is None:
                continue
            (calm_r if v <= vix_calm else stress_r).append(r)
        regime_source = "external_vix"
    else:
        calm_r, stress_r, thr = _regime_split_self(net)
        if calm_r is not None:
            regime_source = "self_volatility"
    if calm_r is not None and stress_r is not None:
        calm_sh = round(_annual_sharpe(calm_r, ann), 3) if len(calm_r) >= 2 else None
        stress_sh = round(_annual_sharpe(stress_r, ann), 3) if len(stress_r) >= 2 else None
        regime = {"source": regime_source, "n_calm": len(calm_r), "n_stress": len(stress_r),
                  "calm_sharpe": calm_sh, "stress_sharpe": stress_sh}

    reasons: List[str] = []
    stop_signals: List[str] = []
    if not passed_cv:
        reasons.append("Median CV fold %.2f < deflated bar %.2f — the edge doesn't hold in a typical period."
                       % (median_fold, threshold))
    if not passed_dd:
        reasons.append("Drawdown %.0f%% > %.0f%% — tail incompatible with capital preservation." % (dd * 100, max_dd * 100))
    if not passed_cvar:
        reasons.append("CVaR %.1f%% worse than −%.0f%% — heavy left tail." % (cvar * 100, max_cvar * 100))
    if worst_fold_warn:
        reasons.append("Worst fold %.2f < 0 — at least one period where it fails (overfit/regime indicator; "
                       "documented, not the main gate)." % min_fold)

    stress_fail = (stress_sh is not None and stress_sh < 0)
    if passed_cv and passed_dd and passed_cvar:
        if stress_fail:
            verdict = "REGIME-CONDITIONAL"
            headline = ("🟠 Approved with caveats — REGIME-CONDITIONAL. The edge holds in the calm regime "
                        "(calm Sharpe %s) but breaks in stress (stress Sharpe %.2f). Real, but NOT a tail hedge — "
                        "you need external tail protection." % (calm_sh, stress_sh))
            stop_signals = [
                "Cut / halt the strategy when realized volatility spikes above your calm-regime band "
                "(the stress bucket is where it lost money in-sample).",
                "Pair it with an explicit tail hedge (long vol / OTM puts) — this edge does not survive stress alone.",
                "Re-check monthly: if the calm-vs-stress gap widens, the edge is decaying.",
            ]
        else:
            verdict = "REAL"
            headline = ("✅ REAL (research tier): median fold ≥ deflated bar, DD/CVaR in range"
                        + (", and it holds in stress too" if stress_sh is not None else "")
                        + ". Historical robustness only — not hidden beta/capacity.")
    elif net_sh <= 0:
        verdict = "DEAD"
        headline = "❌ Dead: no edge left after costs."
    elif median_fold > 0 and min_fold < 0:
        verdict = "SELF-DECEPTION"
        headline = "🔴 SELF-DECEPTION: positive median but losing folds (overfit / regime-dependent)."
    else:
        verdict = "BORDERLINE"
        headline = "🟡 BORDERLINE: weak / unstable — don't rely on it without more data."

    out = {
        "verdict": verdict, "tier": "regime", "headline": headline,
        "reasons": reasons or ["Passed every gate."],
        "stop_signals": stop_signals, "n": len(returns),
        "gross_sharpe": gross, "net_sharpe": net_sh,
        "cv_median_fold": median_fold, "cv_worst_fold": min_fold, "cv_all_folds": [round(f, 3) for f in fs],
        "deflated_threshold": threshold, "max_drawdown": dd, "cvar": cvar,
        "regime": regime, "n_trials": n_trials,
        "note": "Research tier: median-fold gate (not min) + regime gate. The strict free/standard verdict "
                "(min-fold) is harsher on purpose. Not investment advice.",
    }
    if soft:
        out["data_warning"] = soft
    pct, gn = _grave_percentile(net_sh)
    if pct is not None:
        out["percentile"] = pct
        out["graveyard_n"] = gn
    return out
