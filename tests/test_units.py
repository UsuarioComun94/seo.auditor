import csv
import json

import pytest

from seo_auditor.models import CrawlResult, Issue, PageRecord
from seo_auditor.parser import parse_html
from seo_auditor.report import build_tabs, load_schema, write_local
from seo_auditor.sheets import PublishError, SheetsPublisher, _col, build_services
from seo_auditor.urls import Scope, canon_key, normalize_url, resolve


# ---------- urls ----------
def test_normalize_and_resolve():
    assert normalize_url("HTTP://Example.com:80/a#frag") == "http://example.com/a"
    assert normalize_url("https://example.com") == "https://example.com/"
    assert resolve("https://x.com/a/b.html", "../c.html") == "https://x.com/c.html"
    assert resolve("https://x.com/", "mailto:a@b.com") is None
    assert resolve("https://x.com/", "javascript:void(0)") is None
    assert resolve("https://x.com/", "#top") is None


def test_canon_key_ignores_index_html():
    assert canon_key("https://x.com/blog/index.html") == canon_key("https://x.com/blog/")


def test_scope_respects_path_prefix():
    s = Scope("https://x.github.io/proj/")
    assert s.contains("https://x.github.io/proj/a.html")
    assert not s.contains("https://x.github.io/otro/a.html")
    assert not s.contains("https://evil.com/proj/a.html")


# ---------- parser ----------
def test_parser_extracts_seo_fields():
    html = """<html><head><title> Hola   mundo </title>
    <meta name="description" content="desc"><meta name="robots" content="noindex">
    <meta http-equiv="refresh" content="0; url=/b.html">
    <link rel="canonical" href="/c"><link rel="alternate" hreflang="en" href="/en">
    <script type="application/ld+json">{"a": 1}</script></head>
    <body><h1>a</h1><h1>b</h1><a href="x.html">x</a><img src="i.png"><img src="j.png" alt=""></body></html>"""
    p = parse_html(html, "https://x.com/dir/p.html")
    assert p.title == "Hola mundo"
    assert p.meta_description == "desc" and "noindex" in p.meta_robots
    assert p.refresh_url == "https://x.com/b.html"
    assert p.canonical == "https://x.com/c"
    assert p.hreflang == [("en", "https://x.com/en")]
    assert p.h1_count == 2
    assert p.links == ["https://x.com/dir/x.html"]
    assert [i["has_alt"] for i in p.images] == [False, True]
    assert json.loads(p.jsonld[0]) == {"a": 1}


def test_parser_survives_broken_html():
    p = parse_html("<html><head><title>T</title><body><a href='a'", "https://x.com/")
    assert p.title == "T"


# ---------- reporte ----------
def _result():
    r = CrawlResult(name="c", domain="https://x.com/", mode="own", started_at="t0", finished_at="t1")
    r.pages["https://x.com/"] = PageRecord(url="https://x.com/", status=200, is_html=True,
                                           title="=HYPERLINK(\"http://evil\")")
    return r


def test_csv_neutralizes_formulas(tmp_path):
    issues = [Issue("ONP-001", "https://x.com/", "high", "onpage", detail="@cmd")]
    paths = write_local(tmp_path, _result(), issues, "RUN1")
    with paths["pages"].open(encoding="utf-8") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["title"].startswith("'=")
    with paths["issues"].open(encoding="utf-8") as fh:
        assert list(csv.DictReader(fh))[0]["detail"].startswith("'@")


def test_build_tabs_matches_schema_widths_and_keeps_risk_separate():
    issues = [Issue("ONP-001", "https://x.com/", "high", "onpage"),
              Issue("RSK-001", "https://x.com/", "high", "risk", hat="signal")]
    tabs = build_tabs(_result(), issues, "RUN1")
    schema = {t["name"]: len(t["columns"]) for t in load_schema()["tabs"]}
    for name, rows in tabs.items():
        assert all(len(r) == schema[name] for r in rows), name
    assert len(tabs["Issues"]) == 1 and len(tabs["Riesgo"]) == 1
    assert tabs["Resumen"][0][5:9] == [0, 1, 0, 0]  # las señales de riesgo no cuentan como issues


# ---------- sheets (cliente falso) ----------
class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeSheets:
    def __init__(self, titles):
        self.calls = []
        self._titles = list(titles)

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kw):
        return _Exec(lambda: {"sheets": [{"properties": {"sheetId": i, "title": t, "index": i}}
                                         for i, t in enumerate(self._titles)]})

    def batchUpdate(self, spreadsheetId, body):
        self.calls.append(("batchUpdate", body))
        for req in body["requests"]:
            if "addSheet" in req:
                self._titles.append(req["addSheet"]["properties"]["title"])
            if "updateSheetProperties" in req and "title" in req["updateSheetProperties"]["properties"]:
                self._titles[0] = req["updateSheetProperties"]["properties"]["title"]
        return _Exec(lambda: {})

    def update(self, **kw):
        self.calls.append(("update", kw))
        return _Exec(lambda: {})

    def append(self, **kw):
        self.calls.append(("append", kw))
        return _Exec(lambda: {})

    def clear(self, **kw):
        self.calls.append(("clear", kw))
        return _Exec(lambda: {})


def test_publish_creates_missing_tabs_and_renames_csv_sheet_to_config():
    svc = FakeSheets(["SEO Auditor – Fixture"])  # nombre que deja la importación del CSV
    pub = SheetsPublisher(svc, "SID", load_schema())
    pub.publish({"Resumen": [["r"]], "Issues": [["i"]], "Historico": [["h"]], "Riesgo": []})
    assert svc._titles[0] == "Config"
    assert {"Resumen", "Issues", "Historico", "Riesgo"} <= set(svc._titles)
    kinds = [c[0] for c in svc.calls]
    assert "append" in kinds and "clear" in kinds


def test_publish_is_idempotent_on_tabs():
    svc = FakeSheets(["Config", "Resumen", "Issues", "Historico", "Riesgo"])
    SheetsPublisher(svc, "SID", load_schema()).ensure_tabs()
    assert not any("addSheet" in r for c in svc.calls if c[0] == "batchUpdate" for r in c[1]["requests"])


def test_all_writes_are_raw_never_user_entered():
    svc = FakeSheets(["Config"])
    SheetsPublisher(svc, "SID", load_schema()).publish({"Resumen": [["=1+1"]], "Issues": [["=2"]],
                                                        "Historico": [["x"]], "Riesgo": [["y"]]})
    writes = [c[1] for c in svc.calls if c[0] in ("update", "append")]
    assert writes and all(w["valueInputOption"] == "RAW" for w in writes)


def test_replace_mode_clears_only_below_header():
    svc = FakeSheets(["Config", "Resumen", "Issues", "Historico", "Riesgo"])
    SheetsPublisher(svc, "SID", load_schema()).write_tab("Issues", [["a"]])
    clear = next(c[1] for c in svc.calls if c[0] == "clear")
    assert clear["range"].startswith("'Issues'!A2:")


def test_missing_credentials_fail_clearly(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    with pytest.raises(PublishError, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
        build_services()
    with pytest.raises(PublishError, match="JSON"):
        build_services("no es json")


def test_column_letters():
    assert [_col(1), _col(26), _col(27)] == ["A", "Z", "AA"]


# ---------- alias de URL (/ frente a /index.html) ----------
def test_index_html_alias_is_not_double_counted():
    from seo_auditor.checks import run_checks
    from seo_auditor.rules import load_rules

    base = "https://x.com/"
    root = PageRecord(url=base, status=200, is_html=True, title="Inicio", meta_description="d", h1_count=1,
                      canonical=base, links=[base + "rota.html"])
    alias = PageRecord(url=base + "index.html", status=200, is_html=True, title="Inicio", meta_description="d",
                       h1_count=1, canonical=base, links=[base + "rota.html"])
    rota = PageRecord(url=base + "rota.html", status=404)
    r = CrawlResult(name="c", domain=base, mode="own")
    r.pages = {p.url: p for p in (root, alias, rota)}
    issues = run_checks(r, load_rules(), Scope(base))
    assert [i.rule_id for i in issues].count("TECH-001") == 1
    assert "ONP-002" not in {i.rule_id for i in issues}


def test_same_title_without_canonical_is_still_flagged():
    from seo_auditor.checks import run_checks
    from seo_auditor.rules import load_rules

    base = "https://x.com/"
    mk = lambda u: PageRecord(url=u, status=200, is_html=True, title="Igual", meta_description="d", h1_count=1)
    r = CrawlResult(name="c", domain=base, mode="own")
    r.pages = {u: mk(u) for u in (base, base + "index.html")}
    assert "ONP-002" in {i.rule_id for i in run_checks(r, load_rules(), Scope(base))}
