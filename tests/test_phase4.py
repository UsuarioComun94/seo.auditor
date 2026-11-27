"""Fase 4: PageSpeed/CrUX, Search Console, reglas PERF/GSC, pestañas y estados."""

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import local_config
from fakes import MemSheets
from test_panel import HEADER, SCHEMA, row

from seo_auditor import __main__ as cli
from seo_auditor import sheets as sheets_mod
from seo_auditor.benchmark import compute_benchmark
from seo_auditor.checks import run_checks
from seo_auditor.config import ConfigError, parse_config
from seo_auditor.gsc import GscError, expected_ctr, fetch
from seo_auditor.models import CrawlResult, PageRecord
from seo_auditor.pagespeed import CruxClient, PerfError, PsiClient, measure, pick_pages
from seo_auditor.panel import parse_clients
from seo_auditor.report import build_tabs
from seo_auditor.rules import load_rules
from seo_auditor.score import compute_comparable_score
from seo_auditor.state import parse_previous
from seo_auditor.urls import Scope

RULES = load_rules()
BASE = "https://x.com/"
ICOLS = next(t["columns"] for t in SCHEMA["tabs"] if t["name"] == "Issues")
HCOLS = next(t["columns"] for t in SCHEMA["tabs"] if t["name"] == "Historico")


# ---------- servidor falso de PSI / CrUX ----------
class _Api(BaseHTTPRequestHandler):
    mode = {"psi": "ok", "crux": "ok"}
    calls = []

    def log_message(self, *a):
        pass

    def _send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _Api.calls.append(self.path)
        if _Api.mode["psi"] == "429":
            return self._send(429, {})
        self._send(200, {"lighthouseResult": {"categories": {"performance": {"score": 0.42}}, "audits": {
            "largest-contentful-paint": {"numericValue": 5200.0}, "cumulative-layout-shift": {"numericValue": 0.31},
            "total-blocking-time": {"numericValue": 700.0}, "first-contentful-paint": {"numericValue": 1900.0},
            "server-response-time": {"numericValue": 2100.0}, "speed-index": {"numericValue": 4000.0}}}})

    def do_POST(self):
        _Api.calls.append(self.path)
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if _Api.mode["crux"] == "404":
            return self._send(404, {"error": {"status": "NOT_FOUND"}})
        self._send(200, {"record": {"metrics": {
            "largest_contentful_paint": {"percentiles": {"p75": 4500}},
            "interaction_to_next_paint": {"percentiles": {"p75": 650}},
            "cumulative_layout_shift": {"percentiles": {"p75": "0.30"}},
            "experimental_time_to_first_byte": {"percentiles": {"p75": 900}}}}})


@pytest.fixture
def api():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Api.mode.update(psi="ok", crux="ok")
    _Api.calls.clear()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


def result_with(pages=None, **kw):
    r = CrawlResult(name="c", domain=BASE, mode="own", **kw)
    for p in pages or [PageRecord(url=BASE, status=200, is_html=True, title="t", meta_description="d", h1_count=1)]:
        r.pages[p.url] = p
    return r


# ---------- clientes ----------
def test_psi_parses_lab_metrics(api):
    lab = PsiClient("k", api, sleep=lambda s: None).lab(BASE)
    assert lab["score"] == 42 and lab["lcp_ms"] == 5200 and lab["cls"] == 0.31 and lab["ttfb_ms"] == 2100
    assert "key=k" in _Api.calls[0] and "strategy=mobile" in _Api.calls[0]


def test_psi_quota_error_retries_then_fails_without_leaking_the_key(api):
    _Api.mode["psi"] = "429"
    sleeps = []
    with pytest.raises(PerfError) as e:
        PsiClient("SECRETKEY", api, sleep=sleeps.append).lab(BASE)
    assert "cuota" in str(e.value) and "SECRETKEY" not in str(e.value) and len(sleeps) == 2


def test_psi_network_error_message_has_no_url_or_key():
    with pytest.raises(PerfError) as e:
        PsiClient("SECRETKEY", "http://127.0.0.1:9/", sleep=lambda s: None, timeout=1).lab(BASE)
    assert "SECRETKEY" not in str(e.value) and "127.0.0.1" not in str(e.value)


def test_crux_parses_p75_and_404_means_no_data(api):
    c = CruxClient("k", api)
    assert c.origin("https://x.com") == {"lcp_ms": 4500, "inp_ms": 650, "cls": 0.30, "ttfb_ms": 900}
    _Api.mode["crux"] = "404"
    assert c.origin("https://x.com") == {}


# ---------- medición ----------
def test_pick_pages_home_first_then_most_linked_indexable():
    mk = lambda u, links=(): PageRecord(url=u, status=200, is_html=True, links=list(links))   # noqa: E731
    r = result_with([mk(BASE, [BASE + "a", BASE + "b"]), mk(BASE + "a", [BASE + "b"]), mk(BASE + "b"), mk(BASE + "c")])
    assert pick_pages(r, BASE, 3) == [BASE, BASE + "b", BASE + "a"]
    assert pick_pages(r, BASE, 1) == [BASE]


def test_measure_status_ok_partial_and_unavailable(api):
    r = result_with()
    measure(r, BASE, PsiClient("k", api, sleep=lambda s: None), CruxClient("k", api), 3, log=lambda m: None)
    assert r.perf_status == "ok" and r.perf[0]["field"]["inp_ms"] == 650
    r2 = result_with()
    measure(r2, BASE, None, None, 3, log=lambda m: None)
    assert r2.perf_status == "no_disponible" and r2.perf == []
    _Api.mode["psi"] = "429"
    r3 = result_with()
    measure(r3, BASE, PsiClient("", api, sleep=lambda s: None), None, 3, log=lambda m: None)
    assert r3.perf_status == "no_disponible" and any("cuota" in n for n in r3.notes)
    assert any("sin clave" in n for n in r3.notes)


# ---------- reglas PERF ----------
def perf_issues(row_):
    r = result_with()
    r.perf, r.perf_status = [{"url": BASE, "strategy": "mobile", "error": "", **row_}], "ok"
    return {i.rule_id: i for i in run_checks(r, RULES, Scope(BASE)) if i.rule_id.startswith("PERF")}


def test_perf_rules_fire_from_lab_and_field():
    got = perf_issues({"score": 42, "lcp_ms": 5200, "cls": 0.31, "tbt_ms": 700, "ttfb_ms": 2100,
                       "field": {"lcp_ms": 4500, "inp_ms": 650, "cls": 0.3, "ttfb_ms": 900}})
    assert set(got) == {"PERF-001", "PERF-002", "PERF-003", "PERF-004", "PERF-005"}
    assert "laboratorio 5.2 s" in got["PERF-001"].detail and "campo p75 4.5 s" in got["PERF-001"].detail


def test_perf_rules_silent_on_good_or_missing_values_and_errors():
    assert perf_issues({"score": 90, "lcp_ms": 2000, "cls": 0.05, "tbt_ms": 100, "ttfb_ms": 300}) == {}
    assert perf_issues({"score": None, "lcp_ms": None, "cls": None, "tbt_ms": None, "ttfb_ms": None}) == {}
    r = result_with()
    r.perf, r.perf_status = [{"url": BASE, "error": "PSI respondió 500"}], "no_disponible"
    assert not [i for i in run_checks(r, RULES, Scope(BASE)) if i.rule_id.startswith("PERF")]


def test_perf_does_not_affect_comparable_score():
    r = result_with()
    r.perf, r.perf_status = [{"url": BASE, "error": "", "score": 10, "lcp_ms": 9000, "cls": 1, "tbt_ms": 2000, "ttfb_ms": 5000}], "ok"
    issues = run_checks(r, RULES, Scope(BASE))
    assert any(i.rule_id.startswith("PERF") for i in issues)
    w = SCHEMA["severity_weights"]
    assert compute_comparable_score(issues, 1, w, RULES) == compute_comparable_score(
        [i for i in issues if not i.rule_id.startswith("PERF")], 1, w, RULES)


# ---------- reglas GSC ----------
def gsc_result(pages_gsc, crawled, truncated=False, status="ok"):
    r = result_with([PageRecord(url=BASE + u, status=200, is_html=True, title=u, meta_description="d", h1_count=1,
                                canonical=BASE + u) for u in crawled], truncated=truncated)
    r.gsc = {"start": "2026-10-01", "end": "2026-10-28", "queries": [],
             "pages": [{"key": BASE + k, **v} for k, v in pages_gsc.items()]}
    r.gsc_status = status
    return r


def gsc_ids(r):
    return {(i.rule_id, i.url.removeprefix(BASE)) for i in run_checks(r, RULES, Scope(BASE)) if i.rule_id.startswith("GSC")}


def test_gsc_rules():
    r = gsc_result({"a": dict(clicks=1, impressions=1000, ctr=0.001, position=4.0),     # CTR bajo en top 6
                    "viejo": dict(clicks=2, impressions=50, ctr=0.04, position=9.0)},    # google la conoce, el crawl no
                   crawled=["a", "nueva"])                                                # "nueva" sin impresiones
    assert gsc_ids(r) == {("GSC-002", "a"), ("GSC-003", "viejo"), ("GSC-001", "nueva")}


def test_gsc_001_needs_real_traffic_and_003_skips_truncated_crawls():
    r = gsc_result({"a": dict(clicks=0, impressions=40, ctr=0, position=30)}, crawled=["a", "b"])
    assert gsc_ids(r) == set()                       # 40 impresiones en total: "cero" no dice nada
    r = gsc_result({"a": dict(clicks=0, impressions=900, ctr=0.05, position=3), "z": dict(clicks=0, impressions=50, ctr=0.05, position=9)},
                   crawled=["a"], truncated=True)
    assert ("GSC-003", "z") not in gsc_ids(r)        # con el crawl incompleto, "no encontrada" no es confiable


def test_gsc_rules_off_when_search_console_failed():
    r = gsc_result({"viejo": dict(clicks=2, impressions=500, ctr=0.04, position=9.0)}, crawled=["a"], status="no_disponible")
    assert gsc_ids(r) == set()


def test_expected_ctr_curve_and_fetch_window():
    assert expected_ctr(2) > expected_ctr(5) > expected_ctr(9) > expected_ctr(15) == 0.0

    class Svc:
        bodies = []

        def searchanalytics(self):
            return self

        def query(self, siteUrl, body):
            Svc.bodies.append((siteUrl, body))
            return type("E", (), {"execute": lambda s: {"rows": [{"keys": ["k"], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}]}})()

    out = fetch(Svc(), "sc-domain:x.com", today=date(2026, 11, 27))
    assert (out["start"], out["end"]) == ("2026-10-28", "2026-11-24")     # 28 días, sin los últimos 3
    assert [b["dimensions"] for _, b in Svc.bodies] == [["page"], ["query"]]
    assert out["pages"][0]["key"] == "k"

    class Boom:
        def searchanalytics(self):
            raise RuntimeError("403 secreto")
    with pytest.raises(GscError) as e:
        fetch(Boom(), "p")
    assert "secreto" not in str(e.value)


# ---------- pestañas y estados ----------
def test_rendimiento_rows_and_gsc_tab_only_when_ok():
    r = gsc_result({"a": dict(clicks=3, impressions=10, ctr=.3, position=2)}, crawled=["a"])
    r.perf, r.perf_status = [{"url": BASE, "strategy": "mobile", "error": "", "score": 42, "lcp_ms": 5200,
                              "field": {"lcp_ms": 4500}}], "ok"
    tabs = build_tabs(r, [], "R1", schema=SCHEMA)
    rcols = next(t["columns"] for t in SCHEMA["tabs"] if t["name"] == "Rendimiento")
    assert tabs["Rendimiento"][0][rcols.index("campo_lcp_ms")] == 4500
    g = tabs["Search Console"][0]
    assert g[:2] == ["pagina", BASE + "a"] and g[6] is True
    r.gsc_status = "no_disponible"
    assert "Search Console" not in build_tabs(r, [], "R2", schema=SCHEMA)   # no se pisa la última corrida buena


def test_unmeasured_perf_issue_is_kept_not_resolved_but_measured_one_resolves():
    prow = [""] * len(ICOLS)
    for col, val in (("regla_id", "PERF-001"), ("url", BASE), ("estado", "nuevo"), ("issue_key", "kperf"),
                     ("primera_vez_visto", "2026-11-01")):
        prow[ICOLS.index(col)] = val
    prev = parse_previous([prow], [], BASE, ICOLS, HCOLS)
    r = result_with()                                   # no se midió rendimiento
    est = [x[ICOLS.index("estado")] for x in build_tabs(r, [], "R2", schema=SCHEMA, previous=prev)["Issues"]]
    assert est == ["recurrente"]
    r.perf, r.perf_status = [{"url": BASE, "error": "", "score": 95, "lcp_ms": 1000, "cls": 0, "tbt_ms": 0, "ttfb_ms": 100}], "ok"
    est = [x[ICOLS.index("estado")] for x in build_tabs(r, [], "R3", schema=SCHEMA, previous=prev)["Issues"]]
    assert est == ["resuelto"]


def test_benchmark_has_home_performance_columns_or_empty():
    r = result_with()
    assert compute_benchmark(r)["perf_puntaje_movil"] is None
    r.perf = [{"url": BASE, "error": "", "score": 42, "lcp_ms": 5200.0, "cls": 0.31, "tbt_ms": 700.0, "ttfb_ms": 2100.0,
               "field": {"lcp_ms": 4500, "inp_ms": 650, "cls": 0.3}}]
    b = compute_benchmark(r)
    assert (b["perf_puntaje_movil"], b["lcp_ms_lab"], b["inp_ms_campo"]) == (42, 5200.0, 650)
    cols = next(t["columns"] for t in SCHEMA["panel"]["tabs"] if t["name"] == "Benchmark")
    assert set(b) | {"nombre", "modo", "ultima_corrida_utc"} == set(cols)


# ---------- config y Panel ----------
def test_config_search_console_and_performance_validation():
    raw = {"name": "n", "domain": "https://a.com/", "mode": "own", "search_console": "sc-domain:a.com"}
    assert parse_config(raw).search_console == "sc-domain:a.com" and parse_config(raw).perf.pagespeed is True
    with pytest.raises(ConfigError, match="Search Console"):
        parse_config({**raw, "mode": "competitor", "crawl": {"delay_seconds": 2, "user_agent": "bot (+https://x.com)"}})
    with pytest.raises(ConfigError, match="max_pages"):
        parse_config({**raw, "performance": {"max_pages": 99}})


def test_panel_columns_search_console_and_pagespeed_default_on():
    header = HEADER + ["search_console", "pagespeed"]
    [a, b] = parse_clients(header, [row(nombre="A") + ["sc-domain:a.com", ""],
                                    row(nombre="B", dominio="https://b.com/") + ["", "FALSE"]])
    assert a.cfg.search_console == "sc-domain:a.com" and a.cfg.perf.pagespeed is True
    assert b.cfg.perf.pagespeed is False
    [c] = parse_clients(header, [row(modo="competitor") + ["sc-domain:x.com", ""]])
    assert c.cfg is None and c.errors


# ---------- Panel de punta a punta con PSI y Search Console falsos ----------
def test_panel_run_writes_performance_and_search_console(monkeypatch, fixture_server, tmp_path, capsys):
    base = fixture_server.origin + "/seo.auditor/"
    header = HEADER + ["search_console"]
    svc = MemSheets({"P": {"Clientes": [header, row(nombre="Uno", dominio=base, spreadsheet_id="S1", delay_seconds="0") + ["sc-domain:uno.example"]]},
                     "S1": {"Config": []}})

    class Psi:
        def lab(self, url, strategy="mobile"):
            return {"score": 42, "lcp_ms": 5200.0, "cls": 0.1, "tbt_ms": 100.0, "fcp_ms": 1.0, "ttfb_ms": 100.0, "speed_index_ms": 1.0}

    class Gsc:
        def searchanalytics(self):
            return self

        def query(self, siteUrl, body):
            rows = [{"keys": [base + "about.html" if body["dimensions"] == ["page"] else "plomero"], "clicks": 1,
                     "impressions": 800, "ctr": 0.001, "position": 4}]
            return type("E", (), {"execute": lambda s: {"rows": rows}})()

    monkeypatch.setattr(sheets_mod, "build_services", lambda *a, **k: (svc, None, "sa@proyecto.iam"))
    monkeypatch.setattr(cli, "is_public_host", lambda h: True)
    monkeypatch.setattr(cli, "build_perf_clients", lambda: (Psi(), None))
    monkeypatch.setattr(cli, "build_gsc_service", lambda: Gsc())
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert cli.main(["--panel", "--panel-id", "P", "--output-dir", str(tmp_path)]) == 0
    out = capsys.readouterr()
    s1 = svc.books["S1"]
    assert len(s1["Rendimiento"]) >= 2 and s1["Rendimiento"][1][2] == base     # fila 1 reservada al encabezado
    assert [r[0] for r in s1["Search Console"][1:]] == ["pagina", "consulta"]
    estados = {r[ICOLS.index("regla_id")] for r in s1["Issues"][1:]}
    assert {"PERF-001", "PERF-004", "GSC-002"} <= estados
    bcols = next(t["columns"] for t in SCHEMA["panel"]["tabs"] if t["name"] == "Benchmark")
    assert svc.books["P"]["Benchmark"][1][bcols.index("perf_puntaje_movil")] == 42
    assert "uno.example" not in "\n".join(l for l in (out.out + out.err).splitlines() if not l.startswith("::add-mask::"))


def test_panel_run_continues_when_search_console_denies_access(monkeypatch, fixture_server, tmp_path, capsys):
    base = fixture_server.origin + "/seo.auditor/"
    header = HEADER + ["search_console"]
    svc = MemSheets({"P": {"Clientes": [header, row(nombre="Uno", dominio=base, spreadsheet_id="S1", delay_seconds="0") + ["sc-domain:uno.example"]]},
                     "S1": {"Config": [], "Search Console": [["tipo"], ["pagina", "dato viejo"]]}})

    class Denied:
        def searchanalytics(self):
            raise RuntimeError("403")

    monkeypatch.setattr(sheets_mod, "build_services", lambda *a, **k: (svc, None, "sa@proyecto.iam"))
    monkeypatch.setattr(cli, "is_public_host", lambda h: True)
    monkeypatch.setattr(cli, "build_perf_clients", lambda: (None, None))
    monkeypatch.setattr(cli, "build_gsc_service", lambda: Denied())
    assert cli.main(["--panel", "--panel-id", "P", "--output-dir", str(tmp_path)]) == 0
    assert "permiso" in capsys.readouterr().err
    assert svc.books["S1"]["Search Console"][1] == ["pagina", "dato viejo"]      # no se pisó
    assert len(svc.books["S1"]["Issues"]) > 1                                    # el resto se publicó igual
