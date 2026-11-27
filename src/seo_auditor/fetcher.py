"""Cliente HTTP educado: user-agent identificable, espera entre pedidos,
sin seguir redirecciones (se registran para poder auditarlas)."""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

DEFAULT_USER_AGENT = "seo-auditor/0.1 (+https://github.com/UsuarioComun94/seo.auditor)"
MAX_BODY_BYTES = 2_000_000


@dataclass
class FetchResult:
    url: str
    status: int = 0
    headers: dict = field(default_factory=dict)
    text: str | None = None
    error: str = ""
    elapsed_ms: int = 0


def host_problem(host: str) -> str:
    """"" si el host es público; si no, el motivo: 'no resuelve' o 'IP privada' (sin revelar la IP)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return f"no resuelve por DNS ({type(exc).__name__})"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "resuelve a una IP privada/reservada"
    return "" if infos else "no resuelve por DNS (sin direcciones)"


def is_public_host(host: str) -> bool:
    """False si el host no resuelve o resuelve a una IP privada/loopback/link-local (anti-SSRF)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return bool(infos)


class Fetcher:
    def __init__(self, user_agent: str = "", delay_seconds: float = 0.5, timeout: float = 15.0,
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.monotonic):
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.delay = float(delay_seconds)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.requests_made = 0

    @property
    def robots_token(self) -> str:
        """Token de producto del user-agent, para evaluar robots.txt."""
        return self.user_agent.split("/")[0].split()[0] if self.user_agent else "*"

    def _wait(self) -> None:
        if self._last is not None and self.delay > 0:
            remaining = self.delay - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

    def get(self, url: str, read_body: bool = True) -> FetchResult:
        if urlsplit(url).scheme not in ("http", "https"):
            return FetchResult(url=url, error="esquema no soportado")
        self._wait()
        self.requests_made += 1
        started = self._clock()
        try:
            resp = self.session.get(url, allow_redirects=False, timeout=self.timeout, stream=True)
        except requests.RequestException as exc:
            return FetchResult(url=url, error=f"{type(exc).__name__}: {exc}"[:300],
                               elapsed_ms=int((self._clock() - started) * 1000))
        try:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            elapsed = int((self._clock() - started) * 1000)
            ctype = headers.get("content-type", "").lower()
            text = None
            if read_body and any(t in ctype for t in ("html", "xml", "text/plain")):
                raw = b""
                for chunk in resp.iter_content(chunk_size=65536):
                    raw += chunk
                    if len(raw) >= MAX_BODY_BYTES:
                        break
                text = raw.decode(resp.encoding or "utf-8", errors="replace")
            return FetchResult(url=url, status=resp.status_code, headers=headers, text=text, elapsed_ms=elapsed)
        except requests.RequestException as exc:
            return FetchResult(url=url, error=f"{type(exc).__name__}: {exc}"[:300],
                               elapsed_ms=int((self._clock() - started) * 1000))
        finally:
            resp.close()
