"""Modelos de datos del crawl y de los issues."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageRecord:
    url: str
    status: int = 0                      # 0 = error de red / sin respuesta
    error: str = ""
    content_type: str = ""
    response_ms: int = 0
    x_robots_tag: str = ""
    is_html: bool = False
    # Redirección saliente de esta URL (HTTP 3xx o meta refresh)
    redirect_to: str = ""
    redirect_kind: str = ""              # "http" | "meta"
    # Contenido (solo HTML)
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str = ""
    canonical: str | None = None
    h1_count: int = 0
    images: list[dict] = field(default_factory=list)   # {"src": abs_url, "has_alt": bool}
    links: list[str] = field(default_factory=list)     # absolutos, normalizados
    resources: list[str] = field(default_factory=list)
    hreflang: list[tuple[str, str]] = field(default_factory=list)
    jsonld: list[str] = field(default_factory=list)
    # Señales de riesgo (fase 5)
    hidden_text: str = ""
    anchors: list = field(default_factory=list)          # (href, texto, oculto)
    main_word_count: int = 0
    main_words: frozenset = field(default_factory=frozenset)
    # Comparación con el user-agent de Googlebot (solo own/client con compare_googlebot_ua)
    cloak: dict = field(default_factory=dict)            # {"similarity": float, "words": int, "title_user": str, "title_bot": str}
    # Contexto del crawl
    in_sitemap: bool = False
    depth: int = 0
    discovered_from: str = ""

    @property
    def noindex(self) -> bool:
        return "noindex" in f"{self.meta_robots} {self.x_robots_tag}".lower()

    @property
    def is_content_page(self) -> bool:
        """Página HTML que responde 200 y no redirige."""
        return self.status == 200 and self.is_html and not self.redirect_to

    @property
    def indexable(self) -> bool:
        return self.is_content_page and not self.noindex


@dataclass
class CrawlResult:
    name: str
    domain: str
    mode: str
    started_at: str = ""
    finished_at: str = ""
    pages: dict[str, PageRecord] = field(default_factory=dict)
    sitemap_urls: list[str] = field(default_factory=list)
    robots_url: str = ""
    robots_status: int = 0
    blocked_links: dict[str, set[str]] = field(default_factory=dict)  # url bloqueada -> páginas que la enlazan
    external: dict[str, int] = field(default_factory=dict)            # url externa -> status (0 = no responde)
    truncated: bool = False
    platform: str = ""                   # "" = no detectada
    notes: list[str] = field(default_factory=list)
    # Fase 4. status: "" = no se intentó | ok | parcial | no_disponible
    perf: list[dict] = field(default_factory=list)
    perf_status: str = ""
    gsc: dict = field(default_factory=dict)
    gsc_status: str = ""


@dataclass
class Issue:
    rule_id: str
    url: str
    severity: str
    category: str
    detail: str = ""
    target: str = ""
    hat: str = "white"
