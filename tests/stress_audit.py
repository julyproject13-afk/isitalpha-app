"""Стресс-аудит движка — адверсариальные ряды. Запуск: PYTHONPATH=src python3 tests/stress_audit.py
Готовый файл, чтобы НЕ вписывать многострочный python в терминал (мнёт кавычки)."""
import sys, random, math
sys.path.insert(0, "src")
from validator.validator import validate


def run(name, returns, n_trials=10, ppy=252):
    v = validate(returns, n_trials=n_trials, periods_per_year=ppy)
    print("%-38s -> %-15s sr=%-8s dd=%-8s warn=%d" % (
        name, v.get("verdict", "?"), v.get("net_sharpe", "-"),
        v.get("max_drawdown", "-"), len(v.get("data_warning") or [])))


def main():
    print("=== СТРЕСС-АУДИТ ДВИЖКА (адверсариальные кейсы) ===")
    random.seed(31)
    real_example = [round(random.gauss(0.0018, 0.008), 4) for _ in range(180)]
    random.seed(7)

    run("1. реалистичный REAL(180) n=1", real_example, 1)
    run("2. фейк-гладкий(32)", [0.012, -0.004, 0.008, 0.015, 0.002, -0.006, 0.009,
        0.011, -0.003, 0.007, 0.013, -0.005, 0.006, 0.010, 0.004, -0.002, 0.008,
        0.012, -0.007, 0.009, 0.005, 0.011, -0.004, 0.007, 0.013, 0.003, -0.006,
        0.010, 0.008, 0.014, -0.003, 0.006])
    run("3. почти-без-убытков(120)", [abs(random.gauss(0.004, 0.002)) for _ in range(120)])
    run("4. чистый шум(250)", [random.gauss(0, 0.01) for _ in range(250)])
    run("5. эквити-кривая(1..60)", list(range(1, 61)))
    run("6. мало точек(20)", [random.gauss(0, 0.01) for _ in range(20)])
    run("7. константа(100)", [0.01] * 100)
    run("8. бинарный ряд(120)", [(0.01 if i % 2 else -0.01) for i in range(120)])
    run("9. арифм. прогрессия(80)", [0.001 * i for i in range(80)])
    run("10. самообман пол/пол(220)", [((0.004 if i < 110 else -0.0015) +
        0.0006 * math.sin(i * 0.9)) for i in range(220)])
    run("11. цены (большие значения)(90)", [round(100 + random.gauss(0, 2), 2) for _ in range(90)])
    run("12. огромный Sharpe(200)", [round(0.01 + random.gauss(0, 0.0005), 5) for _ in range(200)])

    # --- расширенные адверсариальные кейсы ---
    random.seed(7)
    run("13. Market-beta SR~0.5(300)", [0.0003 + random.gauss(0, 0.012) for _ in range(300)])
    random.seed(11)
    run("14. Regime bull->crash(300)", [random.gauss(0.004, 0.008) for _ in range(150)] +
        [random.gauss(-0.003, 0.015) for _ in range(150)])
    random.seed(99)
    sv = []
    for i in range(300):
        sv.append(-0.10 if i in (87, 203, 267) else random.gauss(0.001, 0.003))
    run("15. Short-vol+3 crashes(300)", sv)
    random.seed(55)
    run("16. 31pts good edge n=1", [random.gauss(0.005, 0.01) for _ in range(31)], 1)
    random.seed(31)
    run("17. Weekly 2yr(104) ppy=52", [random.gauss(0.008, 0.02) for _ in range(104)], 5, ppy=52)
    random.seed(31)
    run("18. Monthly 5yr(60) ppy=12", [random.gauss(0.03, 0.05) for _ in range(60)], 5, ppy=12)
    random.seed(1)
    run("19. 5000pts noise", [random.gauss(0.001, 0.01) for _ in range(5000)])
    run("20. All-negative(200)", [-0.001 - abs(random.gauss(0, 0.005)) for _ in range(200)])

    print("\nОжидания: 1->REAL; 2,3,12->UNCLEAR; 4->DEAD; 5,7,8,9,11->UNCLEAR; 6->INSUFFICIENT; 10->SELF-DECEPTION")
    print("13->не REAL(слабый); 14->не REAL(режим); 15->info; 16->не REAL(<60); 17,18->info; 19->info; 20->DEAD")


if __name__ == "__main__":
    main()
