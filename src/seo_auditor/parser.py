"""Extracción de datos SEO desde HTML, solo con la biblioteca estándar."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .urls import resolve

_REFRESH_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[;,]?\s*(?:url\s*=\s*)?['\"]?(.*?)['\"]?\s*$", re.IGNORECASE
)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_SKIP_TEXT = {"script", "style", "noscript", "template", "head", "title"}
_BOILERPLATE = {"nav", "header", "footer", "aside"}
_WORD_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
# Estilos en línea que ocultan contenido a las personas (señal, no prueba: los menús y modales también lo usan)
_HIDING_STYLE_RE = re.compile(
    r"display:none|visibility:hidden|font-size:0(?![\d.])|opacity:0(?![\d.])|text-indent:-\d{3,}"
    r"|(?:left|top|right|bottom):-\d{3,}|clip:rect\(0|(?:width|height):0(?:px)?;[^\"]*overflow:hidden"
    r"|overflow:hidden;[^\"]*(?:width|height):0(?:px)?(?![\d.])")
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
    # Señales de riesgo (fase 5). Solo se ve el CSS en línea y el atributo hidden: el CSS externo no se evalúa.
    hidden_text: str = ""
    anchors: list = field(default_factory=list)      # (href absoluto, texto, oculto)
    main_words: list = field(default_factory=list)   # texto visible principal (sin nav/header/footer/aside)


def hides_content(style: str) -> bool:
    return bool(_HIDING_STYLE_RE.search("".join((style or "").lower().split())))


class _Extractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out = ParsedPage()
        self._in_title = False
        self._in_jsonld = False
        self._stack: list[tuple[str, bool, bool, bool]] = []   # (tag, oculto, salta texto, boilerplate)
        self._anchor: list | None = None                         # [href, [texto], oculto] del <a> abierto
        self._hidden_parts: list[str] = []

    def _abs(self, href: str | None) -> str | None:
        return resolve(self.base, href) if href else None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        out = self.out
        if tag not in _VOID:
            parent = self._stack[-1] if self._stack else ("", False, False, False)
            self._stack.append((tag,
                                parent[1] or "hidden" in a or hides_content(a.get("style", "")),
                                parent[2] or tag in _SKIP_TEXT,
                                parent[3] or tag in _BOILERPLATE))
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
                self._anchor = [target, [], self._stack[-1][1]]
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
        if tag == "a" and self._anchor is not None:
            href, parts, hidden = self._anchor
            self.out.anchors.append((href, " ".join(" ".join(parts).split())[:120], hidden))
            self._anchor = None
        for i in range(len(self._stack) - 1, -1, -1):      # HTML roto: se cierra hasta la etiqueta que coincide
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._stack and not self._stack[-1][2]:
            _, hidden, _, boiler = self._stack[-1]
            if self._anchor is not None:
                self._anchor[1].append(data)
            if hidden:
                self._hidden_parts.append(data)
            elif not boiler:
                self.out.main_words.extend(w.lower() for w in _WORD_RE.findall(data))
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
    page.hidden_text = " ".join(" ".join(parser._hidden_parts).split())
    if page.title is not None:
        page.title = " ".join(page.title.split())
    if page.meta_description is not None:
        page.meta_description = page.meta_description.strip()
    return page
