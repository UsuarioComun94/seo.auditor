"""Servidores HTTP locales para probar el crawler sin red.

- fixture_server: sirve fixture/site bajo /seo.auditor/ (como GitHub Pages de proyecto) y reescribe
  la URL de producción por la local, así los canonicals apuntan a algo rastreable.
- behavior_server: comportamientos que GitHub Pages no permite (301/302 reales, bucles, X-Robots-Tag).
"""

from __future__ import annotations

import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "fixture" / "site"
PROD_BASE = "https://usuariocomun94.github.io/seo.auditor/"
PREFIX = "/seo.auditor/"


@pytest.fixture(autouse=True)
def _no_proxy_for_localhost(monkeypatch):
    # El entorno puede tener un proxy global; el tráfico a 127.0.0.1 no debe pasar por él.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


class _Server:
    def __init__(self, handler_factory):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _fixture_handler(origin_getter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body: bytes, ctype: str):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _serve(self):
            path = self.path.split("?", 1)[0]
            local_base = origin_getter() + PREFIX
            file = None
            if path.startswith(PREFIX):
                rel = path[len(PREFIX):]
                candidate = SITE / (rel + "index.html" if rel == "" or rel.endswith("/") else rel)
                if candidate.is_file() and SITE in candidate.resolve().parents:
                    file = candidate
            if file is None:
                body = (SITE / "404.html").read_text(encoding="utf-8").replace(PROD_BASE, local_base)
                return self._send(404, body.encode(), "text/html; charset=utf-8")
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            raw = file.read_bytes()
            if ctype.startswith("text/") or ctype in ("application/xml", "text/xml"):
                raw = raw.decode("utf-8").replace(PROD_BASE, local_base).encode("utf-8")
                ctype += "; charset=utf-8"
            self._send(200, raw, ctype)

        do_GET = _serve
        do_HEAD = _serve

    return Handler


@pytest.fixture(scope="session")
def fixture_server():
    holder = {}
    server = _Server(_fixture_handler(lambda: holder["origin"]))
    holder["origin"] = server.origin
    yield server
    server.close()


def _behavior_handler(origin_getter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _html(self, status, body, headers=None):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, status, location):
            self.send_response(status)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            o = origin_getter()
            p = self.path.split("?", 1)[0]
            page = ('<!doctype html><html><head><title>{t}</title><meta name="description" content="d">'
                    '<link rel="canonical" href="{o}{p}"></head><body><h1>{t}</h1>{extra}</body></html>')
            if p == "/robots.txt":
                body = "User-agent: *\nDisallow: /blocked/\nSitemap: " + o + "/sitemap.xml\n"
                return self._html(200, body, {"Content-Type": "text/plain"}) if False else self._plain(body)
            if p == "/sitemap.xml":
                urls = ["/", "/chain-1", "/loop-a", "/xrobots", "/gone"]
                body = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        + "".join(f"<url><loc>{o}{u}</loc></url>" for u in urls) + "</urlset>")
                return self._xml(body)
            if p == "/":
                extra = ('<a href="/chain-1">c</a><a href="/loop-a">l</a><a href="/xrobots">x</a>'
                         '<a href="/blocked/page">b</a><a href="/gone">g</a>')
                return self._html(200, page.format(t="Inicio", o=o, p="/", extra=extra))
            if p == "/chain-1":
                return self._redirect(301, "/chain-2")
            if p == "/chain-2":
                return self._redirect(302, "/chain-3")
            if p == "/chain-3":
                return self._html(200, page.format(t="Destino", o=o, p=p, extra=""))
            if p == "/loop-a":
                return self._redirect(301, "/loop-b")
            if p == "/loop-b":
                return self._redirect(301, "/loop-a")
            if p == "/xrobots":
                return self._html(200, page.format(t="Con cabecera", o=o, p=p, extra=""),
                                  {"X-Robots-Tag": "noindex, nofollow"})
            if p == "/gone":
                return self._html(410, "<html><head><title>Gone</title></head><body>gone</body></html>")
            if p.startswith("/blocked/"):
                return self._html(200, page.format(t="Bloqueada", o=o, p=p, extra=""))
            return self._html(404, "<html><head><title>404</title></head><body>no</body></html>")

        def _plain(self, body):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _xml(self, body):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_HEAD = do_GET

    return Handler


@pytest.fixture(scope="session")
def behavior_server():
    holder = {}
    server = _Server(_behavior_handler(lambda: holder["origin"]))
    holder["origin"] = server.origin
    yield server
    server.close()


def local_config(domain: str, mode: str = "own", **crawl):
    from seo_auditor.config import parse_config

    base = {"max_urls": 200, "delay_seconds": 0, "respect_robots": True,
            "user_agent": "seo-auditor/0.1 (+https://github.com/UsuarioComun94/seo.auditor)"}
    base.update(crawl)
    raw = {"name": "local", "domain": domain, "mode": mode, "crawl": base}
    if mode == "client":
        raw["authorized"] = True
    return parse_config(raw)
