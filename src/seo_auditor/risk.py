"""Señales de riesgo grey/black hat (fase 5). SOLO DETECCIÓN: el auditor nunca ejecuta estas técnicas.

Son señales, no veredictos. Cada regla tiene umbrales conservadores para no marcar patrones legítimos
(menús ocultos, modales, redes sociales en el pie). Limitaciones conocidas:
- RSK-001/002 ven el CSS en línea y el atributo `hidden`, no hojas de estilo externas.
- RSK-004 usa una lista corta de patrones; no es una base de reputación de dominios.
- RSK-005 compara el texto principal (sin nav/header/footer/aside) por directorio.
"""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from .models import PageRecord

# --- RSK-001
HIDDEN_MIN_WORDS = 20
HIDDEN_MIN_REPEAT = 0.4          # 1 - únicas/total: relleno de keywords repite mucho
# --- RSK-002
HIDDEN_EXT_LINKS_MIN = 3
SAFE_HOSTS = ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
              "youtu.be", "tiktok.com", "wa.me", "whatsapp.com", "pinterest.com", "google.com", "goo.gl",
              "maps.app.goo.gl", "t.me", "github.com", "spotify.com", "apple.com")
# --- RSK-003
CLOAK_MIN_WORDS = 30
CLOAK_MAX_SIMILARITY = 0.5
# --- RSK-004
SPAM_RE = re.compile(
    r"casino|poker|betting|apuestas|viagra|cialis|porn|xxx|payday|pastillas|replica|escort|pharma|"
    r"pr[eé]stamos?[ -]?r[aá]pid|cr[eé]ditos?[ -]?(?:f[aá]cil|inmediat)|slot(?:s|machine)|"
    r"adelgaz|bitcoin[ -]?doubler|essay[ -]?writ|hackear", re.IGNORECASE)
# --- RSK-005
DOORWAY_MIN_PAGES = 5
DOORWAY_MIN_WORDS = 80
DOORWAY_MIN_SIMILARITY = 0.85


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _is_safe(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in SAFE_HOSTS)


def hidden_text_signal(p: PageRecord) -> tuple[bool, str]:
    words = p.hidden_text.lower().split()
    if len(words) < HIDDEN_MIN_WORDS:
        return False, ""
    repeat = 1 - len(set(words)) / len(words)
    if repeat < HIDDEN_MIN_REPEAT:
        return False, ""
    return True, f"{len(words)} palabras ocultas, {round(repeat * 100)}% repetidas"


def hidden_links_signal(p: PageRecord, own_host: str) -> tuple[bool, str, str]:
    ext = [(h, t) for h, t, hidden in p.anchors
           if hidden and _host(h) and _host(h) != own_host and not _is_safe(_host(h))]
    if len(ext) < HIDDEN_EXT_LINKS_MIN:
        return False, "", ""
    hosts = sorted({_host(h) for h, _ in ext})
    return True, f"{len(ext)} enlaces externos ocultos a {len(hosts)} dominio(s)", hosts[0]


def spam_links(p: PageRecord, own_host: str) -> list[tuple[str, str]]:
    """[(host, motivo)] de enlaces externos con patrón de spam en el dominio o en el texto del enlace."""
    found: dict[str, str] = {}
    for href, text, _hidden in p.anchors:
        host = _host(href)
        if not host or host == own_host or _is_safe(host):
            continue
        if SPAM_RE.search(host):
            found.setdefault(host, "patrón en el dominio")
        elif SPAM_RE.search(text):
            found.setdefault(host, f"patrón en el texto del enlace: {text[:40]!r}")
    return sorted(found.items())


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def doorway_clusters(pages: list[PageRecord]) -> list[tuple[str, list[PageRecord]]]:
    """Grupos de >= DOORWAY_MIN_PAGES páginas del mismo directorio con texto casi idéntico."""
    by_dir: dict[str, list[PageRecord]] = defaultdict(list)
    for p in pages:
        if p.indexable and p.main_word_count >= DOORWAY_MIN_WORDS:
            path = urlsplit(p.url).path
            by_dir[path.rsplit("/", 1)[0] + "/"].append(p)
    out = []
    for directory, group in by_dir.items():
        if len(group) < DOORWAY_MIN_PAGES:
            continue
        parent = {id(p): id(p) for p in group}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if jaccard(a.main_words, b.main_words) >= DOORWAY_MIN_SIMILARITY:
                    parent[find(id(a))] = find(id(b))
        comps: dict[int, list[PageRecord]] = defaultdict(list)
        for p in group:
            comps[find(id(p))].append(p)
        out.extend((directory, c) for c in comps.values() if len(c) >= DOORWAY_MIN_PAGES)
    return out
