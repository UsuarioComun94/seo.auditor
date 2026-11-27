"""Fase 5: señales de riesgo. Cada regla se prueba con el patrón y con su contraparte legítima."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import local_config

from seo_auditor import risk
from seo_auditor.checks import run_checks
from seo_auditor.crawler import GOOGLEBOT_UA, Crawler
from seo_auditor.models import CrawlResult, PageRecord
from seo_auditor.parser import hides_content, parse_html
from seo_auditor.rules import load_rules
from seo_auditor.urls import Scope

RULES = load_rules()
BASE = "https://x.com/"


def page(url=BASE, **kw):
    kw.setdefault("status", 200)
    kw.setdefault("is_html", True)
    return PageRecord(url=url, **kw)


def run(pages, mode="own"):
    r = CrawlResult(name="c", domain=BASE, mode=mode)
    r.pages = {p.url: p for p in pages}
    return run_checks(r, RULES, Scope(BASE))


def ids(issues):
    return {i.rule_id for i in issues}


# ---------- parser: qué cuenta como oculto ----------
@pytest.mark.parametrize("style", [
    "display:none", "display: none", "visibility:hidden", "font-size:0", "font-size:0px", "opacity:0",
    "position:absolute;left:-9999px", "text-indent:-5000px", "height:0;overflow:hidden", "clip:rect(0,0,0,0)"])
def test_hiding_styles_detected(style):
    assert hides_content(style)


@pytest.mark.parametrize("style", ["display:block", "font-size:0.9em", "opacity:0.5", "left:-10px", "color:red", ""])
def test_visible_styles_not_flagged(style):
    assert not hides_content(style)


def test_parser_separates_hidden_visible_and_boilerplate_text():
    h = ("<body><nav>menu uno dos</nav><p>texto visible principal</p><div hidden>oculto aqui</div>"
         "<div style='display:none'><a href='/x'>enlace oculto</a></div><footer>pie</footer></body>")
    p = parse_html(h, BASE)
    assert p.main_words == ["texto", "visible", "principal"]
    assert "oculto aqui" in p.hidden_text and "enlace oculto" in p.hidden_text
    assert p.anchors == [(BASE + "x", "enlace oculto", True)]


def test_parser_survives_unbalanced_tags_without_leaking_hidden_state():
    p = parse_html("<div style='display:none'><span>a</div><p>visible texto aqui</p>", BASE)
    assert "visible" in p.main_words


# ---------- RSK-001 ----------
def test_rsk001_keyword_stuffing_flagged_but_unique_hidden_text_is_not():
    stuffed = " ".join(["barato oferta comprar"] * 10)
    unique = " ".join(f"palabra{i}" for i in range(40))
    assert "RSK-001" in ids(run([page(hidden_text=stuffed)]))
    assert "RSK-001" not in ids(run([page(hidden_text=unique)]))      # un menú/modal legítimo
    assert "RSK-001" not in ids(run([page(hidden_text="barato barato barato")]))  # muy poco texto


# ---------- RSK-002 ----------
def test_rsk002_hidden_external_links_but_not_internal_or_social():
    spam = [(f"https://spam{i}.example/p", "x", True) for i in range(3)]
    social = [(f"https://{h}/u", "red", True) for h in ("facebook.com", "instagram.com", "x.com")]
    internal = [(BASE + f"p{i}", "menu", True) for i in range(5)]
    assert "RSK-002" in ids(run([page(anchors=spam)]))
    assert "RSK-002" not in ids(run([page(anchors=social)]))
    assert "RSK-002" not in ids(run([page(anchors=internal)]))
    assert "RSK-002" not in ids(run([page(anchors=[(a, t, False) for a, t, _ in spam])]))  # visibles: no es esta regla


# ---------- RSK-004 ----------
def test_rsk004_spam_patterns_in_host_or_text_and_safe_hosts_ignored():
    anchors = [("https://mejor-casino.example/", "jugar", False),
               ("https://blog.example/", "comprar viagra barato", False),
               ("https://facebook.com/casino", "casino", False),
               ("https://wikipedia.org/", "enciclopedia", False)]
    found = [i for i in run([page(anchors=anchors)]) if i.rule_id == "RSK-004"]
    assert sorted(i.target for i in found) == ["blog.example", "mejor-casino.example"]


# ---------- RSK-005 ----------
def _doorway(n, similar=True):
    base = [f"servicio{k}" for k in range(100)]
    out = []
    for i in range(n):
        words = base[:] if similar else [f"w{i}_{k}" for k in range(100)]
        words[0] = f"ciudad{i}"
        out.append(page(BASE + f"servicios/plomero-en-ciudad-{i}.html", title=f"t{i}", meta_description="d", h1_count=1,
                        main_word_count=len(words), main_words=frozenset(words)))
    return out


def test_rsk005_doorway_cluster_detected_once_per_group():
    found = [i for i in run(_doorway(6)) if i.rule_id == "RSK-005"]
    assert len(found) == 1 and "6 páginas" in found[0].detail and found[0].target == "/servicios/"


def test_rsk005_not_for_few_pages_or_different_content():
    assert "RSK-005" not in ids(run(_doorway(4)))
    assert "RSK-005" not in ids(run(_doorway(8, similar=False)))


# ---------- RSK-003: servidor que sirve otra cosa a Googlebot ----------
class _Cloak(BaseHTTPRequestHandler):
    seen_uas = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        _Cloak.seen_uas.append(ua)
        if self.path == "/robots.txt":
            body, status = b"User-agent: *\nAllow: /\n", 200
        elif "Googlebot" in ua and not getattr(self.server, "block_bot", False):
            body, status = (b"<html><head><title>Casino online</title></head><body><p>"
                            + b" ".join(b"apuestas%d" % i for i in range(60)) + b"</p></body></html>"), 200
        elif "Googlebot" in ua:
            body, status = b"forbidden", 403
        else:
            body, status = (b"<html><head><title>Tienda de zapatos</title></head><body><p>"
                            + b" ".join(b"zapato%d" % i for i in range(60)) + b"</p></body></html>"), 200
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = do_GET


@pytest.fixture
def cloak_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Cloak)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Cloak.seen_uas.clear()
    yield httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


def _audit(base, mode="own", **crawl):
    cfg = local_config(base, mode, **crawl)
    res = Crawler(cfg).run()
    return res, run_checks(res, RULES, Scope(base))


def test_rsk003_cloaking_detected_when_enabled(cloak_server):
    _, base = cloak_server
    res, issues = _audit(base, compare_googlebot_ua=True)
    [i] = [i for i in issues if i.rule_id == "RSK-003"]
    assert i.severity == "critical" and i.hat == "signal" and "Casino" in i.detail
    assert any("cloaking: se compararon 1" in n for n in res.notes)


def test_rsk003_not_run_by_default_nor_in_competitor_mode(cloak_server):
    _, base = cloak_server
    _, issues = _audit(base)                                   # compare_googlebot_ua apagado
    assert "RSK-003" not in ids(issues) and not any("Googlebot" in u for u in _Cloak.seen_uas)
    from seo_auditor.config import ConfigError
    with pytest.raises(ConfigError):                           # en competencia no se falsifica Googlebot
        local_config(base, "competitor", compare_googlebot_ua=True, delay_seconds=2.0, max_urls=10)


def test_rsk003_googlebot_403_is_not_cloaking(cloak_server):
    httpd, base = cloak_server
    httpd.block_bot = True      # sitios que bloquean Googlebots falsos (verifican por IP)
    _, issues = _audit(base, compare_googlebot_ua=True)
    assert "RSK-003" not in ids(issues)


def test_risk_issues_stay_out_of_the_score():
    from seo_auditor.score import compute_score
    issues = run([page(hidden_text=" ".join(["barato oferta comprar"] * 10))])
    signals = [i for i in issues if i.rule_id.startswith("RSK")]
    assert signals and all(i.hat == "signal" for i in signals)
    assert compute_score(signals, 1, {"high": 5, "critical": 10}) == 100.0
