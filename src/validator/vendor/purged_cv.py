"""Purged K-Fold кросс-валидация с эмбарго (Лопез де Прадо) — наш stdlib.

Зачем: один OOS-сплит может пройти ВЕЗЕНИЕМ. Настоящая проверка — держится ли край по
ВСЕМ временным фолдам. Эмбарго отрезает первые точки фолда, чтобы серийная корреляция
с предыдущим участком не «протекла» в оценку (классическая ошибка бэктеста).

Идея перенесена из техники mlfinlab; код полностью свой, без зависимостей.
"""
from __future__ import annotations

import math
import statistics as st
from typing import Dict, List

ANNUAL = 252


def fold_sharpes(returns: List[float], k: int = 5, embargo: int = 3, ann: int = ANNUAL) -> List[float]:
    """Sharpe по каждому из k временных фолдов (с эмбарго в начале фолда). ann = периодов в году (день=252/неделя=52/месяц=12)."""
    n = len(returns)
    if n < k * (embargo + 5):
        k = max(2, n // (embargo + 5))           # мало данных — меньше фолдов
    fold = n // k if k else n
    out: List[float] = []
    for i in range(k):
        a = i * fold
        b = n if i == k - 1 else (i + 1) * fold
        seg = returns[a + embargo:b]             # эмбарго: пропускаем начало фолда
        if len(seg) < 5:
            continue
        m = st.mean(seg)
        sd = st.pstdev(seg)
        out.append(m / sd * math.sqrt(ann) if sd > 1e-12 else 0.0)
    return out


def robustness(returns: List[float], k: int = 5, embargo: int = 3,
               min_sharpe: float = 0.0) -> Dict:
    """Робастность края по фолдам: держится ли ВЕЗДЕ. passed = все фолды > порога."""
    sh = fold_sharpes(returns, k, embargo)
    if not sh:
        return {"folds": 0, "min": 0.0, "median": 0.0, "positive_frac": 0.0, "passed": False}
    pos = sum(1 for s in sh if s > min_sharpe) / len(sh)
    return {"folds": len(sh), "min": round(min(sh), 2), "median": round(st.median(sh), 2),
            "positive_frac": round(pos, 2), "passed": all(s > min_sharpe for s in sh)}
