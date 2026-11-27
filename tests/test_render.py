"""Renderizado de JavaScript: sitio que arma título, H1 y enlaces solo en el navegador."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from seo_auditor.config import parse_config
from seo_auditor.crawler import Crawler
from seo_auditor.render import RenderUnavailable, Renderer

pytest.importorskip("playwright")

PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body><div id="app"></div>
<script>
document.title = "Pagina %(n)s";
document.getElementById("app").innerHTML = '<h1>Titulo %(n)s</h1><a href="%(next)s">siguiente</a>';
fetch("http://169.254.169.254/latest/meta-data/").catch(function(){});
</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _H.seen.append(self.path)
        pages = {"/": ("1", "/dos"), "/dos": ("2", "/")}
        if self.path in pages:
            n, nxt = pages[self.path]
            body = (PAGE % {"n": n, "next": nxt}).encode()
            self.send_response(200)
        else:
            body = b"nope"
            self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_HEAD = do_GET


@pytest.fixture
def js_site():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


def cfg_for(domain, render):
    return parse_config({"name": "js", "domain": domain, "mode": "own",
                         "crawl": {"max_urls": 10, "delay_seconds": 0, "render_js": render}})


def _chromium_ok():
    r = Renderer("t", allow_private=True)
    try:
        r.start()
        return True
    except RenderUnavailable:
        return False
    finally:
        r.close()


needs_chromium = pytest.mark.skipif(not _chromium_ok(), reason="Chromium no disponible")


def test_without_render_the_js_site_looks_empty(js_site):
    res = Crawler(cfg_for(js_site, False)).run()
    assert len(res.pages) == 1
    assert not res.pages[js_site].title and res.pages[js_site].h1_count == 0


@needs_chromium
def test_render_discovers_js_content_and_links(js_site):
    res = Crawler(cfg_for(js_site, True), renderer=Renderer("seo-auditor/test", allow_private=True)).run()
    assert set(res.pages) == {js_site, js_site + "dos"}
    assert res.pages[js_site].title == "Pagina 1" and res.pages[js_site].h1_count == 1
    assert any("JavaScript renderizado en 2" in n for n in res.notes)


@needs_chromium
def test_render_blocks_requests_to_non_public_hosts(js_site):
    # sin allow_private: la página local misma es privada y falla, pero el 169.254.169.254 jamás debe salir
    r = Renderer("seo-auditor/test", allow_private=False)
    try:
        assert r.render(js_site) is None          # el propio host local es privado: se aborta
        assert r.blocked_requests >= 1
    finally:
        r.close()
    assert not any("169.254" in p for p in _H.seen)


def test_missing_playwright_degrades_to_raw_html(js_site):
    class Broken(Renderer):
        def start(self):
            raise RenderUnavailable("Playwright no está instalado")

    res = Crawler(cfg_for(js_site, True), renderer=Broken("t")).run()
    assert len(res.pages) == 1
    assert any("no disponible" in n for n in res.notes)


def test_js_platform_turns_rendering_on_automatically(js_site, monkeypatch):
    import seo_auditor.crawler as crawler_mod

    calls = []

    class FakeRenderer:
        def __init__(self, ua):
            pass

        def render(self, url):
            calls.append(url)
            return "<html><head><title>Renderizado</title></head><body><h1>x</h1></body></html>"

        def close(self):
            pass

    monkeypatch.setattr(crawler_mod, "Renderer", FakeRenderer)
    monkeypatch.setattr(crawler_mod, "detect_platform", lambda *a, **k: "google_sites")
    res = Crawler(cfg_for(js_site, False)).run()      # render_js apagado en la config
    assert calls and res.pages[js_site].title == "Renderizado"
    assert any("automáticamente" in n for n in res.notes)
