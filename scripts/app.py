"""Honest Validator (Продукт 2) web-приложение. Самодостаточно, чистый stdlib.
Маршруты: /validate (форма) /report (отчёт) /api/validate (вердикт)
          /api/checkout (создать счёт NOWPayments) /api/ipn (вебхук оплаты) /api/unlock (проверка).
Пейволл: free = только вердикт-слово; полный отчёт — после оплаты $9.
Платёж: NOWPayments (non-custodial, USDT TRC20 → кошелёк владельца). Деньги напрямую владельцу, мы их не держим.
Секреты (NP_API_KEY, NP_IPN_SECRET) — в bootstrap.env, не в git.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
WEB = os.path.join(ROOT, "web")
PAID_FILE = os.path.join(ROOT, "paid_orders.txt")   # оплаченные order_id (локальный учёт)

# Что вообще разрешено отдавать наружу. Всё, чего здесь нет, — 404, даже если
# файл лежит в web/. Разрешение публикации должно быть осознанным действием:
# положить файл в папку — не то же самое, что опубликовать его в интернете.
PUBLIC_FILES = frozenset({
    "landing.html", "validate.html", "report.html", "legal.html",
    "stats.json", "robots.txt", "sitemap.xml",
    "favicon.png", "og.png",
    "learn/index.html",
    "learn/is-a-sharpe-ratio-of-2-good.html",
    "learn/is-my-backtest-overfit.html",
})

from validator.validator import validate, regime_judge, parse_returns_csv      # noqa: E402
from validator.badge import badge_svg, badge_embed_html          # noqa: E402
from validator import plans as _plans                            # noqa: E402
from validator import pay_card as _paycard                       # noqa: E402
from validator import pay_cryptomus as _paycm                    # noqa: E402

_CT = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
       ".txt": "text/plain; charset=utf-8", ".xml": "application/xml; charset=utf-8"}


def _load_env():
    f = os.path.join(ROOT, "bootstrap.env")
    if os.path.isfile(f):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
NP_API_KEY = os.environ.get("NP_API_KEY", "")          # ключ мерчанта NOWPayments (секрет)
NP_IPN_SECRET = os.environ.get("NP_IPN_SECRET", "")    # секрет для проверки вебхука (секрет)
SITE_URL = os.environ.get("SITE_URL", "https://isitalpha.com")
PRICE_USD = int(os.environ.get("PRICE_USD", "15"))   # $15 «all fees included»; меняется через bootstrap.env без правки кода.
PAY_CURRENCY = os.environ.get("PAY_CURRENCY", "")   # пусто = клиент сам выбирает валюту/сеть на оплате (Polygon дешевле всего). Можно форснуть через bootstrap.env (напр. usdcmatic).
TG_TOKEN = os.environ.get("PULSE_TG_TOKEN", "")        # бот для уведомлений (тот же, что Pulse)
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")    # чат владельца для алертов/сводки
REPORT_KEY = os.environ.get("REPORT_KEY", "")          # защита /api/report (простой ключ)
METRICS_FILE = os.path.join(ROOT, "metrics.json")      # бизнес-счётчики (локально)
FUNNEL_FILE = os.path.join(ROOT, "funnel.json")        # пофазная воронка (анонимно, без PII)

FREE_FIELDS = ("verdict", "headline", "n", "reason", "percentile", "graveyard_n")

# ---------- защита от DoS / абьюза (уровень приложения; nginx/CF — снаружи) ----------
MAX_BODY = 1_048_576          # 1 MB — потолок тела POST (self.rfile.read по Content-Length)
MAX_POINTS = 10_000           # потолок длины ряда (≈40 лет дневных данных — с запасом)
RL_MAX = int(os.environ.get("RATE_LIMIT_MAX", "30"))    # запросов на IP в окно
RL_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # окно, сек
_RL_LOCK = threading.Lock()
_RL: dict = {}                # ip -> [window_start_ts, count]


def _rate_ok(ip: str) -> bool:
    """Простой лимитер: не более RL_MAX запросов с IP за RL_WINDOW сек. Потокобезопасно."""
    now = time.time()
    with _RL_LOCK:
        w = _RL.get(ip)
        if not w or now - w[0] >= RL_WINDOW:
            _RL[ip] = [now, 1]
            if len(_RL) > 10000:                     # редкая чистка протухших окон
                for k in [k for k, v in list(_RL.items()) if now - v[0] >= RL_WINDOW]:
                    _RL.pop(k, None)
            return True
        if w[1] >= RL_MAX:
            return False
        w[1] += 1
        return True


# ---------- бизнес-метрики (попытки/продажи/выручка) ----------
def _metrics() -> dict:
    try:
        return json.load(open(METRICS_FILE, encoding="utf-8"))
    except Exception:
        return {"attempts": 0, "sales": 0, "revenue": 0, "first_ts": 0, "last_sale_ts": 0,
                "seen_orders": [], "sources": {}, "order_src": {}}


# ---------- атрибуция источника (utm_source): визит → проверка → продажа ----------
def _norm_src(s: str) -> str:
    """Нормализует метку источника: нижний регистр, только буквы/цифры/-/_, ≤24 симв. Пусто/None → 'direct'."""
    if not s:
        return "direct"
    s = "".join(c for c in str(s).lower() if c.isalnum() or c in "-_")[:24]
    return s or "direct"


def _src_row(m: dict, src: str) -> dict:
    """Возвращает (создавая при необходимости) строку воронки для источника внутри m. Мутирует m."""
    return m.setdefault("sources", {}).setdefault(
        _norm_src(src), {"visits": 0, "attempts": 0, "sales": 0, "revenue": 0})


def _bump_visit(src: str):
    """Заход на /validate с ?utm_source=... — засчитываем визит каналу (перекрёстная сверка с рекламой)."""
    m = _metrics()
    _src_row(m, src)["visits"] += 1
    _save_metrics(m)


def _tag_order(order_id: str, src: str):
    """Привязывает заказ к источнику на этапе checkout, чтобы потом атрибутировать продажу каналу."""
    if not (order_id and src):
        return
    m = _metrics()
    om = m.setdefault("order_src", {})
    om[order_id] = _norm_src(src)
    if len(om) > 1000:                      # держим карту компактной
        for k in list(om)[:-1000]:
            om.pop(k, None)
    _save_metrics(m)


def _save_metrics(m: dict):
    try:
        json.dump(m, open(METRICS_FILE, "w"))
    except Exception:
        pass


def _bump_attempt(src: str = ""):
    import time
    m = _metrics()
    m["attempts"] = m.get("attempts", 0) + 1
    if not m.get("first_ts"):
        m["first_ts"] = int(time.time())
    if src:
        _src_row(m, src)["attempts"] += 1
    _save_metrics(m)


def _record_sale(order_id: str) -> dict | None:
    """Учитывает продажу один раз на order (защита от дубля вебхука). None если уже учтён."""
    import time
    m = _metrics()
    seen = set(m.get("seen_orders", []))
    if order_id in seen:
        return None
    seen.add(order_id)
    m["seen_orders"] = list(seen)[-500:]
    m["sales"] = m.get("sales", 0) + 1
    m["revenue"] = m.get("revenue", 0) + PRICE_USD
    m["last_sale_ts"] = int(time.time())
    src = m.get("order_src", {}).get(order_id)      # атрибуция продажи каналу (если заказ был помечен)
    if src:
        row = _src_row(m, src)
        row["sales"] += 1
        row["revenue"] += PRICE_USD
    _save_metrics(m)
    return m


def tg_send(text: str):
    """Шлёт сообщение владельцу в Telegram (алерты/продажи/сводка). Тихо, не роняет запрос."""
    if not (TG_TOKEN and OWNER_CHAT_ID):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": OWNER_CHAT_ID, "text": text,
                                       "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                     data=data, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def stats_report() -> str:
    """Красивая бизнес-сводка для Telegram."""
    import time
    m = _metrics()
    a = m.get("attempts", 0); s = m.get("sales", 0); rev = m.get("revenue", 0)
    conv = (s / a * 100) if a else 0
    net = round(rev * 0.99, 2)          # минус ~1% NOWPayments
    per = f"${PRICE_USD} − ~${round(PRICE_USD*0.01,2)} комиссия = ~${round(PRICE_USD*0.99,2)} net"
    last = m.get("last_sale_ts", 0)
    last_s = time.strftime("%d.%m %H:%M", time.gmtime(last)) + " UTC" if last else "—"
    # воронка по источникам: визит → проверка → продажа (самые «жирные» каналы сверху)
    srcs = m.get("sources", {})
    funnel = ""
    if srcs:
        rows = sorted(srcs.items(), key=lambda kv: kv[1].get("visits", 0) + kv[1].get("attempts", 0), reverse=True)
        lines = []
        for name, r in rows[:6]:
            v, at, sa = r.get("visits", 0), r.get("attempts", 0), r.get("sales", 0)
            cr = (sa / v * 100) if v else 0
            lines.append(f"• <b>{name}</b>: {v} визит → {at} пров. → {sa} прод.  (CR {cr:.1f}%)")
        funnel = "\n\n🧭 <b>Каналы (визит→проверка→продажа):</b>\n" + "\n".join(lines)
    return (
        "📊 <b>isitalpha — сводка</b>\n\n"
        f"👀 Попыток проверки: <b>{a}</b>\n"
        f"✅ Продаж (${PRICE_USD}): <b>{s}</b>\n"
        f"💰 Выручка: <b>${rev}</b>  (net ~${net})\n"
        f"📈 Конверсия: <b>{conv:.1f}%</b>\n\n"
        f"📦 Юнит-экономика: {per}\n"
        f"🎯 CAC: добавь расход рекламы из реестра → CAC = расход/продажи\n"
        f"🕐 Последняя продажа: {last_s}"
        f"{funnel}\n\n"
        "<i>LTV пока = 1 покупка (разовый продукт). Следим за повторными и пакетами.</i>"
    )


# ---------- ПОФАЗНАЯ ТЕЛЕМЕТРИЯ ВОРОНКИ (анонимно, без PII) ----------
# Считаем ТОЛЬКО обезличенные счётчики шагов воронки, с разбивкой по utm_source.
# Никаких IP, user-agent, cookie, id пользователей — только «сколько людей дошло до шага».
# Файл funnel.json локальный, не в git (как metrics.json). Смысл: увидеть, ГДЕ рвётся.
#
# Шаги воронки (порядок = путь клиента):
#   land       — зашёл на /validate (страница отдана)
#   validate_click — нажал «Get honest verdict» (клиентское событие)
#   validate_run   — сервер реально прогнал валидацию (свежий вердикт, не повтор оплаты)
#   verdict_shown  — фронт показал вердикт-слово
#   example_click  — нажал «Try with example» / «Показать на примере»
#   paywall_view   — упёрся в пейволл (увидел locked-экран с ценой)
#   pay_click      — нажал кнопку «Pay $…» (создание счёта)
#   paid           — оплата подтверждена (IPN finished/confirmed)
FUNNEL_STEPS = ("land", "example_click", "validate_click", "validate_run", "verdict_shown",
                "paywall_view", "pay_click", "paid")


def _funnel() -> dict:
    try:
        return json.load(open(FUNNEL_FILE, encoding="utf-8"))
    except Exception:
        return {"totals": {}, "sources": {}, "first_ts": 0, "last_ts": 0}


def _save_funnel(f: dict):
    try:
        json.dump(f, open(FUNNEL_FILE, "w"))
    except Exception:
        pass


def _bump_step(step: str, src: str = ""):
    """Инкремент счётчика шага воронки (глобально + по источнику). Тихо игнорит чужие шаги."""
    import time
    if step not in FUNNEL_STEPS:
        return
    f = _funnel()
    now = int(time.time())
    if not f.get("first_ts"):
        f["first_ts"] = now
    f["last_ts"] = now
    f.setdefault("totals", {})[step] = f.get("totals", {}).get(step, 0) + 1
    row = f.setdefault("sources", {}).setdefault(_norm_src(src), {})
    row[step] = row.get(step, 0) + 1
    # держим карту источников компактной (не даём разрастись мусорным меткам)
    if len(f["sources"]) > 200:
        # оставляем 200 самых «наполненных» источников по суммарным событиям
        top = sorted(f["sources"].items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:200]
        f["sources"] = dict(top)
    _save_funnel(f)


# ---------- учёт оплат (простой файл; для MVP достаточно) ----------
def _paid_set():
    try:
        return set(x.strip() for x in open(PAID_FILE, encoding="utf-8") if x.strip())
    except FileNotFoundError:
        return set()


def _mark_paid(order_id):
    with open(PAID_FILE, "a", encoding="utf-8") as f:
        f.write(order_id + "\n")


def is_paid(order_id: str) -> bool:
    return bool(order_id) and order_id in _paid_set()


# ---------- NOWPayments ----------
PAY_COINS = {"usdttrc20": "USDT (TRON)", "usdcmatic": "USDC (Polygon)"}  # монеты клиентских кнопок


def np_create_invoice(order_id: str, coin: str = "") -> str:
    """Создаёт счёт на $PRICE_USD, возвращает ссылку на оплату. Пусто, если не настроено.
    coin — фикс-монета из PAY_COINS (кнопка → чистый экран одной монеты, без списка);
    иначе берётся PAY_CURRENCY (env) либо открытый выбор клиентом."""
    if not NP_API_KEY:
        return ""
    payload = {
        "price_amount": PRICE_USD, "price_currency": "usd",
        "order_id": order_id, "order_description": "isitalpha — Full Strategy Report",
        "success_url": f"{SITE_URL}/validate?paid={order_id}",
        "cancel_url": f"{SITE_URL}/validate",
        "ipn_callback_url": f"{SITE_URL}/api/ipn",
    }
    cur = coin if coin in PAY_COINS else PAY_CURRENCY   # кнопка форсит монету; иначе env/открытый выбор
    if cur:
        payload["pay_currency"] = cur
    try:
        req = urllib.request.Request(
            "https://api.nowpayments.io/v1/invoice",
            data=json.dumps(payload).encode(),
            headers={"x-api-key": NP_API_KEY, "Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (isitalpha)"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        return d.get("invoice_url", "")
    except Exception:
        return ""


def np_ipn_valid(raw: bytes, sig: str) -> bool:
    """Проверяет подпись вебхука NOWPayments (HMAC-SHA512 отсортированного JSON)."""
    if not (NP_IPN_SECRET and sig):
        return False
    try:
        data = json.loads(raw)
    except Exception:
        return False
    base = json.dumps(data, separators=(",", ":"), sort_keys=True)
    # NOWPayments (PHP json_encode) экранирует слэши как \/, Python — нет. Пробуем оба варианта.
    for candidate in (base, base.replace("/", "\\/")):
        mac = hmac.new(NP_IPN_SECRET.encode(), candidate.encode(), hashlib.sha512).hexdigest()
        if hmac.compare_digest(mac, sig):
            return True
    return False


def gate(result: dict, paid: bool) -> dict:
    """Не оплачено → только вердикт-слово + флаг locked + цена.
    INSUFFICIENT (<30 точек — анализ не запускался) отдаём бесплатно.
    UNCLEAR (поймали фейк — работа сделана) идёт через пейволл: вердикт-слово видно, разбор платный."""
    if paid or result.get("verdict") == "INSUFFICIENT":
        return result
    g = {k: result[k] for k in FREE_FIELDS if k in result}
    g["locked"] = True
    g["price_usd"] = PRICE_USD
    g["pay_ready"] = bool(NP_API_KEY)
    g["pay_card_ready"] = _paycm.cryptomus_enabled() or _paycard.card_enabled()   # карта: Cryptomus ИЛИ MoR
    return g


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, name):
        path = os.path.join(WEB, name)
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as f:
            self._send(200, f.read(), _CT.get(os.path.splitext(name)[1], "application/octet-stream"))

    def _raw(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_BODY:                 # не читаем гигантские тела в память
                return b""
            return self.rfile.read(n)
        except Exception:
            return b""

    def _client_ip(self) -> str:
        """Реальный IP клиента: за nginx/Cloudflare берём первый из X-Forwarded-For."""
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "?"

    def _too_big(self) -> bool:
        try:
            return int(self.headers.get("Content-Length", 0)) > MAX_BODY
        except Exception:
            return False

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/report":
            if not _rate_ok(self._client_ip()):
                return self._send(429, {"error": "too many requests"})
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            supplied = self.headers.get("X-Report-Key", "") or qs.get("key", [""])[0]
            # fail-closed: без заданного REPORT_KEY ручка ЗАКРЫТА — бизнес-метрики не утекают.
            if not REPORT_KEY or not hmac.compare_digest(supplied, REPORT_KEY):
                return self._send(403, {"error": "forbidden"})
            rep = stats_report()
            if qs.get("send", [""])[0] == "1":
                tg_send(rep)
            return self._send(200, {"report": rep, "metrics": _metrics(), "funnel": _funnel()})
        if p == "/api/ping":
            # Мост «рабочая сессия → владелец»: сессия шлёт строку в Telegram через сервер.
            # Защита: REPORT_KEY (fail-closed) + rate-limit.
            if not _rate_ok(self._client_ip()):
                return self._send(429, {"error": "too many requests"})
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            supplied = self.headers.get("X-Report-Key", "") or qs.get("key", [""])[0]
            if not REPORT_KEY or not hmac.compare_digest(supplied, REPORT_KEY):
                return self._send(403, {"error": "forbidden"})
            msg = (qs.get("msg", [""])[0] or "").strip()[:500]
            if not msg:
                return self._send(400, {"error": "empty msg"})
            safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tg_send("🛠 <b>Сессия Claude</b>\n" + safe)
            return self._send(200, {"ok": True})
        if p == "/api/badge.svg":
            # публичный SVG-бейдж «Validated by isitalpha» — вирусная петля (каждый показ тянет наш домен)
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            verdict = qs.get("verdict", ["UNCLEAR"])[0]
            try:
                pct = float(qs["pct"][0]) if qs.get("pct") else None
            except Exception:
                pct = None
            try:
                gn = int(qs["n"][0]) if qs.get("n") else None
            except Exception:
                gn = None
            svg = badge_svg(verdict, pct, gn).encode()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            return self.wfile.write(svg)
        if p == "/api/plans":
            return self._send(200, {"plans": _plans.ladder_public()})
        if p in ("/", "/index.html"):
            return self._file("landing.html")
        if p == "/validate":
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            src = qs.get("utm_source", [""])[0]
            # мониторинг/боты не должны загрязнять воронку живыми людьми
            ua = self.headers.get("User-Agent", "")
            is_probe = "healthcheck" in ua.lower() or "uptimerobot" in ua.lower()
            if src and not is_probe:        # заход с рекламной ссылки — засчитываем визит каналу
                _bump_visit(src)
            if not is_probe:
                _bump_step("land", src)     # пофазная воронка: приземление (даже direct/без utm)
            return self._file("validate.html")
        if p == "/report":
            return self._file("report.html")
        if p in ("/learn", "/learn/"):
            return self._file("learn/index.html")
        if p.startswith("/learn/"):
            slug = "".join(c for c in p[7:].strip("/") if c.isalnum() or c == "-")
            if slug and os.path.isfile(os.path.join(WEB, "learn", slug + ".html")):
                return self._file("learn/" + slug + ".html")
        # ЯВНЫЙ СПИСОК публичных файлов. Раньше здесь отдавался ЛЮБОЙ файл,
        # который лежит в web/ — то есть положить файл в папку означало
        # опубликовать его в интернете. Так наружу утекли внутренние страницы:
        # русский симулятор, русский лендинг и дашборд воронки, публично
        # показывавший «0 продаж, $0 выручка». Список закрывает класс проблемы:
        # новый служебный файл в web/ больше не станет публичным сам собой.
        safe = os.path.normpath(p).lstrip("/")
        if safe in PUBLIC_FILES and os.path.isfile(os.path.join(WEB, safe)):
            return self._file(safe)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        """Обёртка: любое необработанное исключение → честный 500 JSON, не обрыв связи.

        Без неё исключение внутри обработчика убивает соединение, nginx отдаёт
        502 Bad Gateway, и снаружи это неотличимо от «сервер лежит». Именно так
        выглядел баг с JSON-массивом в returns."""
        try:
            return self._do_post()
        except Exception as e:
            try:
                sys.stderr.write("POST %s failed: %r\n" % (self.path, e))
                return self._send(500, {"error": "internal error"})
            except Exception:
                return

    def _do_post(self):
        if self._too_big():                              # тело больше 1 MB — режем сразу
            return self._send(413, {"error": "payload too large"})
        # rate-limit на дорогие/абьюзабельные ручки (IPN/callback/unlock не лимитируем — HMAC/дёшево)
        if self.path in ("/api/validate", "/api/checkout") and not _rate_ok(self._client_ip()):
            return self._send(429, {"error": "too many requests", "retry_after": RL_WINDOW})
        if self.path == "/api/track":
            # анонимный beacon клиентских шагов воронки (validate_click, verdict_shown).
            # ТОЛЬКО step + src. Никакого PII/IP/тела строки — просто счётчик. Всегда 204.
            try:
                b = json.loads(self._raw() or b"{}")
            except Exception:
                b = {}
            step = str(b.get("step", "")).strip()
            src = str(b.get("src", "")).strip()
            # клиенту доверяем только «мягкие» шаги; жёсткие (validate_run/verdict_shown/paywall_view/pay_click/paid)
            # считает сервер сам — так их нельзя накрутить с фронта.
            # verdict_shown теперь бьётся на сервере при отдаче вердикта (надёжнее sendBeacon).
            if step in ("example_click", "validate_click"):
                _bump_step(step, src)
            return self._send(204, b"")

        if self.path == "/api/validate":
            try:
                body = json.loads(self._raw() or b"{}")
            except Exception:
                return self._send(400, {"error": "bad request"})
            rets = parse_returns_csv(body.get("returns", ""))
            if len(rets) > MAX_POINTS:                    # защита от гигантских рядов
                rets = rets[:MAX_POINTS]
            n_trials = int(body.get("n_trials", 10) or 10)
            n_trials = max(1, min(n_trials, 1000))        # ограничим диапазон испытаний
            period = str(body.get("period", "day")).strip().lower()   # день/неделя/месяц → правильная аннуализация
            ppy = {"day": 252, "week": 52, "month": 12, "quarter": 4}.get(period, 252)
            order = str(body.get("order", "")).strip()
            src = str(body.get("src", "")).strip()      # utm_source, проброшенный фронтом
            tier = str(body.get("tier", "")).strip().lower()   # "regime" → платный research-тир (approved-with-caveats)
            # SIM_UNLOCK=1 — локальный тест-стенд показывает полный отчёт без оплаты. В бою переменная не задана → обычный пейволл.
            paid = is_paid(order) or os.environ.get("SIM_UNLOCK") == "1"
            # regime-тир доступен только оплатившим; неоплаченным всегда строгий validate() (free-вердикт под пейволлом)
            if tier == "regime" and paid:
                result = regime_judge(rets, n_trials=n_trials, periods_per_year=ppy)
            else:
                result = validate(rets, n_trials=n_trials, periods_per_year=ppy)
            # считаем попытку (лид) только на СВЕЖий вердикт, не на повторный опрос оплаченного заказа
            if result.get("verdict") != "INSUFFICIENT" and not order:
                _bump_attempt(src)
                _bump_step("validate_run", src)     # воронка: сервер реально прогнал валидацию
                _bump_step("verdict_shown", src)    # серверный счёт надёжнее клиентского beacon
            gated = gate(result, paid)
            # серверный сигнал пейволла: неоплаченный locked-вердикт = человек упёрся в стену
            if gated.get("locked") and not order:
                _bump_step("paywall_view", src)
            return self._send(200, gated)

        if self.path == "/api/checkout":
            try:
                cbody = json.loads(self._raw() or b"{}")
            except Exception:
                cbody = {}
            coin = str(cbody.get("coin", "")).strip().lower()   # usdttrc20 / usdcmatic от кнопки, либо пусто
            src = str(cbody.get("src", "")).strip()              # utm_source для атрибуции продажи каналу
            _bump_step("pay_click", src)                         # воронка: нажал «Pay $…» (намерение оплатить)
            order_id = "isa_" + _secrets.token_hex(8)
            url = np_create_invoice(order_id, coin)
            if not url:
                return self._send(200, {"ok": False, "reason": "payment_not_configured"})
            _tag_order(order_id, src)
            return self._send(200, {"ok": True, "order": order_id, "invoice_url": url})

        if self.path == "/api/pay/card-start":
            # карта: генерим order → страница оплаты картой → фронт редиректит. Клиент платит картой.
            # Приоритет Cryptomus (card→USDT, RF, invoice с order_id для авто-разблокировки), иначе MoR/LS.
            try:
                cbody = json.loads(self._raw() or b"{}")
            except Exception:
                cbody = {}
            plan = (str(cbody.get("plan", "report")).strip().lower() or "report")
            src = str(cbody.get("src", "")).strip()
            order_id = "isa_" + _secrets.token_hex(8)
            url = None
            if _paycm.cryptomus_enabled():
                url = _paycm.create_invoice(
                    order_id, PRICE_USD, currency="USD",
                    callback_url=f"{SITE_URL}/api/pay/cryptomus",
                    return_url=f"{SITE_URL}/validate",
                    success_url=f"{SITE_URL}/validate?paid={order_id}")
            elif _paycard.card_enabled():
                url = _paycard.checkout_url_for(plan, order_id, site_url=SITE_URL)
            if not url:
                return self._send(200, {"ok": False, "reason": "card_not_configured"})
            _bump_step("pay_click", src)
            _tag_order(order_id, src)
            return self._send(200, {"ok": True, "order": order_id, "url": url})

        if self.path == "/api/pay/cryptomus":
            # вебхук Cryptomus: проверка md5-подписи → тот же путь разблокировки (_mark_paid)
            raw = self._raw()
            if not _paycm.verify_webhook(raw):
                return self._send(403, {"ok": False})
            try:
                d = json.loads(raw)
            except Exception:
                return self._send(400, {"ok": False})
            ev = _paycm.normalize_event(d)
            order = str(ev.get("order_id", "")).strip()
            if ev.get("paid") and order:
                _mark_paid(order)
                m = _record_sale(order)          # None если дубль вебхука (идемпотентность)
                if m is not None:
                    _bump_step("paid", m.get("order_src", {}).get(order, ""))
                    tg_send(f"💳 <b>Продажа (карта/Cryptomus)!</b> заказ {order}\n"
                            f"Всего продаж: <b>{m['sales']}</b> · выручка <b>${m['revenue']}</b>")
            return self._send(200, {"ok": True})

        if self.path == "/api/pay/callback":
            # вебхук MoR: проверяем HMAC-подпись → тот же путь разблокировки, что крипто (_mark_paid)
            raw = self._raw()
            sig = self.headers.get("X-Signature", "")
            if not _paycard.verify_signature(raw, sig):
                return self._send(403, {"ok": False})
            try:
                d = json.loads(raw)
            except Exception:
                return self._send(400, {"ok": False})
            ev = _paycard.normalize_event(d)
            order = str(ev.get("order_id", "")).strip()
            if ev.get("paid") and order:
                _mark_paid(order)
                m = _record_sale(order)          # None если дубль вебхука (идемпотентность)
                if m is not None:
                    _bump_step("paid", m.get("order_src", {}).get(order, ""))
                    tg_send(f"💳 <b>Продажа (карта)!</b> заказ {order}\n"
                            f"Всего продаж: <b>{m['sales']}</b> · выручка <b>${m['revenue']}</b>")
            return self._send(200, {"ok": True})

        if self.path == "/api/badge":
            # вернуть встраиваемые сниппеты бейджа (SVG + <img> + markdown) для «Validated by isitalpha»
            try:
                b = json.loads(self._raw() or b"{}")
            except Exception:
                b = {}
            verdict = str(b.get("verdict", "UNCLEAR")).strip()
            pct = b.get("percentile")
            gn = b.get("graveyard_n")
            try:
                pct = float(pct) if pct is not None else None
            except Exception:
                pct = None
            try:
                gn = int(gn) if gn is not None else None
            except Exception:
                gn = None
            return self._send(200, badge_embed_html(verdict, pct, gn, base_url=SITE_URL))

        if self.path == "/api/unlock":
            try:
                body = json.loads(self._raw() or b"{}")
            except Exception:
                body = {}
            return self._send(200, {"ok": is_paid(str(body.get("order", "")).strip())})

        if self.path == "/api/ipn":
            raw = self._raw()
            sig = self.headers.get("x-nowpayments-sig", "")
            if not np_ipn_valid(raw, sig):
                return self._send(403, {"ok": False})
            try:
                d = json.loads(raw)
            except Exception:
                return self._send(400, {"ok": False})
            status = d.get("payment_status")
            order = str(d.get("order_id", "")).strip()
            if status in ("finished", "confirmed") and order:
                _mark_paid(order)
                m = _record_sale(order)          # None если дубль вебхука
                if m is not None:
                    # воронка: оплата подтверждена. Источник — из карты атрибуции заказа (order_src).
                    _bump_step("paid", m.get("order_src", {}).get(order, ""))
                    tg_send(f"💰 <b>Продажа!</b> ${PRICE_USD} · заказ {order}\n"
                            f"Всего продаж: <b>{m['sales']}</b> · выручка <b>${m['revenue']}</b>")
                try:
                    pay_amt, actual = d.get("pay_amount"), d.get("actually_paid")
                    if actual and pay_amt and float(actual) > float(pay_amt) * 1.02:
                        tg_send(f"⚠️ Переплата по {order}: пришло {actual}, ждали {pay_amt}. Возможен возврат излишка.")
                except Exception:
                    pass
            elif status == "partially_paid" and order:
                tg_send(f"⚠️ Недоплата по {order} (partially_paid) — отчёт не открыт. Клиент мог ошибиться суммой.")
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main(port=8423):
    print("Honest Validator app: http://127.0.0.1:%d  (/validate, /report)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8423)
