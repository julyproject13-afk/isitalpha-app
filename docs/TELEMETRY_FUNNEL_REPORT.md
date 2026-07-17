# Отчёт по телеметрии воронки isitalpha

> research/analytics. Деньги/ключи/торговля не трогались. Локальный `funnel.json` — dev/тестовые данные; живые цифры на сервере.

## 1. Аудит телеметрии

Запуск: `PYTHONPATH=src:scripts python3 scripts/funnel_audit.py`

```
PASS=16 FAIL=0 INFO=1
```

**Что проверено:**
- ✅ Полный happy path (`land → validate_click → validate_run → verdict_shown → paywall_view → pay_click → paid`) инкрементит все шаги и глобально, и по `utm_source`.
- ✅ `is_probe` (User-Agent `healthcheck` / `uptimerobot`) блокирует `land` и `_bump_visit`.
- ✅ `/api/track` принимает только `validate_click` и `verdict_shown`; серверные шаги (`validate_run`, `paywall_view`, `pay_click`, `paid`) через него не накручиваются.

**Найденная дыра:**
- ⚠️ **Монотонность шагов не проверяется.** `_bump_step` инкрементит любой шаг из `FUNNEL_STEPS` без контроля порядка. Например, `paid` может появиться без `paywall_view`, а `validate_run` без `land`. Это допустимо для MVP, но при масштабе стоит добавить guard.

## 2. Сводка воронки (локальный `funnel.json`)

Запуск: `python3 scripts/funnel_report.py --json`

```json
{
  "totals": {"land": 1, "validate_run": 2, "paywall_view": 2},
  "biggest_leak": ["validate_run", "verdict_shown", 2, 0.0],
  "sources": {"direct": {"land": 1, "validate_run": 2, "paywall_view": 2}}
}
```

| Шаг | N | % от land |
|---|---|---|
| land | 1 | 100% |
| validate_click | 0 | 0% |
| validate_run | 2 | 200% *(аномалия: > land, dev-данные)* |
| verdict_shown | 0 | 0% |
| paywall_view | 2 | 200% *(аномалия: > land, dev-данные)* |
| pay_click | 0 | 0% |
| paid | 0 | 0% |

### Конверсии шаг→шаг
- `land → validate_click`: 0% (0/1) — **никто не нажал кнопку на клиенте**
- `validate_click → validate_run`: н/д (2/0) — *пропущен шаг click*
- `validate_run → verdict_shown`: 0% (0/2) — **вердикт не показан**
- `verdict_shown → paywall_view`: н/д (2/0) — *пропущен шаг verdict_shown*
- `paywall_view → pay_click`: 0% (0/2) — **пейволл не конвертирует в намерение оплатить**
- `pay_click → paid`: н/д (0/0)

## 3. Где рвётся

🔴 **Главный обрыв — `validate_run → verdict_shown`**: 2 → 0 (дошло 0%).

**Гипотезы:**
1. Клиентские beacon `/api/track` с `verdict_shown` не доходят (CORS, блокировка, ошибка на фронте).
2. Вердикт реально не показывается — фронт не отрисовывает результат после `/api/validate`.
3. Данные dev: `validate_run` и `paywall_view` могли записаться серверными событиями без клиентских `validate_click`/`verdict_shown`, поэтому 0 на промежуточных шагах.

🔴 **Второй обрыв — `paywall_view → pay_click`**: 2 → 0. Никто не нажал «оплатить».

**Гипотезы:**
- Ценник $15 отпугивает сразу (слишком высокий для импульса).
- Нет доверия к продукту / отсутствует social proof / непонятна ценность до пейволла.
- Оплата криптой — friction; если аудитория не держит USDT — конверсия ноль.
- Pay-wall появляется ДО того, как пользователь понял, что получит за деньги.

## 4. По каналам

Только `direct`, land=1, validate_run=2, paywall_view=2, paid=0. Распределить по каналам невозможно — трафика почти нет.

## 5. Мини-дашборд

Сгенерирован: `web/funnel_dashboard.html` (`python3 scripts/funnel_dashboard.py`).
- Статический HTML, читается из `funnel.json`/`metrics.json` при генерации.
- Можно открыть локально или раздать через `nginx`/app (файл лежит в `web/`, приложение отдаёт статику).

## 6. Честное ограничение

- Локальные `funnel.json` и `metrics.json` — dev-мусор (`land: 1`, `validate_run: 2`, `paywall_view: 2`, `sales: 0`).
- Живые данные на сервере: `/opt/isitalpha/funnel.json`, `/opt/isitalpha/metrics.json` или `/api/report?key=$REPORT_KEY`.
- Рекомендация владельцу: прислать `cat /opt/isitalpha/funnel.json` / `metrics.json` или выгрузить `/api/report`, после чего перегенерировать дашборд и уточнить главный обрыв.

## 7. Рекомендации

1. **Проверить фронт `/api/track`**: убедиться, что `validate_click` и `verdict_shown` шлются и доходят (204).
2. **Добавить монотонность** в `_bump_step` или при анализе: не считать `paid` без `pay_click`.
3. **A/B ценника/пейволла**: попробовать $5–$9, показать preview отчёта, добавить отзывы/примеры.
4. **Разрешить альтернативы оплаты**: карта (Cryptomus/MoR) уже есть, но нужно убедиться, что она включена и видна пользователю.
