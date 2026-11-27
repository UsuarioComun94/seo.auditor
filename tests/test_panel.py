"""Panel (planilla maestra), pestaña Crawl, puntaje comparable y modo --panel de punta a punta."""

import pytest

from seo_auditor import __main__ as cli
from seo_auditor import sheets as sheets_mod
from seo_auditor.models import Issue
from seo_auditor.panel import SheetsPanel, parse_clients
from seo_auditor.report import crawl_rows, load_schema
from seo_auditor.rules import load_rules
from seo_auditor.score import compute_comparable_score, compute_score
from seo_auditor.sheets import PublishError, SheetsPublisher
from fakes import MemSheets

SCHEMA = load_schema()
HEADER = ["nombre", "dominio", "modo", "autorizado", "max_urls", "delay_seconds", "render_js",
          "robots_url", "spreadsheet_id", "activo", "notas"]
W = SCHEMA["severity_weights"]


def row(**kw):
    base = dict(nombre="Sitio", dominio="https://a.com/", modo="own", autorizado="", max_urls="",
                delay_seconds="", render_js="", robots_url="", spreadsheet_id="SID", activo="TRUE", notas="")
    base.update(kw)
    return [base[h] for h in HEADER]


# ---------- parse_clients ----------
def test_parse_valid_own_and_defaults():
    [e] = parse_clients(HEADER, [row()])
    assert e.active and not e.errors
    assert (e.cfg.mode, e.cfg.crawl.max_urls, e.cfg.crawl.delay_seconds) == ("own", 1000, 0.5)


def test_competitor_defaults_are_polite_and_enforced():
    [e] = parse_clients(HEADER, [row(modo="competitor")])
    assert (e.cfg.crawl.delay_seconds, e.cfg.crawl.max_urls) == (2.0, 500)
    [bad] = parse_clients(HEADER, [row(modo="competitor", delay_seconds="0.1")])
    assert bad.cfg is None and bad.errors


def test_client_requires_authorization():
    [e] = parse_clients(HEADER, [row(modo="client")])
    assert e.cfg is None and e.errors
    [ok] = parse_clients(HEADER, [row(modo="client", autorizado="TRUE")])
    assert ok.cfg is not None


def test_inactive_rows_are_not_validated_and_blank_rows_ignored():
    entries = parse_clients(HEADER, [row(activo="FALSE", dominio="basura"), [], ["", ""]])
    assert len(entries) == 1 and not entries[0].active and not entries[0].errors


def test_one_invalid_row_does_not_block_others():
    entries = parse_clients(HEADER, [row(nombre="A", dominio="no es url"), row(nombre="B")])
    assert entries[0].errors and entries[1].cfg is not None


def test_duplicate_names_and_missing_sheet_id():
    entries = parse_clients(HEADER, [row(nombre="X"), row(nombre="x", dominio="https://b.com/")])
    assert entries[1].errors == ["nombre repetido"]
    [e] = parse_clients(HEADER, [row(spreadsheet_id="")])
    assert e.cfg is None and e.errors


def test_columns_are_read_by_name_and_decimal_comma_accepted():
    header = ["activo", "spreadsheet_id", "modo", "dominio", "nombre", "delay_seconds"]
    [e] = parse_clients(header, [["si", "S", "own", "https://a.com/", "Z", "1,5"]])
    assert e.cfg.crawl.delay_seconds == 1.5


def test_missing_required_column_fails_clearly():
    with pytest.raises(PublishError, match="spreadsheet_id"):
        parse_clients(["nombre", "dominio", "modo", "activo"], [])


# ---------- SheetsPanel ----------
def test_panel_renames_first_sheet_and_upserts_by_name():
    svc = MemSheets({"P": {"SEO Auditor – Panel": [HEADER, row()]}})
    panel = SheetsPanel(svc, "P", SCHEMA)
    panel.ensure_tabs()
    assert set(svc.books["P"]) == {"Clientes", "Comparativa", "Benchmark"}
    assert len(panel.read_clients()) == 1
    r = lambda n, p: {"nombre": n, "dominio": "d", "modo": "own", "puntaje": p}
    panel.upsert_comparativa([r("A", 50), r("B", 60)])
    panel.upsert_comparativa([r("a", 70)])      # actualiza A (sin distinguir mayúsculas), conserva B
    rows = svc.books["P"]["Comparativa"][1:]
    assert len(rows) == 2
    assert {x[0].casefold(): x[5] for x in rows} == {"a": 70, "b": 60}


# ---------- Crawl / filas / puntaje comparable ----------
def test_crawl_rows_cap_and_width():
    from seo_auditor.models import CrawlResult, PageRecord
    r = CrawlResult(name="c", domain="https://x.com/", mode="own")
    for i in range(30):
        u = f"https://x.com/{i}"
        r.pages[u] = PageRecord(url=u, status=200, is_html=True, title="=cmd")
    cols = next(t["columns"] for t in SCHEMA["tabs"] if t["name"] == "Crawl")
    rows = crawl_rows(r, cols, 10)
    assert len(rows) == 10 and all(len(x) == len(cols) for x in rows)


def test_publisher_resizes_grid_and_chunks_large_crawl(monkeypatch):
    monkeypatch.setattr(sheets_mod, "CHUNK_ROWS", 100)
    svc = MemSheets({"S": {"Config": [], "Resumen": [], "Issues": [], "Historico": [], "Riesgo": [], "Crawl": []}},
                    grid_rows=50)
    n = 1234
    SheetsPublisher(svc, "S", SCHEMA).write_tab("Crawl", [[i, 200] for i in range(n)])
    assert len(svc.books["S"]["Crawl"]) == n + 1   # fila 1 reservada al encabezado
    assert all(w[3] == "RAW" for w in svc.writes)


def test_comparable_score_ignores_rules_not_valid_in_every_mode():
    rules = load_rules()
    only_own = next(r for r in rules.values() if "competitor" not in r.modes)
    everywhere = next(r for r in rules.values() if {"own", "client", "competitor"} <= set(r.modes))
    issues = [Issue(only_own.id, "u", "critical", "x"), Issue(everywhere.id, "v", "low", "x")]
    comp = compute_comparable_score(issues, 10, W, rules)
    assert comp > compute_score(issues, 10, W)
    assert comp == compute_score([issues[1]], 10, W)


# ---------- modo --panel de punta a punta ----------
def test_mask_only_inside_github_actions(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    cli.mask("secreto")
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    cli.mask("secreto", "", None)
    assert capsys.readouterr().out.strip() == "::add-mask::secreto"


@pytest.fixture
def panel_env(monkeypatch, fixture_server):
    base = fixture_server.origin + "/seo.auditor/"
    svc = MemSheets({
        "P": {"Clientes": [HEADER, row(nombre="Uno", dominio=base, spreadsheet_id="S1", delay_seconds="0"),
                           row(nombre="Malo", dominio="no es url", spreadsheet_id="S2"),
                           row(nombre="Apagado", activo="FALSE", spreadsheet_id="S3")]},
        "S1": {"Config": []},
    })
    monkeypatch.setattr(sheets_mod, "build_services", lambda *a, **k: (svc, None, "sa@proyecto.iam"))
    monkeypatch.setattr(cli, "is_public_host", lambda h: True)   # el servidor local es loopback
    monkeypatch.setattr(cli, "build_perf_clients", lambda: (None, None))   # sin red en los tests
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    return svc


def test_panel_run_publishes_site_sheet_and_comparativa_and_masks(panel_env, tmp_path, capsys):
    code = cli.main(["--panel", "--panel-id", "P", "--output-dir", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 2                                   # fila inválida -> error, pero no frenó a "Uno"
    s1 = panel_env.books["S1"]
    assert len(s1["Crawl"]) > 1 and len(s1["Issues"]) > 1 and len(s1["Resumen"]) == 2
    comp = panel_env.books["P"]["Comparativa"]
    assert [r[0] for r in comp[1:]] == ["Uno"]
    assert "::add-mask::Uno" in out.out and "::add-mask::P" in out.out and "::add-mask::sa@proyecto.iam" in out.out
    # nada sensible en los logs, y solo la máscara puede contener los nombres
    visible = "\n".join(l for l in (out.out + out.err).splitlines() if not l.startswith("::add-mask::"))
    assert "Uno" not in visible and "127.0.0.1" not in visible and "S1" not in visible


def test_panel_second_run_marks_issues_recurrent(panel_env, tmp_path, capsys):
    cli.main(["--panel", "--panel-id", "P", "--site", "Uno", "--output-dir", str(tmp_path)])
    cli.main(["--panel", "--panel-id", "P", "--site", "uno", "--output-dir", str(tmp_path)])
    capsys.readouterr()
    issues = panel_env.books["S1"]["Issues"]
    col = next(t["columns"] for t in SCHEMA["tabs"] if t["name"] == "Issues").index("estado")
    assert {r[col] for r in issues[1:]} == {"recurrente"}
    assert len(panel_env.books["S1"]["Resumen"]) == 3          # encabezado + 2 corridas
    assert len(panel_env.books["P"]["Comparativa"]) == 2       # sin duplicar la fila


def test_panel_requires_id_and_unknown_site_fails(panel_env, capsys, monkeypatch):
    monkeypatch.delenv("SEO_PANEL_ID", raising=False)
    assert cli.main(["--panel", "--panel-id", ""]) == 2
    assert cli.main(["--panel", "--panel-id", "P", "--site", "no-existe"]) == 2


def test_ssrf_blocked_site_is_skipped(panel_env, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "is_public_host", lambda h: False)
    cli.main(["--panel", "--panel-id", "P", "--output-dir", str(tmp_path)])
    assert "Crawl" not in panel_env.books["S1"] or len(panel_env.books["S1"].get("Crawl", [])) == 0


# ---------- Benchmark ----------
def _bench_result():
    from seo_auditor.models import CrawlResult, PageRecord
    r = CrawlResult(name="c", domain="https://x.com/", mode="competitor", robots_status=200,
                    sitemap_urls=["https://x.com/a"])
    r.pages["https://x.com/a"] = PageRecord(url="https://x.com/a", status=200, is_html=True, title="t",
                                            meta_description="d", h1_count=1, canonical="https://x.com/a",
                                            in_sitemap=True, response_ms=100, depth=1, links=["l1", "l2"],
                                            images=[{"src": "i", "has_alt": True}, {"src": "j", "has_alt": False}])
    r.pages["https://x.com/b"] = PageRecord(url="https://x.com/b", status=200, is_html=True, h1_count=2,
                                            response_ms=300, depth=2)
    r.pages["https://x.com/c"] = PageRecord(url="https://x.com/c", status=404, response_ms=50)
    return r


def test_benchmark_percentages_and_unmeasurable_is_none():
    from seo_auditor.benchmark import METRICS, compute_benchmark
    b = compute_benchmark(_bench_result())
    assert set(b) == set(METRICS)
    assert (b["paginas_html"], b["pct_title"], b["pct_h1_unico"]) == (2, 50.0, 50.0)
    assert b["pct_imagenes_con_alt"] == 50.0 and b["pct_en_sitemap"] == 50.0
    assert b["pct_errores_4xx_5xx"] == 33.3 and b["tiene_robots"] and b["ms_mediana"] == 100
    assert b["pct_schema_jsonld"] == 0.0            # medible y es 0
    from seo_auditor.models import CrawlResult
    empty = compute_benchmark(CrawlResult(name="e", domain="https://e.com/", mode="own"))
    assert empty["pct_title"] is None and empty["ms_mediana"] is None   # no medible != 0


def test_benchmark_none_becomes_empty_cell_and_schema_matches():
    svc = MemSheets({"P": {"Clientes": [HEADER], "Benchmark": [], "Comparativa": []}})
    panel = SheetsPanel(svc, "P", SCHEMA)
    cols = next(t["columns"] for t in SCHEMA["panel"]["tabs"] if t["name"] == "Benchmark")
    panel.upsert_benchmark([{"nombre": "A", "modo": "own", "pct_title": None, "paginas_html": 0}])
    r = svc.books["P"]["Benchmark"][1]   # la fila 1 queda reservada al encabezado
    assert len(r) == len(cols) and r[cols.index("pct_title")] == "" and r[cols.index("paginas_html")] == 0


def test_panel_run_fills_benchmark(panel_env, tmp_path, capsys):
    cli.main(["--panel", "--panel-id", "P", "--site", "Uno", "--output-dir", str(tmp_path)])
    capsys.readouterr()
    rows = panel_env.books["P"]["Benchmark"]
    assert [r[0] for r in rows[1:]] == ["Uno"] and rows[1][1] == "own"


def test_comparar_googlebot_is_optional_and_forbidden_for_competitors():
    header = HEADER + ["comparar_googlebot"]
    [ok] = parse_clients(header, [row() + ["TRUE"]])
    assert ok.cfg.crawl.compare_googlebot_ua is True
    [bad] = parse_clients(header, [row(modo="competitor") + ["TRUE"]])
    assert bad.cfg is None and bad.errors
    [none] = parse_clients(HEADER, [row()])               # sin la columna: apagado
    assert none.cfg.crawl.compare_googlebot_ua is False


def test_notes_in_public_logs_hide_urls(panel_env, tmp_path, capsys):
    cli.main(["--panel", "--panel-id", "P", "--output-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "http://" not in "\n".join(l for l in out.splitlines() if "Nota:" in l)
