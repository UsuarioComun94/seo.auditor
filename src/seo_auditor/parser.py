"""Extracción de datos SEO desde HTML, solo con la biblioteca estándar."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .urls import resolve

_REFRESH_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[;,]?\s*(?:url\s*=\s*)?['\"]?(.*?)['\"]?\s*$", re.IGNORECASE
)
_RESOURCE_TAGS = {"script": "src", "iframe": "src", "source": "src", "video": "src", "audio": "src", "embed": "src"}


@dataclass
class ParsedPage:
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str = ""
    canonical: str | None = None
    h1_count: int = 0
    images: list[dict] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    hreflang: list[tuple[str, str]] = field(default_factory=list)
    jsonld: list[str] = field(default_factory=list)
    refresh_url: str = ""


class _Extractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out = ParsedPage()
        self._in_title = False
        self._in_jsonld = False

    def _abs(self, href: str | None) -> str | None:
        return resolve(self.base, href) if href else None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        out = self.out
        if tag == "base" and a.get("href"):
            resolved = resolve(self.base, a["href"])
            if resolved:
                self.base = resolved
        elif tag == "title":
            if out.title is None:
                out.title = ""
            self._in_title = True
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description" and out.meta_description is None:
                out.meta_description = a.get("content", "")
            elif name == "robots":
                out.meta_robots = (out.meta_robots + " " + a.get("content", "")).strip()
            elif a.get("http-equiv", "").lower() == "refresh":
                m = _REFRESH_RE.match(a.get("content", ""))
                if m and m.group(2) and not out.refresh_url:
                    target = self._abs(m.group(2))
                    if target:
                        out.refresh_url = target
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            href = a.get("href")
            if "canonical" in rel and href and out.canonical is None:
                out.canonical = self._abs(href) or href
            elif "alternate" in rel and a.get("hreflang") and href:
                target = self._abs(href)
                if target:
                    out.hreflang.append((a["hreflang"], target))
            elif href and not {"canonical", "alternate", "dns-prefetch", "preconnect"} & set(rel):
                target = self._abs(href)
                if target:
                    out.resources.append(target)
        elif tag == "h1":
            out.h1_count += 1
        elif tag == "a":
            target = self._abs(a.get("href"))
            if target:
                out.links.append(target)
        elif tag == "img":
            src = self._abs(a.get("src"))
            if src:
                out.images.append({"src": src, "has_alt": "alt" in a})
                out.resources.append(src)
        elif tag in _RESOURCE_TAGS:
            target = self._abs(a.get(_RESOURCE_TAGS[tag]))
            if target:
                out.resources.append(target)
            if tag == "script" and a.get("type", "").lower() == "application/ld+json":
                self._in_jsonld = True
                out.jsonld.append("")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_title and self.out.title is not None:
            self.out.title += data
        if self._in_jsonld and self.out.jsonld:
            self.out.jsonld[-1] += data


def parse_html(html: str, base_url: str) -> ParsedPage:
    parser = _Extractor(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # HTML roto: nos quedamos con lo que se alcanzó a extraer
        pass
    page = parser.out
    if page.title is not None:
        page.title = " ".join(page.title.split())
    if page.meta_description is not None:
        page.meta_description = page.meta_description.strip()
    return page
