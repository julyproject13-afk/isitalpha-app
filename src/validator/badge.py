"""Shareable «Validated by isitalpha» badge — вирусная петля (фишка №3 стратегии).

Отдаёт встраиваемый SVG-бейдж с вердиктом + перцентилем. Клиент постит его (в блог/твиттер/
резюме стратегии) → бесплатный брендовый трафик обратно на isitalpha.com.

Честность: бейдж показывает ТОЛЬКО реально выданный вердикт-слово и перцентиль, никаких обещаний.
Чистый stdlib, без зависимостей — SVG собирается строкой, легко кэшировать/встраивать.
"""
from __future__ import annotations

from typing import Dict, Optional

SITE = "isitalpha.com"

# цвет по вердикту (совпадает с UI-палитрой сайта)
_COLORS = {
    "REAL":              ("#0e1a15", "#62c98a", "REAL EDGE"),
    "REGIME-CONDITIONAL": ("#1c1508", "#e3b95e", "REGIME-CONDITIONAL"),
    "BORDERLINE":        ("#1c1508", "#e3b95e", "BORDERLINE"),
    "SELF-DECEPTION":    ("#1c1010", "#e08a82", "SELF-DECEPTION"),
    "DEAD":              ("#1c1010", "#e08a82", "DEAD"),
    "UNCLEAR":           ("#141821", "#8b94a3", "UNCLEAR"),
    "INSUFFICIENT":      ("#141821", "#8b94a3", "INSUFFICIENT"),
}


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def badge_svg(verdict: str, percentile: Optional[float] = None,
              graveyard_n: Optional[int] = None, width: int = 320) -> str:
    """Собрать SVG-бейдж «Validated by isitalpha» под данный вердикт.

    verdict     — вердикт-слово (REAL / REGIME-CONDITIONAL / SELF-DECEPTION / …)
    percentile  — «бьёт X% кладбища» (опц.); показываем, если есть и вердикт содержательный
    graveyard_n — размер кладбища (для подписи), опц.
    """
    v = str(verdict or "").upper()
    bg, accent, label = _COLORS.get(v, ("#141821", "#8b94a3", _esc(v) or "VERDICT"))
    h = 96
    show_pct = (percentile is not None and v in ("REAL", "REGIME-CONDITIONAL", "BORDERLINE"))
    sub = ""
    if show_pct:
        n_txt = ("{:,}".format(int(graveyard_n))).replace(",", ",") if graveyard_n else "the graveyard"
        sub = ("<text x='16' y='78' fill='#c4ccd6' font-family='Inter,Arial,sans-serif' "
               "font-size='11'>Beats {pct}% of {n}</text>").format(pct=percentile, n=_esc(n_txt))
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}' "
        "role='img' aria-label='Validated by isitalpha — {label}'>"
        "<rect width='{w}' height='{h}' rx='14' fill='{bg}' stroke='{accent}' stroke-opacity='0.5'/>"
        "<g transform='translate(16,20)'>"
        "<path d='M0 14 h5 l3 -10 l4 20 l3 -14 h5' fill='none' stroke='{accent}' stroke-width='2.2' "
        "stroke-linecap='round' stroke-linejoin='round'/></g>"
        "<text x='48' y='30' fill='#f3f5f8' font-family='Inter,Arial,sans-serif' font-size='13' "
        "font-weight='700'>Validated by isitalpha</text>"
        "<text x='16' y='58' fill='{accent}' font-family='Inter,Arial,sans-serif' font-size='19' "
        "font-weight='800' letter-spacing='0.5'>{label}</text>"
        "{sub}"
        "<text x='{wr}' y='20' text-anchor='end' fill='#69727f' "
        "font-family='Inter,Arial,sans-serif' font-size='10'>{site}</text>"
        "</svg>"
    ).format(w=width, h=h, bg=bg, accent=accent, label=label, sub=sub, wr=width - 14, site=SITE)


def badge_embed_html(verdict: str, percentile: Optional[float] = None,
                     graveyard_n: Optional[int] = None, base_url: str = "https://isitalpha.com") -> Dict[str, str]:
    """Готовые сниппеты для встраивания (что клиент копирует, чтобы запостить бейдж).

    Возвращает dict: raw SVG, <img>-снипет (ссылается на /api/badge.svg), и markdown-вариант.
    Ссылка на бейдж-эндпоинт → каждый показ бейджа тянет наш домен = брендовый трафик.
    """
    import urllib.parse
    q = {"verdict": verdict}
    if percentile is not None:
        q["pct"] = percentile
    if graveyard_n is not None:
        q["n"] = graveyard_n
    url = base_url.rstrip("/") + "/api/badge.svg?" + urllib.parse.urlencode(q)
    alt = "Validated by isitalpha — %s" % _esc(str(verdict))
    img = '<a href="%s" target="_blank" rel="noopener"><img src="%s" alt="%s" width="320" height="96"></a>' % (
        base_url, url, alt)
    md = "[![%s](%s)](%s)" % (alt, url, base_url)
    return {"svg": badge_svg(verdict, percentile, graveyard_n), "img_html": img,
            "markdown": md, "badge_url": url}
