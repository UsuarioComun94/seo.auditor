"""Benchmark entre sitios: porcentajes y promedios del crawl público, comparables sin importar el tamaño.

Todo sale de lo que cualquier visitante o bot puede ver (HTML, headers, robots.txt, sitemap), así que
se calcula igual para sitios propios, de clientes y de competencia. No usa datos privados.
"""

from __future__ import annotations

import statistics

from .models import CrawlResult

METRICS = (
    "paginas_html", "pct_title", "pct_meta_desc", "pct_h1_unico", "pct_canonical", "pct_schema_jsonld",
    "pct_imagenes_con_alt", "pct_indexables", "pct_en_sitemap", "pct_con_hreflang",
    "profundidad_media", "profundidad_max", "ms_mediana", "ms_p90", "enlaces_internos_medios",
    "pct_errores_4xx_5xx", "tiene_robots", "tiene_sitemap", "truncado",
    "perf_puntaje_movil", "lcp_ms_lab", "cls_lab", "tbt_ms_lab", "ttfb_ms_lab", "lcp_ms_campo", "inp_ms_campo", "cls_campo",
)


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def compute_benchmark(result: CrawlResult) -> dict:
    """Métricas de un crawl. Un valor None (celda vacía) significa "no medible", nunca 0."""
    pages = list(result.pages.values())
    html = [p for p in pages if p.is_content_page]
    n = len(html)
    imgs = [i for p in html for i in p.images]
    times = sorted(p.response_ms for p in pages if p.status and p.response_ms)
    p90 = times[min(len(times) - 1, int(0.9 * len(times)))] if times else None
    errors = sum(1 for p in pages if p.status >= 400 or p.status == 0)
    home = next((r for r in result.perf if not r.get("error")), None)      # la home: primera medición
    field = (home or {}).get("field") or {}
    perf = {
        "perf_puntaje_movil": (home or {}).get("score"), "lcp_ms_lab": (home or {}).get("lcp_ms"),
        "cls_lab": (home or {}).get("cls"), "tbt_ms_lab": (home or {}).get("tbt_ms"),
        "ttfb_ms_lab": (home or {}).get("ttfb_ms"), "lcp_ms_campo": field.get("lcp_ms"),
        "inp_ms_campo": field.get("inp_ms"), "cls_campo": field.get("cls"),
    }
    perf = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in perf.items()}
    return {
        **perf,
        "paginas_html": n,
        "pct_title": _pct(sum(1 for p in html if p.title), n),
        "pct_meta_desc": _pct(sum(1 for p in html if p.meta_description), n),
        "pct_h1_unico": _pct(sum(1 for p in html if p.h1_count == 1), n),
        "pct_canonical": _pct(sum(1 for p in html if p.canonical), n),
        "pct_schema_jsonld": _pct(sum(1 for p in html if p.jsonld), n),
        "pct_imagenes_con_alt": _pct(sum(1 for i in imgs if i["has_alt"]), len(imgs)),
        "pct_indexables": _pct(sum(1 for p in html if p.indexable), n),
        "pct_en_sitemap": _pct(sum(1 for p in html if p.in_sitemap), n) if result.sitemap_urls else None,
        "pct_con_hreflang": _pct(sum(1 for p in html if p.hreflang), n),
        "profundidad_media": round(statistics.mean(p.depth for p in html), 2) if html else None,
        "profundidad_max": max((p.depth for p in html), default=None),
        "ms_mediana": int(statistics.median(times)) if times else None,
        "ms_p90": p90,
        "enlaces_internos_medios": round(statistics.mean(len(p.links) for p in html), 1) if html else None,
        "pct_errores_4xx_5xx": _pct(errors, len(pages)),
        "tiene_robots": result.robots_status == 200,
        "tiene_sitemap": bool(result.sitemap_urls),
        "truncado": result.truncated,
    }
