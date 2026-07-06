#!/usr/bin/env python3
"""ОТЧЁТ ВОРОНКИ isitalpha — где именно рвётся путь клиента (land → … → paid).

Читает funnel.json (анонимные пофазные счётчики, БЕЗ PII) и печатает по-человечески:
  • сквозную воронку с конверсией шаг→шаг и главной точкой обрыва;
  • разбивку по utm_source (какой канал даёт клики, но не продажи);
  • spend-vs-conversion (если передать расходы каналов через --spend).

Ничего не пишет и не шлёт — только читает и печатает. Слепых цифр не рисуем:
если данных нет — так и говорим.

Запуск:
  python3 scripts/funnel_report.py
  FUNNEL=/path/to/funnel.json python3 scripts/funnel_report.py
  python3 scripts/funnel_report.py --spend reddit=42,twitter=10    # $ по каналам → CAC/утечка
  python3 scripts/funnel_report.py --json                          # машиночитаемо
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FUNNEL_FILE = os.environ.get("FUNNEL", os.path.join(ROOT, "funnel.json"))

# порядок шагов = путь клиента (должен совпадать с FUNNEL_STEPS в app.py)
STEPS = ("land", "validate_click", "validate_run", "verdict_shown",
         "paywall_view", "pay_click", "paid")
LABEL = {
    "land": "зашли на /validate",
    "validate_click": "нажали «получить вердикт»",
    "validate_run": "запустили валидацию",
    "verdict_shown": "увидели вердикт",
    "paywall_view": "упёрлись в пейволл",
    "pay_click": "нажали «оплатить»",
    "paid": "оплатили",
}


def load(path=FUNNEL_FILE) -> dict:
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def _steps_of(counts: dict) -> list:
    """Список (шаг, значение) в каноническом порядке; отсутствующие = 0."""
    return [(s, int(counts.get(s, 0) or 0)) for s in STEPS]


def conversions(counts: dict) -> list:
    """Конверсии шаг→шаг: [(from,to,prev,cur,pct_or_None)]. pct None если prev=0."""
    seq = _steps_of(counts)
    out = []
    for i in range(1, len(seq)):
        pstep, pv = seq[i - 1]
        cstep, cv = seq[i]
        pct = (cv / pv * 100) if pv else None
        out.append((pstep, cstep, pv, cv, pct))
    return out


def biggest_leak(counts: dict):
    """Шаг с наибольшим АБСОЛЮТНЫМ отвалом (prev-cur) при непустом prev.
    Возвращает (from,to,dropped,pct_kept) или None если данных нет."""
    worst = None
    for pstep, cstep, pv, cv, pct in conversions(counts):
        if pv <= 0:
            continue
        dropped = pv - cv
        if worst is None or dropped > worst[2]:
            worst = (pstep, cstep, dropped, pct)
    return worst


def parse_spend(arg: str) -> dict:
    """'reddit=42,twitter=10.5' → {'reddit':42.0,'twitter':10.5}. Тихо игнорит мусор."""
    out = {}
    for part in (arg or "").split(","):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k.strip()] = float(v.strip())
        except ValueError:
            pass
    return out


def _bar(pct):
    if pct is None:
        return "     —"
    filled = int(round(pct / 10.0))
    return "█" * filled + "░" * (10 - filled)


def human_report(f: dict, spend: dict | None = None) -> str:
    spend = spend or {}
    totals = f.get("totals", {}) or {}
    lines = []
    lines.append("=" * 60)
    lines.append("ВОРОНКА isitalpha — где рвётся путь клиента")
    lines.append("=" * 60)

    if not totals:
        lines.append("")
        lines.append("Данных пока нет (funnel.json пуст или отсутствует).")
        lines.append("Появятся, как только пойдёт трафик на /validate после деплоя.")
        return "\n".join(lines)

    seq = _steps_of(totals)
    land = seq[0][1]
    lines.append("")
    lines.append("Из тех, кто зашёл — сколько дошло до каждого шага:")
    lines.append("")
    for step, val in seq:
        pct_of_land = (val / land * 100) if land else None
        pct_txt = f"{pct_of_land:5.1f}%" if pct_of_land is not None else "   —  "
        lines.append(f"  {pct_txt}  {_bar(pct_of_land)}  {val:>6}  {LABEL[step]}")

    lines.append("")
    lines.append("Конверсия шаг→шаг (где утекают люди):")
    for pstep, cstep, pv, cv, pct in conversions(totals):
        pct_txt = f"{pct:5.1f}%" if pct is not None else "   —  "
        flag = ""
        if pct is not None and pct < 50 and pv >= 3:
            flag = "  ⚠️ узкое место"
        lines.append(f"  {LABEL[pstep]:>26} → {LABEL[cstep]:<26}  {pct_txt} ({cv}/{pv}){flag}")

    leak = biggest_leak(totals)
    if leak:
        pstep, cstep, dropped, pct = leak
        kept = f"{pct:.0f}%" if pct is not None else "—"
        lines.append("")
        lines.append(f"🔴 ГЛАВНЫЙ ОБРЫВ: «{LABEL[pstep]}» → «{LABEL[cstep]}» "
                     f"(−{dropped} чел., дошло {kept}).")

    # человеческий вывод «из 100 зашедших: 40 запустили, …, 0 оплатили»
    if land:
        def per100(step):
            return round(seq[STEPS.index(step)][1] / land * 100)
        lines.append("")
        lines.append(f"👉 Из 100 зашедших: {per100('validate_run')} запустили валидацию, "
                     f"{per100('paywall_view')} дошли до пейволла, "
                     f"{per100('pay_click')} нажали «оплатить», "
                     f"{per100('paid')} оплатили.")
        paid = seq[-1][1]
        if paid == 0:
            # где именно ноль ломается: последний непустой шаг
            last_nonzero = None
            for s, v in seq:
                if v > 0:
                    last_nonzero = s
            lines.append(f"   Рвётся на «{LABEL.get(last_nonzero, last_nonzero)}» — "
                         f"дальше не проходит НИКТО.")

    # разбивка по источникам
    srcs = f.get("sources", {}) or {}
    if srcs:
        lines.append("")
        lines.append("-" * 60)
        lines.append("По каналам (utm_source) — кто шлёт клики, но не продажи:")
        lines.append("-" * 60)
        rows = sorted(srcs.items(), key=lambda kv: kv[1].get("land", 0)
                      + kv[1].get("validate_run", 0), reverse=True)
        for name, c in rows[:12]:
            ld = c.get("land", 0)
            run = c.get("validate_run", 0)
            pw = c.get("paywall_view", 0)
            paid = c.get("paid", 0)
            crv = (run / ld * 100) if ld else None
            crp = (paid / ld * 100) if ld else None
            crv_t = f"{crv:.0f}%" if crv is not None else "—"
            crp_t = f"{crp:.1f}%" if crp is not None else "—"
            sp = spend.get(name)
            cac = ""
            if sp is not None:
                if paid:
                    cac = f"  CAC ${sp/paid:.2f}"
                else:
                    cac = f"  расход ${sp:.0f} → 0 продаж ⚠️"
            lines.append(f"  • {name:<14} land {ld:>4} → run {run:>4} ({crv_t}) "
                         f"→ paywall {pw:>4} → paid {paid:>3} ({crp_t}){cac}")

    # spend-vs-conversion сводно
    if spend:
        total_spend = sum(spend.values())
        total_paid = totals.get("paid", 0)
        lines.append("")
        lines.append(f"💸 Расход всего: ${total_spend:.0f} · продаж: {total_paid} · "
                     + (f"CAC ${total_spend/total_paid:.2f}" if total_paid
                        else "CAC = ∞ (0 продаж — деньги в трубу, чинить оффер/оплату)"))

    return "\n".join(lines)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    as_json = "--json" in argv
    spend = {}
    if "--spend" in argv:
        i = argv.index("--spend")
        if i + 1 < len(argv):
            spend = parse_spend(argv[i + 1])
    f = load()
    if as_json:
        out = {
            "totals": f.get("totals", {}),
            "conversions": [
                {"from": a, "to": b, "prev": pv, "cur": cv, "pct": pct}
                for a, b, pv, cv, pct in conversions(f.get("totals", {}))
            ],
            "biggest_leak": biggest_leak(f.get("totals", {})),
            "sources": f.get("sources", {}),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(human_report(f, spend))
    return 0


if __name__ == "__main__":
    sys.exit(main())
