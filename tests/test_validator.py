"""Тесты Honest Validator (2-й продукт). PYTHONPATH=src python3 tests/test_validator.py"""
import sys, math, random; sys.path.insert(0,"src")
from validator.validator import validate, parse_returns_csv

_n=0
def check(c,m):
    global _n; assert c,"FAIL: "+m; _n+=1; print("  [OK]",m)

print("ТЕСТ Honest Validator:")
# 1) РЕАЛЬНЫЙ край — РЕАЛИСТИЧНЫЙ (умеренный Sharpe, с убытками и просадками)
random.seed(31)
real=[round(random.gauss(0.0018,0.008),4) for _ in range(180)]
r=validate(real, n_trials=1)
check(r["verdict"]=="REAL","реалистичный устойчивый край → REAL")
check(r["cv_worst_fold"]>0,"худший фолд положителен у реального края")
check(0 < r["net_sharpe"] <= 8,"Sharpe правдоподобный (не фейк)")

# 1b) ЗАЩИТА: фейк-гладкий ряд с НЕРЕАЛЬНЫМ Sharpe — НЕ должен быть REAL
smooth=[0.0018 + 0.0004*math.sin(i*0.7) for i in range(220)]
r=validate(smooth, n_trials=10)
check(r["verdict"]!="REAL","фейк-гладкий (Sharpe нереален) НЕ проходит как реальный")
check(r["verdict"]=="BORDERLINE","нереальный Sharpe → BORDERLINE (слишком хорошо, но НЕ называем фейком)")
check(r["verdict"]!="UNCLEAR","реальный ряд с высоким Sharpe НЕ помечается фейком (UNCLEAR)")

# 1c) ЗАЩИТА: прошёл проверки, но мало данных (<60) — НЕ сертифицируем как REAL
random.seed(31)
short=[round(random.gauss(0.0018,0.008),4) for _ in range(45)]
r=validate(short, n_trials=1)
check(r["verdict"]!="REAL","<60 точек не сертифицируем как REAL")

# 2) САМООБМАН — работает в первой половине, теряет во второй (переподгон/режим)
fake=[(0.004 if i<110 else -0.0015) + 0.0006*math.sin(i*0.9) for i in range(220)]
r=validate(fake, n_trials=10)
check(r["verdict"]=="SELF-DECEPTION","полураб/полупровал → САМООБМАН")
check(r["cv_worst_fold"]<0,"худший фолд отрицателен у самообмана")
check(any("period" in x for x in r["reasons"]),"причина: не держится по периодам (EN 'period')")

# 3) МЁРТВЫЙ — нет края после издержек
dead=[0.0003 + 0.0015*math.sin(i*1.3) for i in range(220)]
r=validate(dead, n_trials=10)
check(r["verdict"] in ("DEAD","BORDERLINE","SELF-DECEPTION"),"слабый/нулевой → не REAL")
check(r["verdict"]!="REAL","нулевой край НЕ проходит как реальный")

# 4) мало данных
check(validate([0.01]*10)["verdict"]=="INSUFFICIENT","<30 точек → INSUFFICIENT")

# 5) парсер CSV
p=parse_returns_csv("0.01, 0.02; -0.005\n0.03 мусор 0.01")
check(len(p)==5 and p[0]==0.01,"парсер: числа из CSV/мусора")
check(parse_returns_csv("5\n-3\n2")[0]==0.05,"парсер: проценты (5 → 0.05)")

# 6) метрики на месте
m=validate(real, n_trials=1)
check(all(kk in m for kk in ["net_sharpe","cv_worst_fold","deflated_threshold","max_drawdown","cvar","headline"]),"вердикт содержит метрики+headline")
print(f"\nВСЕГО ПРОВЕРОК: {_n} — РЕЗУЛЬТАТ: PASS")
