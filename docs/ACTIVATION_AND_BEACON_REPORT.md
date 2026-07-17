# Отчёт — фикс активации и надёжности beacon

> research/dev, деньги/ключи не трогались. Локальный `funnel.json` всё ещё dev-мусор; живые цифры на сервере.

## Что сделано

### 1. Активация — кнопка «Try with example»

- **`web/validate.html`**: кнопка `↧ Load example` переименована в `↧ Try with example`, подставляет готовый ряд доходностей и `n_trials=1`.
- Добавлена микро-подсказка у поля: формат, 30+ значений, 60 сек, free verdict.
- **`web/validate_ru.html`**: добавлена та же механика, beacon `example_click`, подсказка «Пример (реальный) — за 60 секунд».
- Добавлен новый шаг воронки `example_click` в:
  - `scripts/app.py` (`FUNNEL_STEPS`, `/api/track` принимает `example_click`)
  - `scripts/funnel_report.py` (`STEPS`, `LABEL`)
  - `scripts/funnel_dashboard.py` (`STEPS`, `LABEL`)
  - `scripts/funnel_audit.py` (happy path + assertions)

### 2. Beacon-надёжность

- **`web/validate.html`**: `track()` уже использовал `navigator.sendBeacon` с `fetch`-fallback; оставлен.
- **`web/validate_ru.html`**: добавлена идентичная `track()` + `trafficSrc()` функция.
- **`scripts/app.py /api/validate`**: `verdict_shown` теперь считается на сервере при отдаче свежего не-INSUFFICIENT вердикта (рядом с `validate_run`).
- **`scripts/app.py /api/track`**: из списка разрешённых клиентских шагов убран `verdict_shown`, чтобы не дублировать серверный счёт.
- Из `web/validate.html` и `web/validate_ru.html` убран клиентский `track("verdict_shown")`.

### 3. Монотонность — предупреждение в отчёте

- `scripts/funnel_report.py`: добавлен `monotonicity_issues()` + вывод в human- и JSON-отчётах.
- Теперь видно, если поздний шаг оказался больше предыдущего (например, `validate_run > validate_click` из-за дубли/старых beacon).

## Проверки

- `PYTHONPATH=src:scripts python3 scripts/funnel_audit.py` — **PASS=20, FAIL=0, INFO=1**.
- `python3 -m pytest tests -q` — **4 passed**.
- `python3 scripts/funnel_report.py` — отрабатывает с новым шагом `example_click` и флагами немонотонности.
- `python3 scripts/funnel_dashboard.py` — перегенерировал `web/funnel_dashboard.html`.

## Честные ограничения

- Локальный `funnel.json` — старый dev-набор (`land:1, validate_run:2, paywall_view:2`), поэтому в отчёте всё ещё немонотонность и 0% на клиентских шагах. Это ожидаемо.
- Реальный эффект «Try with example» можно измерить только на живом трафике: смотреть рост `example_click` и `validate_run` из `/opt/isitalpha/funnel.json`.
- Примерные ряды в `validate.html` / `validate_ru.html` взяты из существующих данных, но не гарантированно дают DEAD/SELF-DECEPTION на продакшен-конфиге. Если цель — показать именно «мёртвую» стратегию, нужно подобрать/проверить ряд на `scripts/validator.validator`.

## Рекомендации владельцу

1. **Деплой** и проверить `funnel.json` на сервере через 1–2 дня.
2. **A/B**: сравнить `land → (example_click + validate_click)` до и после появления кнопки.
3. **Проверить beacon**: в DevTools убедиться, что `/api/track` уходит с `example_click` и `validate_click` (204).
4. **Подобрать убойный пример**: если `example_click → validate_run` низкий, заменить ряд на тот, что даёт наглядный DEAD/SELF-DECEPTION.
