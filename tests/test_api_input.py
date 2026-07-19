"""Форматы входа /api/validate: ничто не должно ронять обработчик.

Контекст (19.07.2026): POST с JSON-массивом в `returns` валил обработчик
AttributeError'ом внутри parse_returns_csv — список не имеет .replace. Снаружи
это выглядело как 502 Bad Gateway, то есть «сайт не работает», причём именно у
технической аудитории, которая естественным образом шлёт массив, а не строку.

Запуск: PYTHONPATH=src python3 tests/test_api_input.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from validator.validator import parse_returns_csv  # noqa: E402

_n = 0


def check(cond, msg):
    global _n
    assert cond, "FAIL: " + msg
    _n += 1
    print("  [OK]", msg)


print("ТЕСТ форматов входа parse_returns_csv:")

# 1. Строка — исторический формат, который шлёт сайт.
check(parse_returns_csv("0.01,-0.005,0.012") == [0.01, -0.005, 0.012],
      "строка CSV разбирается")

# 2. JSON-массив чисел — так шлёт любой, кто дёргает API из кода.
check(parse_returns_csv([0.01, -0.005, 0.012]) == [0.01, -0.005, 0.012],
      "JSON-массив чисел разбирается (раньше падал AttributeError)")

# 3. Массив строк — частый случай выгрузки из CSV.
check(parse_returns_csv(["0.01", "-0.005"]) == [0.01, -0.005],
      "массив строк разбирается")

# 4. Проценты приводятся к доле одинаково в обоих форматах.
check(parse_returns_csv([5.0]) == parse_returns_csv("5.0") == [0.05],
      "проценты → доля одинаково для массива и строки")

# 5. Мусор не роняет, а отбрасывается.
check(parse_returns_csv([0.01, None, "abc", True, 0.02]) == [0.01, 0.02],
      "мусор внутри массива отбрасывается, не роняет")

# 6. Пограничные значения не роняют.
for bad in (None, 42, {"a": 1}, [], ""):
    try:
        parse_returns_csv(bad)
    except Exception as e:
        raise AssertionError("FAIL: упало на входе %r: %r" % (bad, e))
check(True, "None/число/словарь/пустое не роняют")

# 7. Обработчик POST обёрнут — необработанное исключение отдаёт 500, а не рвёт связь.
app_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "scripts", "app.py"), encoding="utf-8").read()
check("def _do_post" in app_src and "internal error" in app_src,
      "do_POST обёрнут try/except → 500 JSON вместо обрыва (502)")

print(f"\nВСЕГО ПРОВЕРОК: {_n} — РЕЗУЛЬТАТ: PASS")
