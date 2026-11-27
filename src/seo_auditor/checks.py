"""Reglas de la fase 1. Cada regla usa un id de rules/rules.yaml."""

from __future__ import annotations

import json
from collections import defaultdict

from . import risk
from .models import CrawlResult, Issue, PageRecord
from .rules import Rule
from .urls import Scope, canon_key, normalize_url

MAX_REDIRECT_HOPS = 10

RECOMMENDATIONS = {
    "TECH-001": "Corregir o quitar el enlace, o redirigir la URL rota (301) a su equivalente más cercano.",
    "TECH-002": "Actualizar o quitar el enlace saliente roto.",
    "TECH-003": "Apuntar el enlace y la redirección directamente a la URL final (una sola redirección).",
    "TECH-004": "Romper el bucle: definir un destino final que responda 200.",
    "TECH-005": "Si la página debe indexarse, quitar noindex; si no, sacarla del sitemap.",
    "TECH-006": "Dejar en el sitemap solo URLs que respondan 200 e indexables.",
    "TECH-008": "Hacer que el canonical apunte a una URL que responda 200 (idealmente la propia página).",
    "TECH-009": "Verificar que el canonical sea intencional; si es error de plantilla, apuntar a la propia URL.",
    "TECH-010": "O se permite en robots.txt, o se deja de enlazar internamente.",
    "TECH-011": "Servir el recurso o enlace por HTTPS.",
    "TECH-007": "Enlazar la página desde la navegación o desde contenido relacionado, o sacarla del sitemap si no debe indexarse.",
    "SCH-001": "Corregir la sintaxis del JSON-LD (coma final, comillas, llaves) y validar el resultado.",
    "INT-001": "Agregar en la página alternativa el hreflang de retorno hacia esta URL.",
    "ONP-001": "Agregar un title único y descriptivo.",
    "ONP-002": "Dar a cada URL un title propio.",
    "ONP-003": "Agregar una meta description única que resuma la página.",
    "ONP-004": "Agregar un H1 que describa el tema de la página.",
    "ONP-005": "Dejar un único H1 y usar H2/H3 para el resto.",
    "ONP-006": "Agregar un atributo alt descriptivo (o alt vacío si la imagen es decorativa).",
}


class _Emitter:
    def __init__(self, rules: dict[str, Rule], mode: str):
        self.rules = rules
        self.mode = mode
        self.issues: list[Issue] = []
        self._seen: set[tuple[str, str, str]] = set()

    def add(self, rule_id: str, url: str, detail: str = "", target: str = "") -> None:
        rule = self.rules[rule_id]
        if self.mode not in rule.modes:
            return
        key = (rule_id, url, target)
        if key in self._seen:
            return
        self._seen.add(key)
        self.issues.append(Issue(rule_id=rule_id, url=url, severity=rule.severity,
                                 category=rule.category, detail=detail, target=target, hat=rule.hat))


def follow_redirects(pages: dict[str, PageRecord], start: str) -> tuple[list[str], str, bool]:
    """Recorre la cadena de redirecciones desde `start`. Devuelve (saltos, url_final, hay_bucle)."""
    hops: list[str] = []
    seen = {start}
    current = start
    while True:
        rec = pages.get(current)
        if rec is None or not rec.redirect_to:
            return hops, current, False
        nxt = normalize_url(rec.redirect_to)
        hops.append(nxt)
        if nxt in seen:
            return hops, nxt, True
        if len(hops) >= MAX_REDIRECT_HOPS:
            return hops, nxt, False
        seen.add(nxt)
        current = nxt


def _is_alias(p: PageRecord, pages: dict[str, PageRecord]) -> bool:
    """Variante de otra URL ya rastreada (p. ej. /index.html frente a /) que declara a esa otra como canonical.

    Es la misma página, no otra: no se cuentan dos veces sus issues. Sin canonical no hay alias.
    """
    if not p.is_content_page or not p.canonical:
        return False
    canon = normalize_url(p.canonical)
    return canon != p.url and canon in pages and canon_key(canon) == canon_key(p.url)


def _is_error(rec: PageRecord) -> bool:
    return rec.status == 0 or rec.status >= 400


def run_checks(result: CrawlResult, rules: dict[str, Rule], scope: Scope | None = None) -> list[Issue]:
    scope = scope or Scope(result.domain)
    em = _Emitter(rules, result.mode)
    pages = result.pages

    redirect_targets = {normalize_url(p.redirect_to) for p in pages.values() if p.redirect_to}
    covered: set[str] = set()  # URLs ya recorridas desde el inicio de alguna cadena

    # Enlaces entrantes por URL canónica-equivalente (/ e /index.html cuentan como la misma)
    inlinks: dict[str, set[str]] = defaultdict(set)
    for q in pages.values():
        if q.status == 200:
            for link in q.links:
                if canon_key(link) != canon_key(q.url):
                    inlinks[canon_key(link)].add(q.url)
        if q.redirect_to and canon_key(q.redirect_to) != canon_key(q.url):
            inlinks[canon_key(q.redirect_to)].add(q.url)

    for p in pages.values():
        alias = _is_alias(p, pages)

        # ---------- Técnico ----------
        if p.status == 200 and not alias:
            for link in dict.fromkeys(p.links):
                if scope.contains(link):
                    t = pages.get(link)
                    if t is not None and _is_error(t):
                        em.add("TECH-001", p.url, f"enlace a {link} responde {t.status or 'sin respuesta'}", link)
                elif not scope.same_host(link):
                    status = result.external.get(link)
                    if status is not None and (status == 0 or status >= 400):
                        em.add("TECH-002", p.url, f"enlace externo {link} responde {status or 'sin respuesta'}", link)

        if p.redirect_to and p.url not in redirect_targets:
            hops, final, loop = follow_redirects(pages, p.url)
            covered.update([p.url] + hops)
            if loop:
                em.add("TECH-004", p.url, "bucle de redirecciones: " + " → ".join([p.url] + hops), final)
            elif len(hops) >= 2:
                em.add("TECH-003", p.url, f"{len(hops)} redirecciones: " + " → ".join([p.url] + hops), final)

        if p.in_sitemap and p.status == 200 and p.noindex:
            em.add("TECH-005", p.url, "está en el sitemap pero tiene noindex")

        if p.is_content_page and p.canonical:
            canon = normalize_url(p.canonical)
            t = pages.get(canon)
            if t is not None:
                if _is_error(t) or t.redirect_to:
                    why = f"responde {t.status}" if _is_error(t) else f"redirige a {t.redirect_to}"
                    em.add("TECH-008", p.url, f"canonical {canon} {why}", canon)
                elif t.indexable and canon_key(canon) != canon_key(p.url):
                    em.add("TECH-009", p.url, f"canonical apunta a otra URL indexable: {canon}", canon)

        if p.url.startswith("https://") and p.is_content_page:
            for res in dict.fromkeys(p.resources):
                if res.startswith("http://"):
                    em.add("TECH-011", p.url, f"recurso por HTTP en página HTTPS: {res}", res)
            for link in dict.fromkeys(p.links):
                if link.startswith("http://") and scope.same_host(link):
                    em.add("TECH-011", p.url, f"enlace interno por HTTP: {link}", link)

        # ---------- On-page ----------
        if p.is_content_page and not alias:
            if p.title is None or not p.title.strip():
                em.add("ONP-001", p.url, "sin title" if p.title is None else "title vacío")
            if p.h1_count > 1:
                em.add("ONP-005", p.url, f"{p.h1_count} H1")
            for img in p.images:
                if not img["has_alt"]:
                    em.add("ONP-006", p.url, f"imagen sin alt: {img['src']}", img["src"])
            for n, block in enumerate(p.jsonld, 1):
                try:
                    if not block.strip():
                        raise ValueError("bloque vacío")
                    json.loads(block)
                except ValueError as exc:  # JSONDecodeError es subclase de ValueError
                    em.add("SCH-001", p.url, f"JSON-LD #{n} inválido: {str(exc)[:120]}", f"jsonld-{n}")
        if p.indexable and not alias:
            if not (p.meta_description or "").strip():
                em.add("ONP-003", p.url, "sin meta description")
            if p.h1_count == 0:
                em.add("ONP-004", p.url, "sin H1")

    # Bucles puros (A→B→A): todos sus miembros son destino de otro, así que ninguno es "inicio de cadena".
    reported_cycles: set[frozenset] = set()
    for p in pages.values():
        if p.redirect_to and p.url not in covered:
            hops, final, loop = follow_redirects(pages, p.url)
            covered.update([p.url] + hops)
            if loop:
                members = frozenset([p.url] + hops)
                if members not in reported_cycles:
                    reported_cycles.add(members)
                    head = min(members)
                    em.add("TECH-004", head, "bucle de redirecciones: " + " → ".join([p.url] + hops), final)

    # Huérfanas: en el sitemap pero sin ningún enlace interno. Con crawl truncado faltan datos de
    # enlaces entrantes, así que la regla se omite para no generar falsos positivos.
    if not result.truncated:
        root_key = canon_key(scope.root)
        for url in result.sitemap_urls:
            p = pages.get(url)
            if p is None or not p.is_content_page or _is_alias(p, pages) or canon_key(url) == root_key:
                continue
            if not inlinks.get(canon_key(url)):
                em.add("TECH-007", url, "está en el sitemap pero ninguna página rastreada la enlaza")

    # Hreflang sin enlace de retorno
    for p in pages.values():
        if not p.is_content_page or _is_alias(p, pages):
            continue
        for lang, target in p.hreflang:
            t_url = normalize_url(target)
            if canon_key(t_url) == canon_key(p.url):
                continue  # auto-referencia
            tp = pages.get(t_url)
            if tp is None or not tp.is_content_page:
                continue
            back = {canon_key(h) for _, h in tp.hreflang}
            if canon_key(p.url) not in back:
                em.add("INT-001", p.url, f"hreflang {lang} → {t_url}, que no declara el retorno", t_url)

    # Sitemap con URLs que no sirven
    for url in result.sitemap_urls:
        p = pages.get(url)
        if p is None:
            continue
        if _is_error(p):
            em.add("TECH-006", url, f"URL del sitemap responde {p.status or 'sin respuesta'}")
        elif p.redirect_to:
            em.add("TECH-006", url, f"URL del sitemap redirige a {p.redirect_to}", p.redirect_to)

    # Bloqueadas por robots.txt pero enlazadas
    for blocked, sources in result.blocked_links.items():
        if sources:
            em.add("TECH-010", blocked, f"bloqueada por robots.txt y enlazada desde {len(sources)} página(s)")

    # Títulos duplicados entre páginas indexables
    by_title: dict[str, list[str]] = defaultdict(list)
    for p in pages.values():
        if p.indexable and p.title and p.title.strip() and not _is_alias(p, pages):
            by_title[p.title.strip().casefold()].append(p.url)
    for urls in by_title.values():
        if len(urls) > 1:
            for u in urls:
                em.add("ONP-002", u, f"title repetido en {len(urls)} URLs")

    # ---------- Señales de riesgo (fase 5): solo detección ----------
    own_host = risk._host(result.domain)
    for p in pages.values():
        if not p.is_content_page or _is_alias(p, pages):
            continue
        hit, detail = risk.hidden_text_signal(p)
        if hit:
            em.add("RSK-001", p.url, detail)
        hit, detail, target = risk.hidden_links_signal(p, own_host)
        if hit:
            em.add("RSK-002", p.url, detail, target)
        for host, why in risk.spam_links(p, own_host):
            em.add("RSK-004", p.url, why, host)
        sim = p.cloak.get("similarity")
        if sim is not None and sim < risk.CLOAK_MAX_SIMILARITY:
            em.add("RSK-003", p.url, f"similitud {sim:.2f} entre usuario y Googlebot"
                   + (f"; title distinto: {p.cloak.get('title_bot', '')!r}" if p.cloak.get("title_user") != p.cloak.get("title_bot") else ""))
    for directory, cluster in risk.doorway_clusters([p for p in pages.values() if not _is_alias(p, pages)]):
        first = sorted(cluster, key=lambda x: x.url)[0]
        em.add("RSK-005", first.url, f"{len(cluster)} páginas casi idénticas en {directory}", directory)

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    em.issues.sort(key=lambda i: (order.get(i.severity, 9), i.rule_id, i.url, i.target))
    return em.issues
