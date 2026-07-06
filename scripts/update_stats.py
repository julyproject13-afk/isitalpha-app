#!/usr/bin/env python3
"""АВТО-ОБНОВЛЕНИЕ статистики isitalpha из кладбища краёв (cron-совместимо).

Читает edge_graveyard.jsonl (по строке JSON на край) → пересчитывает stats.json
(tested/killed/dead/self_deception/borderline/real) → пишет в web/stats.json.
Числа на лендинге читаются из stats.json (fetch no-store) → сайт показывает актуал
АВТОМАТИЧЕСКИ, как только кладбище растёт. Владелец просил: «убитые края если растёт
статистика — автоматически».

Запуск:
  python3 scripts/update_stats.py                 # дефолтные пути
  GRAVEYARD=/path/to/edge_graveyard.jsonl \
  STATS_TARGETS=/a/web/stats.json,/b/web/stats.json python3 scripts/update_stats.py

Cron (пример — каждый час):
  0 * * * * cd ~/honest-validator && /usr/bin/python3 scripts/update_stats.py >> /tmp/isitalpha_stats.log 2>&1
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# кладбище: env GRAVEYARD, иначе каноничный golden-mutation, иначе локальная копия в репо
DEFAULT_GRAVE_CANDIDATES = [
    os.environ.get("GRAVEYARD", ""),
    os.path.expanduser("~/golden-mutation/campaign/edge_graveyard.jsonl"),
    os.path.join(ROOT, "data", "edge_graveyard.jsonl"),
]

# куда писать stats.json: env STATS_TARGETS (через запятую), иначе dev + боевой репо
DEFAULT_TARGETS = [
    os.path.join(ROOT, "web", "stats.json"),
    "/Users/yuriibond/isitalpha-app/web/stats.json",
]


def _grave_path() -> str:
    for c in DEFAULT_GRAVE_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    return ""


def _targets():
    env = os.environ.get("STATS_TARGETS", "")
    if env.strip():
        return [t.strip() for t in env.split(",") if t.strip()]
    return DEFAULT_TARGETS


def compute(grave_path: str):
    """Пересчитать счётчики вердиктов из jsonl-кладбища. None если файла нет."""
    if not (grave_path and os.path.isfile(grave_path)):
        return None
    c = {"tested": 0, "dead": 0, "self_deception": 0, "borderline": 0, "real": 0}
    with open(grave_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line).get("verdict")
            except Exception:
                continue
            c["tested"] += 1
            if v == "DEAD":
                c["dead"] += 1
            elif v == "SELF-DECEPTION":
                c["self_deception"] += 1
            elif v == "BORDERLINE":
                c["borderline"] += 1
            elif v == "REAL":
                c["real"] += 1
    c["killed"] = c["dead"] + c["self_deception"]
    # порядок ключей как в текущем stats.json
    return {"tested": c["tested"], "killed": c["killed"], "dead": c["dead"],
            "self_deception": c["self_deception"], "borderline": c["borderline"], "real": c["real"]}


def write_stats(stats: dict, targets) -> int:
    """Записать stats только если ИЗМЕНИЛОСЬ (не трогаем файл зря). Возвращает число записанных."""
    written = 0
    for t in targets:
        try:
            if os.path.isfile(t):
                try:
                    if json.load(open(t, encoding="utf-8")) == stats:
                        print("без изменений:", t)
                        continue
                except Exception:
                    pass
            os.makedirs(os.path.dirname(t), exist_ok=True)
            json.dump(stats, open(t, "w"))
            written += 1
            print("обновлён", t, "→", stats)
        except Exception as e:
            print("не записал", t, e)
    return written


def main() -> int:
    grave = _grave_path()
    stats = compute(grave)
    if stats is None:
        print("кладбище не найдено (проверь GRAVEYARD / пути):", DEFAULT_GRAVE_CANDIDATES)
        return 1
    print("кладбище:", grave)
    write_stats(stats, _targets())
    return 0


if __name__ == "__main__":
    sys.exit(main())
