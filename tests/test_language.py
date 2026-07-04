"""МЕТКА-СТОППЕР ЯЗЫКА: боевые EN-страницы НЕ должны содержать ВИДИМОГО русского текста.
Запуск: python3 tests/test_language.py  (часть чек-листа перед деплоем).

Контекст: аудитория продукта — англоязычная. Если ПОСЕТИТЕЛЬ видит «русский сайт» —
это АВТОПЕРЕВОД его браузера (Chrome/Яндекс на не-Apple), а НЕ наш баг: сервер отдаёт всем английский.
Проверяем ТОЛЬКО видимое: HTML-текст + строковые литералы JS (их могут вывести на экран).
Комментарии (<!-- -->, /* */, //) игнорируем — посетитель их не видит."""
import os, re, sys

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
PUBLIC_EN = ["landing.html", "validate.html", "report.html"]   # публичные английские страницы


def visible_text(s: str) -> str:
    """Оставляем только то, что видит посетитель: HTML-текст + строки JS. Комментарии/CSS выкидываем."""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)                      # HTML-комментарии
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.S | re.I)  # CSS — невидим
    def clean_js(m):                                                   # в <script> убираем комментарии, строки оставляем
        js = re.sub(r"/\*.*?\*/", "", m.group(0), flags=re.S)
        js = re.sub(r"(?m)(?<!:)//.*$", "", js)                       # // ... но не http://
        return js
    s = re.sub(r"<script[^>]*>.*?</script>", clean_js, s, flags=re.S | re.I)
    return s


def main():
    fails = []
    for f in PUBLIC_EN:
        p = os.path.join(WEB, f)
        if not os.path.isfile(p):
            print("• skip (нет файла):", f)
            continue
        cyr = re.findall(r"[А-Яа-яЁё]{2,}", visible_text(open(p, encoding="utf-8").read()))
        if cyr:
            print("❌ %-16s ВИДИМАЯ кириллица: %s" % (f, cyr[:10]))
            fails.append(f)
        else:
            print("✅ %-16s чисто — 0 видимого русского" % f)
    print("\nИТОГ:", "EN-страницы ЧИСТЫЕ ✅" if not fails else "🚨 УТЕЧКА РУССКОГО: %s — НЕ деплоить!" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
