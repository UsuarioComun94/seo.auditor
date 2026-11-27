"""Detección de plataforma del sitio y límites conocidos de cada una.

La detección usa señales públicas de la home (HTML y cabeceras). Si no hay señal clara, devuelve "".
Los límites (rules/platforms.yaml) son solo los de alta confianza: que una regla no figure ahí
NO significa que se pueda arreglar en esa plataforma.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .rules import default_rules_path

# Plataformas que arman el contenido en el navegador: sin renderizar, el HTML crudo está casi vacío.
JS_RENDERED_PLATFORMS = {"google_sites"}

_GENERATOR_RE = re.compile(r"""<meta[^>]+name=["']generator["'][^>]*content=["']([^"']+)""", re.IGNORECASE)


def detect_platform(url: str, headers: dict, html: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    low = (html or "")[:300_000].lower()
    m = _GENERATOR_RE.search(html or "")
    generator = (m.group(1) if m else "").lower()
    server = (headers or {}).get("server", "").lower()

    if host == "sites.google.com":
        return "google_sites"
    if "wordpress" in generator or "/wp-content/" in low:
        return "wordpress"
    if "cdn.shopify.com" in low or "shopify.theme" in low:
        return "shopify"
    if "wix.com" in generator or "wixstatic.com" in low:
        return "wix"
    if "tiendanube" in low or "nuvemshop" in low:
        return "tiendanube"
    if "squarespace" in generator or "static1.squarespace.com" in low:
        return "squarespace"
    if "webflow" in generator or "assets.website-files.com" in low:
        return "webflow"
    if host.endswith(".github.io") or server == "github.com":
        return "github_pages"
    return ""


def default_platforms_path() -> Path:
    return default_rules_path().parent / "platforms.yaml"


def load_platforms(path: str | Path | None = None) -> dict:
    data = yaml.safe_load(Path(path or default_platforms_path()).read_text(encoding="utf-8")) or {}
    return data.get("platforms", {})


def platform_label(platforms: dict, platform: str) -> str:
    return platforms.get(platform, {}).get("label", platform)


def limit_for(platforms: dict, platform: str, rule_id: str) -> str:
    """Texto del límite conocido de la plataforma para esa regla, o "" si no hay dato."""
    entry = platforms.get(platform)
    if not entry:
        return ""
    text = (entry.get("limits") or {}).get(rule_id)
    return f"limitado en {entry.get('label', platform)}: {text}" if text else ""
