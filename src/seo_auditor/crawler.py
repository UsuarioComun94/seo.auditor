"""Crawler: robots.txt, sitemap, BFS por enlaces internos, redirecciones y enlaces externos."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit

# defusedxml: los sitemaps de sitios ajenos son entrada no confiable (XML bombs, entidades externas)
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .config import ClientConfig
from .fetcher import DEFAULT_USER_AGENT, Fetcher, is_public_host
from .models import CrawlResult, PageRecord
from .parser import parse_html
from .render import RenderUnavailable, Renderer
from .platform import detect_platform
from .urls import Scope, normalize_url, resolve

MAX_EXTERNAL_CHECKS = 200
MAX_SITEMAPS = 20


class CrawlAbort(RuntimeError):
    """El crawl no puede ni debe continuar (por ejemplo, robots.txt inaccesible en modo competitor)."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Crawler:
    def __init__(self, cfg: ClientConfig, fetcher: Fetcher | None = None, log=lambda msg: None,
                 renderer: Renderer | None = None):
        self.cfg = cfg
        self.scope = Scope(cfg.domain)
        self.fetcher = fetcher or Fetcher(cfg.crawl.user_agent, cfg.crawl.delay_seconds)
        self.log = log
        self.renderer = renderer if renderer is not None else (
            Renderer(cfg.crawl.user_agent or DEFAULT_USER_AGENT) if cfg.crawl.render_js else None)
        self.rendered_pages = 0
        self.render_failures = 0
        self.robots = RobotFileParser()
        self.robots_loaded = False
        self.result = CrawlResult(name=cfg.name, domain=cfg.domain, mode=cfg.mode)

    # ---------- robots.txt ----------
    def _load_robots(self) -> None:
        url = self.cfg.crawl.robots_url or f"{self.scope.origin}/robots.txt"
        self.result.robots_url = url
        res = self.fetcher.get(url)
        self.result.robots_status = res.status
        if res.status == 200 and res.text is not None:
            self.robots.parse(res.text.splitlines())
            self.robots_loaded = True
            return
        unreachable = res.status == 0 or res.status >= 500
        if unreachable and self.cfg.mode == "competitor":
            # Conservador: sin robots.txt confiable no se rastrea un sitio ajeno.
            raise CrawlAbort(f"robots.txt no disponible ({res.status or res.error}); no se rastrea un sitio ajeno")
        if unreachable:
            self.result.notes.append(f"robots.txt no disponible ({res.status or res.error}); se asume todo permitido")

    def _blocked(self, url: str) -> bool:
        return self.robots_loaded and not self.robots.can_fetch(self.fetcher.robots_token, url)

    # ---------- sitemap ----------
    def _sitemap_candidates(self) -> list[str]:
        found = list(self.robots.site_maps() or []) if self.robots_loaded else []
        if not found:
            found = [self.scope.origin + self.scope.prefix + "sitemap.xml"]
        return [normalize_url(u) for u in found]

    def _read_sitemaps(self) -> list[str]:
        urls: list[str] = []
        queue = deque(self._sitemap_candidates())
        seen: set[str] = set()
        while queue and len(seen) < MAX_SITEMAPS:
            sm = queue.popleft()
            if sm in seen:
                continue
            seen.add(sm)
            res = self.fetcher.get(sm)
            if res.status != 200 or not res.text:
                self.result.notes.append(f"sitemap no disponible: {sm} ({res.status or res.error})")
                continue
            try:
                root = ET.fromstring(res.text)
            except (ET.ParseError, DefusedXmlException):
                self.result.notes.append(f"sitemap inválido o no permitido (XML): {sm}")
                continue
            is_index = root.tag.lower().endswith("sitemapindex")
            for loc in root.iter():
                if loc.tag.lower().endswith("}loc") or loc.tag.lower() == "loc":
                    value = (loc.text or "").strip()
                    if not value:
                        continue
                    target = normalize_url(value)
                    if is_index:
                        queue.append(target)
                    else:
                        urls.append(target)
        in_scope = [u for u in dict.fromkeys(urls) if self.scope.contains(u)]
        dropped = len(set(urls)) - len(in_scope)
        if dropped:
            self.result.notes.append(f"{dropped} URLs del sitemap fuera del alcance del dominio (ignoradas)")
        return in_scope

    # ---------- fetch de una página ----------
    def _fetch_page(self, url: str, depth: int, discovered_from: str) -> PageRecord:
        rec = PageRecord(url=url, depth=depth, discovered_from=discovered_from)
        res = self.fetcher.get(url)
        rec.status = res.status
        rec.error = res.error
        rec.response_ms = res.elapsed_ms
        rec.content_type = res.headers.get("content-type", "")
        rec.x_robots_tag = res.headers.get("x-robots-tag", "")
        if 300 <= res.status < 400 and res.headers.get("location"):
            target = resolve(url, res.headers["location"])
            if target:
                rec.redirect_to, rec.redirect_kind = target, "http"
        ctype = rec.content_type.lower()
        rec.is_html = res.text is not None and ("html" in ctype)
        if url == self.scope.root and res.status == 200 and res.text:
            self.result.platform = detect_platform(url, res.headers, res.text)
        html = res.text
        if self.renderer and rec.is_html and res.status == 200 and res.text:
            self.fetcher._wait()                 # el render es otro pedido: misma pausa de cortesía
            self.fetcher.requests_made += 1
            try:
                rendered = self.renderer.render(url)
            except RenderUnavailable as exc:
                self.result.notes.append(f"render_js pedido pero no disponible: {exc}; se usa el HTML crudo")
                self.renderer = None
                rendered = None
            if rendered:
                html = rendered
                self.rendered_pages += 1
            elif self.renderer:
                self.render_failures += 1
        if rec.is_html and res.status == 200 and html:
            parsed = parse_html(html, url)
            rec.title = parsed.title
            rec.meta_description = parsed.meta_description
            rec.meta_robots = parsed.meta_robots
            rec.canonical = parsed.canonical
            rec.h1_count = parsed.h1_count
            rec.images = parsed.images
            rec.links = parsed.links
            rec.resources = parsed.resources
            rec.hreflang = parsed.hreflang
            rec.jsonld = parsed.jsonld
            if parsed.refresh_url:
                rec.redirect_to, rec.redirect_kind = parsed.refresh_url, "meta"
        return rec

    # ---------- crawl principal ----------
    def run(self) -> CrawlResult:
        r = self.result
        r.started_at = _now()
        respect = self.cfg.crawl.respect_robots
        max_urls = self.cfg.crawl.max_urls

        self._load_robots()
        sitemap_urls = self._read_sitemaps()
        r.sitemap_urls = sitemap_urls
        sitemap_set = set(sitemap_urls)

        queue: deque[tuple[str, int, str]] = deque()
        queued: set[str] = set()

        def enqueue(url: str, depth: int, source: str) -> None:
            if url in queued or not self.scope.contains(url):
                return
            queued.add(url)
            queue.append((url, depth, source))

        enqueue(self.scope.root, 0, "")
        for u in sitemap_urls:
            enqueue(u, 0, "sitemap")

        while queue:
            url, depth, source = queue.popleft()
            if self._blocked(url):
                r.blocked_links.setdefault(url, set())
                if respect:
                    if source and source != "sitemap":
                        r.blocked_links[url].add(source)
                    continue
            if len(r.pages) >= max_urls:
                r.truncated = True
                break
            rec = self._fetch_page(url, depth, source)
            rec.in_sitemap = url in sitemap_set
            r.pages[url] = rec
            self.log(f"[{len(r.pages)}] {rec.status or 'ERR'} {url}")

            for link in rec.links:
                if self.scope.contains(link):
                    if self._blocked(link):
                        r.blocked_links.setdefault(link, set()).add(url)
                        if respect:
                            continue
                    enqueue(link, depth + 1, url)
            if rec.canonical:
                canon = normalize_url(rec.canonical)
                if self.scope.contains(canon):
                    enqueue(canon, depth + 1, url)
            if rec.redirect_to and self.scope.contains(rec.redirect_to):
                enqueue(rec.redirect_to, depth + 1, url)

        if self.renderer:
            self.renderer.close()
            r.notes.append(f"JavaScript renderizado en {self.rendered_pages} páginas"
                           + (f" ({self.render_failures} fallaron y usaron el HTML crudo)" if self.render_failures else ""))
        if self.cfg.mode != "competitor":
            self._check_externals()
        r.finished_at = _now()
        return r

    # ---------- enlaces externos (solo own/client) ----------
    def _check_externals(self) -> None:
        r = self.result
        externals: list[str] = []
        for rec in r.pages.values():
            for link in rec.links:
                if not self.scope.same_host(link) and link not in externals:
                    externals.append(link)
        if len(externals) > MAX_EXTERNAL_CHECKS:
            r.notes.append(f"{len(externals)} enlaces externos; se verificaron los primeros {MAX_EXTERNAL_CHECKS}")
            externals = externals[:MAX_EXTERNAL_CHECKS]
        for link in externals:
            host = urlsplit(link).hostname or ""
            if not is_public_host(host):
                r.external[link] = 0  # no resuelve o apunta a una red privada: no se consulta
                continue
            res = self.fetcher.get(link, read_body=False)
            r.external[link] = res.status
