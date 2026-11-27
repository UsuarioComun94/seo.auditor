"""Renderizado de JavaScript con Chromium (Playwright), para sitios que arman el HTML en el navegador
(Google Sites, SPAs). Es opcional: sin Playwright instalado el crawl sigue con el HTML crudo.

Reglas de seguridad y cortesía:
- Mismo user-agent identificable del crawl (no se hace pasar por Chrome ni por Googlebot).
- Cada render cuenta como un pedido más y respeta la pausa configurada.
- Anti-SSRF: se abortan los pedidos del navegador a hosts que no son públicos (un script de la página no
  puede llevar al runner a redes internas). Imágenes, fuentes y media no se descargan.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .fetcher import is_public_host

BLOCKED_TYPES = {"image", "media", "font"}


class RenderUnavailable(RuntimeError):
    pass


class Renderer:
    def __init__(self, user_agent: str, timeout_ms: int = 20000, allow_private: bool = False):
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self.allow_private = allow_private      # solo para pruebas con servidores locales
        self._pw = self._browser = self._ctx = None
        self._host_cache: dict[str, bool] = {}
        self.blocked_requests = 0

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RenderUnavailable("Playwright no está instalado") from exc
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self._ctx = self._browser.new_context(user_agent=self.user_agent, java_script_enabled=True)
            self._ctx.route("**/*", self._route)
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise RenderUnavailable(f"no se pudo iniciar Chromium: {type(exc).__name__}") from exc

    def _host_ok(self, host: str) -> bool:
        if self.allow_private:
            return True
        if host not in self._host_cache:
            self._host_cache[host] = is_public_host(host)
        return self._host_cache[host]

    def _route(self, route) -> None:
        req = route.request
        parts = urlsplit(req.url)
        if req.resource_type in BLOCKED_TYPES or parts.scheme not in ("http", "https") \
                or not self._host_ok(parts.hostname or ""):
            if req.resource_type not in BLOCKED_TYPES:
                self.blocked_requests += 1
            route.abort()
        else:
            route.continue_()

    def render(self, url: str) -> str | None:
        """HTML del DOM luego de ejecutar JS, o None si falla (el crawl usa entonces el HTML crudo)."""
        if self._ctx is None:
            self.start()
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            return page.content()
        except Exception:  # noqa: BLE001 - timeout o error de página: se degrada al HTML crudo
            return None
        finally:
            page.close()

    def close(self) -> None:
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._ctx = None
