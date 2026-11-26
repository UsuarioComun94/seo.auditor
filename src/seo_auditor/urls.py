"""Utilidades de URLs: normalización, resolución y alcance del crawl."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit

_SKIP_SCHEMES = {"javascript", "mailto", "tel", "data", "sms", "ftp", "file"}


def normalize_url(url: str) -> str:
    """Normaliza esquema y host a minúsculas, saca puerto por defecto, userinfo y fragmento."""
    url = url.strip()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return url.split("#", 1)[0]
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:  # IPv6
        host = f"[{host}]"
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def resolve(base: str, href: str) -> str | None:
    """Resuelve un href contra la URL base. Devuelve None si no es http(s)."""
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return None
    scheme = urlsplit(href).scheme.lower()
    if scheme in _SKIP_SCHEMES:
        return None
    absolute = urljoin(base, href)
    if urlsplit(absolute).scheme.lower() not in ("http", "https"):
        return None
    return normalize_url(absolute)


def canon_key(url: str) -> str:
    """Clave para comparar canonicals: ignora index.html / index.htm final."""
    n = normalize_url(url)
    parts = urlsplit(n)
    path = parts.path
    for suffix in ("/index.html", "/index.htm"):
        if path.endswith(suffix):
            path = path[: -len(suffix) + 1]
            break
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


class Scope:
    """Define qué URLs son internas: mismo host y bajo el prefijo de ruta del dominio."""

    def __init__(self, domain: str):
        parts = urlsplit(normalize_url(domain))
        self.scheme = parts.scheme
        self.netloc = parts.netloc
        path = parts.path or "/"
        self.prefix = path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"
        self.root = normalize_url(domain)

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.netloc}"

    def same_host(self, url: str) -> bool:
        return urlsplit(url).netloc.lower() == self.netloc

    def contains(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.netloc.lower() == self.netloc and parts.path.startswith(self.prefix)
