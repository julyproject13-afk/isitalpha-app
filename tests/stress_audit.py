"""Стресс-аудит движка — адверсариальные ряды с ПРОВЕРКАМИ. Запуск: PYTHONPATH=src python3 tests/stress_audit.py
Инвариант бренда: структурный мусор → UNCLEAR (фейк, платно); подозрительно-хорошее, но правдоподобно-ряд → НЕ фейк (BORDERLINE)."""
import sys, random, math
sys.path.insert(0, "src")
from validator.validator import validate

FAILS = []


def run(name, returns, expect, n_trials=10, ppy=252):
    """expect — множество допустимых вердиктов ИЛИ строка-предикат 'not REAL'/'not UNCLEAR'."""
    v = validate(returns, n_trials=n_trials, periods_per_year=ppy)
    got = v.get("verdict", "?")
    if isinstance(expect, str) and expect.startswith("not "):
        ok = got != expect[4:]
    else:
        ok = got in (expect if isinstance(expect, (set, tuple, list)) else {expect})
    mark = "✅" if ok else "❌"
    print("%s %-34s -> %-13s sr=%-7s (ждали %s)" % (mark, name, got, v.get("net_sharpe", "-"), expect))
    if not ok:
        FAILS.append(name)


def main():
    print("=== СТРЕСС-АУДИТ ДВИЖКА (адверсариальные кейсы + проверки) ===")
    random.seed(31)
    real_example = [round(random.gauss(0.0018, 0.008), 4) for _ in range(180)]
    random.seed(7)

    run("1. реалистичный REAL(180)", real_example, "REAL", 1)
    # 2,3,12 — подозрительно «хорошо/чисто», но это ПРАВДОПОДОБНО-ряд → НЕ фейк (не REAL и не UNCLEAR)
    run("2. гладкий короткий(32)", [0.012, -0.004, 0.008, 0.015, 0.002, -0.006, 0.009,
        0.011, -0.003, 0.007, 0.013, -0.005, 0.006, 0.010, 0.004, -0.002, 0.008,
        0.012, -0.007, 0.009, 0.005, 0.011, -0.004, 0.007, 0.013, 0.003, -0.006,
        0.010, 0.008, 0.014, -0.003, 0.006], {"BORDERLINE"})
    run("3. почти-без-убытков(120)", [abs(random.gauss(0.004, 0.002)) for _ in range(120)], "not UNCLEAR")
    run("4. чистый шум(250)", [random.gauss(0, 0.01) for _ in range(250)], {"DEAD", "BORDERLINE"})
    # 5,7,8,9,11 — СТРУКТУРНЫЙ мусор → UNCLEAR (честно ловим фейк)
    run("5. эквити-кривая(1..60)", list(range(1, 61)), "UNCLEAR")
    run("6. мало точек(20)", [random.gauss(0, 0.01) for _ in range(20)], "INSUFFICIENT")
    run("7. константа(100)", [0.01] * 100, "UNCLEAR")
    run("8. бинарный ряд(120)", [(0.01 if i % 2 else -0.01) for i in range(120)], "UNCLEAR")
    run("9. арифм. прогрессия(80)", [0.001 * i for i in range(80)], "UNCLEAR")
    run("10. самообман пол/пол(220)", [((0.004 if i < 110 else -0.0015) +
        0.0006 * math.sin(i * 0.9)) for i in range(220)], {"SELF-DECEPTION", "DEAD", "BORDERLINE"})
    run("11. цены большие(90)", [round(100 + random.gauss(0, 2), 2) for _ in range(90)], "UNCLEAR")
    run("12. огромный Sharpe(200)", [round(0.01 + random.gauss(0, 0.0005), 5) for _ in range(200)], "not UNCLEAR")

    random.seed(7)
    run("13. Market-beta SR~0.5(300)", [0.0003 + random.gauss(0, 0.012) for _ in range(300)], "not REAL")
    random.seed(11)
    run("14. Regime bull->crash(300)", [random.gauss(0.004, 0.008) for _ in range(150)] +
        [random.gauss(-0.003, 0.015) for _ in range(150)], "not REAL")
    random.seed(99)
    sv = [(-0.10 if i in (87, 203, 267) else random.gauss(0.001, 0.003)) for i in range(300)]
    run("15. Short-vol+3 crashes(300)", sv, "not REAL")
    random.seed(55)
    run("16. 31pts good edge", [random.gauss(0.005, 0.01) for _ in range(31)], "not REAL", 1)
    random.seed(31)
    run("17. Weekly 2yr(104) ppy=52", [random.gauss(0.008, 0.02) for _ in range(104)], "not UNCLEAR", 5, ppy=52)
    random.seed(31)
    run("18. Monthly 5yr(60) ppy=12", [random.gauss(0.03, 0.05) for _ in range(60)], "not UNCLEAR", 5, ppy=12)
    random.seed(1)
    run("19. 5000pts noise", [random.gauss(0.001, 0.01) for _ in range(5000)], "not REAL")
    run("20. All-negative(200)", [-0.001 - abs(random.gauss(0, 0.005)) for _ in range(200)], "DEAD")

    print("\nИТОГ:", "ВСЕ 20 ПРОЙДЕНЫ ✅" if not FAILS else "ПРОВАЛЫ: %s" % FAILS)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
