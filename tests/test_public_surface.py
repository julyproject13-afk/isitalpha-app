"""Что сервер отдаёт наружу: ТОЛЬКО явно разрешённое.

Контекст (19.07.2026): сервер отдавал любой файл, лежащий в web/. То есть
положить файл в папку означало опубликовать его в интернете. Так наружу утекли
три внутренние страницы, включая дашборд воронки, публично показывавший
«0 продаж, $0 выручка». Этот тест держит границу: список публичных файлов
задаётся явно, а всё, что в web/ появилось и в список не внесено, — не публично.

Запуск: PYTHONPATH=src python3 tests/test_public_surface.py
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEB = os.path.join(ROOT, "web")
APP = os.path.join(ROOT, "scripts", "app.py")

_n = 0


def check(cond, msg):
    global _n
    assert cond, "FAIL: " + msg
    _n += 1
    print("  [OK]", msg)


src = open(APP, encoding="utf-8").read()

print("ТЕСТ публичной поверхности:")

# 1. Список существует и применяется в раздаче статики.
check("PUBLIC_FILES" in src, "список PUBLIC_FILES задан")
check(re.search(r"safe in PUBLIC_FILES", src),
      "раздача статики идёт ЧЕРЕЗ список, а не по наличию файла на диске")
check(not re.search(r"if safe and os\.path\.isfile", src),
      "старое правило «есть файл → отдаём» убрано")

# 2. Разбираем сам список.
block = re.search(r"PUBLIC_FILES\s*=\s*frozenset\(\{(.*?)\}\)", src, re.S)
check(block is not None, "список читается")
allowed = set(re.findall(r'"([^"]+)"', block.group(1)))

# 3. Каждый разрешённый файл существует — список не гниёт молча.
for f in sorted(allowed):
    check(os.path.isfile(os.path.join(WEB, f)), "разрешённый файл на месте: %s" % f)

# 4. ГЛАВНОЕ: ничего в web/ не оказалось публичным «само собой».
on_disk = set()
for base, _dirs, files in os.walk(WEB):
    for name in files:
        rel = os.path.relpath(os.path.join(base, name), WEB)
        on_disk.add(rel.replace(os.sep, "/"))
extra = sorted(on_disk - allowed)
check(not extra,
      "в web/ нет файлов вне списка (найдено бы: %s)" % (extra or "—"))

# 5. Русские служебные страницы не должны вернуться в публичный список.
for banned in ("validate_ru.html", "landing_ru.html", "funnel_dashboard.html"):
    check(banned not in allowed, "не публикуется снова: %s" % banned)

print(f"\nВСЕГО ПРОВЕРОК: {_n} — РЕЗУЛЬТАТ: PASS")
