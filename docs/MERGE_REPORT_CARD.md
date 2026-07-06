# 🔀 МЕРДЖ dev→боевой: карта+защита (ветка merge-card-security, 08.07.2026)

## Зачем
dev-репо (`~/honest-validator`, БЕЗ GitHub-remote) и боевой (`~/isitalpha-app`, remote=github/isitalpha-app,
сервер тянет отсюда) СИЛЬНО разошлись — почти две версии. Простой sync сломал бы прод. Сделан честный UNION.

## Что вобрал union (ветка merge-card-security)
**Из боевого (сохранено, НЕ потеряно):**
- Защита от DoS/абьюза: MAX_BODY 1MB, MAX_POINTS 10k, rate-limit (RL_MAX/окно), `_client_ip` (X-Forwarded-For).
- `/api/report` и `/api/ping` — **fail-closed** по REPORT_KEY (hmac.compare_digest) + rate-limit.
- Клампы n_trials, длины ряда.
- Виральная кнопка **Share this verdict** (shareRow/shareVerdict) в validate.html.

**Из dev (добавлено):**
- Оплата КАРТОЙ: `/api/pay/card-start` + `/api/pay/callback` (HMAC), кнопка Card (config-gated).
- Перцентиль (`percentile`/`graveyard_n`), бейдж (`/api/badge`, `/api/badge.svg`), подписка (`/api/plans`),
  regime-тир, телеметрия воронки (`/api/track`, funnel).
- Модули: validator.py (надмножество), badge.py, plans.py, pay_card.py, graveyard_dist.json.
- Ops: update_stats.py, daily_monitor.py, funnel_report.py, health_check.py.

## НЕ трогали (осознанно)
- `web/landing.html` — тоже разошёлся, но не платёжно-критичен → оставлен боевой (регресс не нужен). Ревью отдельно.
- `bootstrap.env` — секреты, НЕ копировались.
- `main` — нетронут (мердж на ветке).

## Smoke-тест (в боевом репо, ветка) — PASS
- app.py компилится; все модули импортятся.
- /validate 200 (shareVerdict + cardCheckout + pctlBadge присутствуют).
- /api/validate → BORDERLINE, percentile=100, pay_card_ready=False (gated).
- /api/report → 403 fail-closed. /api/plans 200. /api/badge.svg 200. rate-limit → 429 после лимита.
- Карта скрыта без env → нулевой риск текущему поведению.

## КАК ФИНАЛИЗИРОВАТЬ (владелец, на возвращении)
1. **Ревью:** в GitHub Desktop переключись на ветку `merge-card-security`, глянь diff (app.py/validate.html/модули).
2. Прогони визуально локально (опц.): `RATE_LIMIT_MAX=50 REPORT_KEY=tk PYTHONPATH=src python3 scripts/app.py 8480` → открой http://127.0.0.1:8480/validate → Load example → вердикт+share видны, Card НЕ виден (env нет).
3. Если ок — **merge ветки в main** (GitHub Desktop: Branch → Merge into current branch, будучи на main) → **Push origin**.
4. Деплой: VNC на сервере → `cd /opt/isitalpha` → `git pull` → рестарт (`systemctl restart isitalpha`).
5. Проверь боевой isitalpha.com/validate: вердикт, крипто-кнопки, share. Card появится ПОЗЖЕ (когда впишешь PAY_* от Димы в bootstrap.env — без нового деплоя).
6. **Проверь, что крипто-оплата всё ещё работает** (главный регресс-риск) — тест-заход.

Коммит ветки: 1087f89. main: 5a3c5c6 (не тронут).
