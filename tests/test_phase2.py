"""Fase 2: puntaje, diff entre corridas, reglas TECH-007 / SCH-001 / INT-001 y plataforma."""

import pytest

from seo_auditor.checks import run_checks
from seo_auditor.models import CrawlResult, Issue, PageRecord
from seo_auditor.platform import detect_platform, limit_for, load_platforms
from seo_auditor.report import build_tabs, load_schema
from seo_auditor.rules import load_rules
from seo_auditor.score import compute_score
from seo_auditor.sheets import SheetsPublisher
from seo_auditor.state import PreviousState, annotate, issue_key, parse_previous, resolved_rows
from seo_auditor.urls import Scope

W = {"critical": 10, "high": 5, "medium": 2, "low": 1}
RULES = load_rules()
SCHEMA = load_schema()
BASE = "https://x.com/"


def iss(sev="low", rule="ONP-003", url="https://x.com/a", target="", hat="white"):
    return Issue(rule, url, sev, "onpage", target=target, hat=hat)


# ---------- puntaje ----------
def test_score_is_100_without_issues_and_survives_zero_urls():
    assert compute_score([], 50, W) == 100.0
    assert compute_score([iss("critical")], 0, W) <= 100.0


def test_score_decreases_with_severity_and_count():
    base = compute_score([iss("low")], 100, W)
    assert compute_score([iss("low"), iss("low")], 100, W) < base
    assert compute_score([iss("critical")], 100, W) < base


def test_score_does_not_depend_on_site_size():
    small = compute_score([iss("high")] * 10, 100, W)
    big = compute_score([iss("high")] * 100, 1000, W)
    assert small == big


def test_score_ignores_risk_signals_and_stays_in_range():
    assert compute_score([iss("critical", hat="signal")] * 50, 10, W) == 100.0
    worst = compute_score([iss("critical")] * 10_000, 1, W)
    assert 0.0 <= worst <= 100.0


def test_score_reference_values():
    fixture_like = [iss("critical")] + [iss("high")] * 6 + [iss("medium")] * 10 + [iss("low")] * 4
    assert compute_score(fixture_like, 19, W) == 18.6      # sitio roto a propósito
    assert compute_score([iss("low")] * 2, 100, W) == 99.0  # sitio casi sano


# ---------- estado entre corridas ----------
def test_issue_key_is_stable_and_distinguishes_targets():
    assert issue_key("R", "u", "t") == issue_key("R", "u", "t")
    assert issue_key("R", "u", "t1") != issue_key("R", "u", "t2")


def _prev_row(rule, url, first="2026-01-01", estado="nuevo", target=""):
    cols = SCHEMA["tabs"][2]["columns"]
    row = dict.fromkeys(cols, "")
    row.update(regla_id=rule, url=url, primera_vez_visto=first, estado=estado, issue_key=issue_key(rule, url, target))
    return [row[c] for c in cols]


def _history(domain, score):
    cols = SCHEMA["tabs"][3]["columns"]
    row = dict.fromkeys(cols, "")
    row.update(dominio=domain, puntaje=score)
    return [row[c] for c in cols]


ICOLS = SCHEMA["tabs"][2]["columns"]
HCOLS = SCHEMA["tabs"][3]["columns"]


def test_first_run_everything_is_new():
    out = annotate([iss()], None, "t1")
    assert [(e, f) for _, _, e, f in out] == [("nuevo", "t1")]


def test_recurring_new_and_resolved():
    prev = parse_previous([_prev_row("ONP-003", "https://x.com/a", first="t0"),
                           _prev_row("ONP-001", "https://x.com/b")], [], BASE, ICOLS, HCOLS)
    current = [iss(rule="ONP-003", url="https://x.com/a"), iss(rule="ONP-004", url="https://x.com/c")]
    out = annotate(current, prev, "t2")
    assert [(i.rule_id, e, f) for i, _, e, f in out] == [("ONP-003", "recurrente", "t0"), ("ONP-004", "nuevo", "t2")]
    gone = resolved_rows({k for _, k, _, _ in out}, prev)
    assert [g["regla_id"] for g in gone] == ["ONP-001"]


def test_previous_ignores_rows_without_key_and_already_resolved():
    no_key = _prev_row("ONP-003", "https://x.com/a")
    no_key[ICOLS.index("issue_key")] = ""
    resolved = _prev_row("ONP-001", "https://x.com/b", estado="resuelto")
    prev = parse_previous([no_key, resolved], [], BASE, ICOLS, HCOLS)
    assert prev.rows == {}


def test_last_score_parses_comma_filters_domain_and_skips_blanks():
    hist = [_history(BASE, "50,5"), _history("https://otro.com/", "10"), _history(BASE, ""), _history(BASE, "61.2")]
    assert parse_previous([], hist, BASE, ICOLS, HCOLS).last_score == 61.2
    assert parse_previous([], [_history(BASE, "")], BASE, ICOLS, HCOLS).last_score is None


def _result(truncated=False, platform="", finished="t"):
    r = CrawlResult(name="c", domain=BASE, mode="own", started_at=finished, finished_at=finished,
                    truncated=truncated, platform=platform)
    r.pages[BASE] = PageRecord(url=BASE, status=200, is_html=True)
    return r


def test_truncated_crawl_never_marks_issues_as_resolved():
    prev = parse_previous([_prev_row("ONP-001", "https://x.com/b")], [], BASE, ICOLS, HCOLS)
    tabs = build_tabs(_result(truncated=True), [], "R2", previous=prev)
    assert tabs["Issues"] == []
    tabs = build_tabs(_result(truncated=False), [], "R2", previous=prev)
    assert [r[ICOLS.index("estado")] for r in tabs["Issues"]] == ["resuelto"]


def test_platform_columns_in_tabs():
    platforms = load_platforms()
    tabs = build_tabs(_result(platform="google_sites"),
                      [iss("medium", "TECH-010", "https://x.com/p"), iss("low", "ONP-003")],
                      "R1", platforms=platforms)
    assert tabs["Resumen"][0][SCHEMA["tabs"][1]["columns"].index("plataforma")] == "Google Sites"
    fix = {r[ICOLS.index("regla_id")]: r[ICOLS.index("arreglable_en_plataforma")] for r in tabs["Issues"]}
    assert fix["TECH-010"].startswith("limitado en Google Sites")
    assert fix["ONP-003"] == ""   # sin dato: no se afirma que sea arreglable


# ---------- planilla en memoria: tres corridas seguidas ----------
class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class MemSheets:
    def __init__(self):
        self.tabs = {"Config": []}

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kw):
        if "range" in kw:
            tab = kw["range"].split("'")[1]
            return _Exec(lambda: {"values": [list(r) for r in self.tabs.get(tab, [])[1:]]})
        return _Exec(lambda: {"sheets": [{"properties": {"sheetId": i, "title": t, "index": i}}
                                         for i, t in enumerate(self.tabs)]})

    def batchUpdate(self, spreadsheetId, body):
        for req in body["requests"]:
            if "addSheet" in req:
                self.tabs.setdefault(req["addSheet"]["properties"]["title"], [])
        return _Exec(lambda: {})

    def update(self, spreadsheetId, range, valueInputOption, body):
        tab, start = range.split("'")[1], range.split("!")[1]
        vals = [list(r) for r in body["values"]]
        if start == "A1":
            self.tabs[tab] = [vals[0]] + self.tabs[tab][1:]
        else:
            self.tabs[tab] = self.tabs[tab][:1] + vals
        return _Exec(lambda: {})

    def clear(self, spreadsheetId, range, body):
        tab = range.split("'")[1]
        self.tabs[tab] = self.tabs[tab][:1]
        return _Exec(lambda: {})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        tab = range.split("'")[1]
        self.tabs[tab] = (self.tabs[tab] or [[]]) + [list(r) for r in body["values"]]
        return _Exec(lambda: {})


def _run(pub, issues, score, when):
    previous = pub.read_previous(BASE)
    delta = None if previous.last_score is None else round(score - previous.last_score, 1)
    tabs = build_tabs(_result(finished=when), issues, f"R-{when}", schema=SCHEMA, previous=previous,
                      score=score, delta=delta)
    pub.write_all(tabs)
    return previous, tabs


def test_three_consecutive_runs_track_new_recurring_and_resolved():
    mem = MemSheets()
    pub = SheetsPublisher(mem, "SID", SCHEMA)
    pub.ensure_tabs()
    est = lambda tabs: sorted((r[ICOLS.index("regla_id")], r[ICOLS.index("estado")]) for r in tabs["Issues"])

    a, b, c = iss(rule="ONP-001", url="https://x.com/a"), iss(rule="ONP-003", url="https://x.com/a"), \
        iss(rule="ONP-004", url="https://x.com/b")

    prev, tabs = _run(pub, [a, b], 80.0, "t1")
    assert prev.last_score is None and est(tabs) == [("ONP-001", "nuevo"), ("ONP-003", "nuevo")]

    prev, tabs = _run(pub, [a, c], 85.0, "t2")
    assert prev.last_score == 80.0
    assert est(tabs) == [("ONP-001", "recurrente"), ("ONP-003", "resuelto"), ("ONP-004", "nuevo")]
    first_seen = {r[ICOLS.index("regla_id")]: r[ICOLS.index("primera_vez_visto")] for r in tabs["Issues"]}
    assert first_seen["ONP-001"] == "t1"        # se conserva la primera vez

    prev, tabs = _run(pub, [c], 90.0, "t3")
    assert prev.last_score == 85.0
    # ONP-003 ya se informó como resuelto una vez: no vuelve a aparecer
    assert est(tabs) == [("ONP-001", "resuelto"), ("ONP-004", "recurrente")]

    assert len(mem.tabs["Historico"]) == 4       # encabezado + 3 corridas
    delta_col = SCHEMA["tabs"][1]["columns"].index("delta_puntaje_vs_anterior")
    assert [r[delta_col] for r in mem.tabs["Resumen"][1:]] == ["", 5.0, 5.0]


# ---------- reglas de fase 2 ----------
def _page(path, **kw):
    kw.setdefault("status", 200)
    kw.setdefault("is_html", True)
    kw.setdefault("title", "T " + path)
    kw.setdefault("meta_description", "d")
    kw.setdefault("h1_count", 1)
    return PageRecord(url=BASE + path, **kw)


def _crawl(*pages, sitemap=(), truncated=False):
    r = CrawlResult(name="c", domain=BASE, mode="own", truncated=truncated)
    r.pages = {p.url: p for p in pages}
    r.sitemap_urls = [BASE + s for s in sitemap]
    return run_checks(r, RULES, Scope(BASE))


def _ids(issues, rule):
    return [i.url.removeprefix(BASE) for i in issues if i.rule_id == rule]


def test_orphan_rules():
    home = _page("", links=[BASE + "linked"])
    linked, lonely = _page("linked"), _page("lonely")
    assert _ids(_crawl(home, linked, lonely, sitemap=["linked", "lonely"]), "TECH-007") == ["lonely"]
    # el inicio nunca es huérfano, aunque nadie lo enlace
    assert _ids(_crawl(_page(""), sitemap=[""]), "TECH-007") == []
    # llegar por redirección cuenta como estar enlazada
    redirecting = _page("go", redirect_to=BASE + "dest", redirect_kind="meta")
    assert _ids(_crawl(home, redirecting, _page("dest"), sitemap=["dest"]), "TECH-007") == []
    # con el crawl truncado faltan enlaces: no se acusa a nadie
    assert _ids(_crawl(home, lonely, sitemap=["lonely"], truncated=True), "TECH-007") == []


def test_jsonld_validation():
    ok = _page("ok", jsonld=['{"@type": "Thing"}'])
    bad = _page("bad", jsonld=['{"a": 1,}'])
    empty = _page("empty", jsonld=["  "])
    issues = _crawl(ok, bad, empty)
    assert sorted(_ids(issues, "SCH-001")) == ["bad", "empty"]


def test_hreflang_return_links():
    en = _page("en", hreflang=[("en", BASE + "en"), ("es", BASE + "es")])
    es_without = _page("es")
    assert _ids(_crawl(en, es_without), "INT-001") == ["en"]
    es_with = _page("es", hreflang=[("en", BASE + "en"), ("es", BASE + "es")])
    assert _ids(_crawl(en, es_with), "INT-001") == []
    # alternativa no rastreada: no hay evidencia, no se acusa
    assert _ids(_crawl(en), "INT-001") == []


# ---------- plataforma ----------
@pytest.mark.parametrize("url,headers,html,expected", [
    ("https://sites.google.com/view/x", {}, "<html></html>", "google_sites"),
    ("https://a.com/", {}, '<meta name="generator" content="WordPress 6.5">', "wordpress"),
    ("https://a.com/", {}, '<img src="https://cdn.shopify.com/s/files/x.png">', "shopify"),
    ("https://a.com/", {}, '<img src="https://static.wixstatic.com/x.png">', "wix"),
    ("https://a.github.io/p/", {}, "<html></html>", "github_pages"),
    ("https://a.com/", {"server": "GitHub.com"}, "<html></html>", "github_pages"),
    ("https://a.com/", {}, "<html><body>nada especial</body></html>", ""),
])
def test_platform_detection(url, headers, html, expected):
    assert detect_platform(url, headers, html) == expected


def test_platform_limits_only_claim_known_limits():
    platforms = load_platforms()
    assert limit_for(platforms, "google_sites", "TECH-010").startswith("limitado en Google Sites")
    assert limit_for(platforms, "wordpress", "TECH-010") == ""
    assert limit_for(platforms, "", "TECH-010") == ""
    assert limit_for(platforms, "inventada", "TECH-010") == ""
