"""CLI del auditor.

Dos modos:
  --config clients/x.yaml   un sitio desde un YAML (el fixture público, pruebas locales)
  --panel                   todos los sitios activos de la planilla maestra (Drive); publica siempre

Códigos de salida: 0 ok | 2 config inválida | 3 faltan issues esperados (fixture)
                   4 falló la publicación a Sheets | 5 crawl abortado
Con varios sitios, el código es el mayor de todos.

PRIVACIDAD: el repo es público y los logs de GitHub Actions también. En modo --panel los nombres,
dominios e IDs se ocultan con ::add-mask:: ANTES de imprimir nada, y no se imprime cada URL.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import __version__
from .benchmark import compute_benchmark
from .checks import run_checks
from .config import ClientConfig, ConfigError, load_config
from .crawler import CrawlAbort, Crawler
from .expected import check_expected
from .fetcher import host_problem, is_public_host
from .models import CrawlResult
from .platform import load_platforms, platform_label
from .report import build_tabs, count_by_severity, load_schema, new_run_id, write_local
from .rules import load_rules
from .score import DEFAULT_SCALE, compute_comparable_score, compute_score
from .urls import Scope


def mask(*values) -> None:
    """Pide a GitHub Actions que oculte estos valores en los logs. Fuera de Actions no hace nada."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for v in values:
        v = str(v or "").strip()
        if v:
            print(f"::add-mask::{v}", flush=True)


def schema_idx(schema: dict, tab: str, column: str) -> int:
    return next(t["columns"].index(column) for t in schema["tabs"] if t["name"] == tab)


@dataclass
class Context:
    rules: dict
    schema: dict
    platforms: dict
    output_dir: str
    quiet: bool
    _services: tuple | None = None

    def services(self):
        """Clientes de Sheets y Drive, creados una sola vez."""
        from .sheets import build_services

        if self._services is None:
            self._services = build_services()
            mask(self._services[2])  # el mail del service account revela el ID del proyecto de Google Cloud
        return self._services


@dataclass
class SiteOutcome:
    code: int = 0
    cfg: ClientConfig | None = None
    result: CrawlResult | None = None
    issues: list = field(default_factory=list)
    score: float | None = None
    comparable: float | None = None
    counts: dict = field(default_factory=dict)


def audit_site(cfg: ClientConfig, ctx: Context, *, publish: bool, upload_csv: bool, check_public: bool,
               expected: str | None = None, label: str = "") -> SiteOutcome:
    out = SiteOutcome(cfg=cfg)
    pre = f"[{label}] " if label else ""

    if check_public and not is_public_host(urlsplit(cfg.domain).hostname or ""):
        # Anti-SSRF: el runner no debe consultar redes privadas ni el endpoint de metadatos de la nube
        why = host_problem(urlsplit(cfg.domain).hostname or "") or "no es un host público"
        print(f"ERROR {pre}se omite: el dominio {why}", file=sys.stderr)
        out.code = 2
        return out

    run_id = new_run_id()
    crawler = Crawler(cfg, log=(lambda m: None) if ctx.quiet else print)
    try:
        result = crawler.run()
    except CrawlAbort as exc:
        print(f"ERROR {pre}crawl abortado: {exc}", file=sys.stderr)
        out.code = 5
        return out

    weights = ctx.schema.get("severity_weights", {})
    scale = ctx.schema.get("score_scale", DEFAULT_SCALE)
    issues = run_checks(result, ctx.rules, Scope(cfg.domain))
    counts = count_by_severity(issues)
    score = compute_score(issues, len(result.pages), weights, scale)
    comparable = compute_comparable_score(issues, len(result.pages), weights, ctx.rules, scale)
    paths = write_local(ctx.output_dir, result, issues, run_id, score=score)
    out.result, out.issues, out.score, out.comparable, out.counts = result, issues, score, comparable, counts

    print(f"\n{pre}Rastreadas {len(result.pages)} URLs ({crawler.fetcher.requests_made} pedidos)"
          f"{' [TRUNCADO por max_urls]' if result.truncated else ''}")
    print(f"{pre}Plataforma: {platform_label(ctx.platforms, result.platform) if result.platform else 'no detectada'}")
    print(f"{pre}Issues: {counts['critical']} críticos, {counts['high']} altos, {counts['medium']} medios, {counts['low']} bajos")
    print(f"{pre}Puntaje: {score} (comparable: {comparable})")
    for note in result.notes:
        print(f"{pre}Nota: {note}")
    if upload_csv:
        print(f"{pre}CSV completos en {paths['pages'].parent}")

    if publish:
        from .sheets import PublishError, SheetsPublisher, upload_csv_to_drive

        try:
            if not cfg.sheets.spreadsheet_id:
                raise PublishError("la config no tiene sheets.spreadsheet_id")
            sheets_svc, drive_svc, sa_email = ctx.services()
            link = upload_csv_to_drive(drive_svc, cfg.sheets.drive_folder_id, paths["pages"],
                                       f"{cfg.name}-{run_id}-pages.csv") if upload_csv else ""
            publisher = SheetsPublisher(sheets_svc, cfg.sheets.spreadsheet_id, ctx.schema)
            publisher.ensure_tabs()
            previous = publisher.read_previous(cfg.domain)
            delta = None
            if previous.last_score is not None:
                delta = round(score - previous.last_score, 1)
                print(f"{pre}Puntaje anterior: {previous.last_score} (cambio: {delta:+})")
            csv_link = link or ("ver artifact del workflow" if upload_csv else "ver pestaña Crawl")
            tabs = build_tabs(result, issues, run_id, csv_link=csv_link, schema=ctx.schema,
                              previous=previous, score=score, delta=delta, platforms=ctx.platforms)
            publisher.write_all(tabs)
            col = schema_idx(ctx.schema, "Issues", "estado")
            estados = [r[col] for r in tabs["Issues"]]
            print(f"{pre}Estado de issues: "
                  + (", ".join(f"{n} {e}" for e in ("nuevo", "recurrente", "resuelto") if (n := estados.count(e))) or "sin issues"))
            print(f"{pre}Publicado en la planilla del sitio ({len(tabs['Crawl'])} filas en Crawl)")
        except PublishError as exc:
            print(f"ERROR {pre}publicación: {exc}", file=sys.stderr)
            out.code = 4
        except Exception as exc:  # noqa: BLE001 - se muestra el motivo y se falla con código propio
            print(f"ERROR {pre}publicación a Google falló: {type(exc).__name__}: {str(exc)[:500]}", file=sys.stderr)
            out.code = 4

    if expected:
        report = check_expected(issues, expected, ctx.rules, cfg.mode)
        print(f"\nFixture: {report.found}/{report.checked} issues esperados detectados")
        if report.skipped:
            print("No evaluados: " + ", ".join(report.skipped))
        for exp in report.missing:
            print(f"  FALTA {exp['rule']} en {exp['url'] or '/'}"
                  + (f" → {exp['target']}" if exp.get("target") else ""), file=sys.stderr)
        if not report.ok:
            out.code = out.code or 3
    return out


def run_panel(args, ctx: Context) -> int:
    from .panel import SheetsPanel
    from .sheets import PublishError

    panel_id = (args.panel_id or "").strip()
    if not panel_id:
        print("ERROR: falta el ID de la planilla Panel (--panel-id o la variable SEO_PANEL_ID)", file=sys.stderr)
        return 2
    mask(panel_id)

    try:
        sheets_svc, _, _ = ctx.services()
        panel = SheetsPanel(sheets_svc, panel_id, ctx.schema)
        panel.ensure_tabs()
        entries = panel.read_clients()
    except PublishError as exc:
        print(f"ERROR: Panel: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: no se pudo leer el Panel: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 4

    # Primero ocultar, después imprimir: nada de lo que sigue puede filtrar nombres, dominios o IDs.
    for e in entries:
        mask(e.name)
        if e.cfg:
            mask(e.cfg.name, e.cfg.domain, urlsplit(e.cfg.domain).hostname, e.cfg.sheets.spreadsheet_id,
                 e.cfg.sheets.drive_folder_id)

    code = 0
    for e in entries:
        if e.active and e.errors:
            print(f"ERROR fila {e.row} del Panel: " + "; ".join(e.errors), file=sys.stderr)
            code = max(code, 2)

    wanted = (args.site or "all").strip().casefold()
    valid = [e for e in entries if e.active and e.cfg and (wanted == "all" or e.name.casefold() == wanted)]
    inactive = sum(1 for e in entries if not e.active)
    print(f"Panel: {len(valid)} sitio(s) a auditar, {inactive} inactivo(s)")
    if wanted != "all" and not valid:
        print("ERROR: no hay un sitio activo y válido con ese nombre", file=sys.stderr)
        return max(code, 2)
    if args.validate_only:
        return code

    outcomes: list[SiteOutcome] = []
    for i, e in enumerate(valid, 1):
        out = audit_site(e.cfg, ctx, publish=True, upload_csv=False, check_public=True, label=f"sitio {i}/{len(valid)}")
        outcomes.append(out)
        code = max(code, out.code)

    rows = [{
        "nombre": o.cfg.name, "dominio": o.cfg.domain, "modo": o.cfg.mode,
        "ultima_corrida_utc": o.result.finished_at, "urls_rastreadas": len(o.result.pages),
        "puntaje": o.score, "puntaje_comparable": o.comparable,
        "criticos": o.counts["critical"], "altos": o.counts["high"], "medios": o.counts["medium"],
        "bajos": o.counts["low"],
        "plataforma": platform_label(ctx.platforms, o.result.platform) if o.result.platform else "",
    } for o in outcomes if o.result is not None]
    bench = [{"nombre": o.cfg.name, "modo": o.cfg.mode, "ultima_corrida_utc": o.result.finished_at,
              **compute_benchmark(o.result)} for o in outcomes if o.result is not None]
    if rows:
        try:
            panel.upsert_comparativa(rows)
            panel.upsert_benchmark(bench)
            print(f"Comparativa y Benchmark actualizados ({len(rows)} sitio(s))")
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: no se pudo actualizar la Comparativa: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            code = max(code, 4)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seo_auditor", description="Auditor SEO autónomo")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="Ruta al YAML de un sitio")
    source.add_argument("--panel", action="store_true", help="Auditar los sitios activos del Panel (Drive); publica siempre")
    parser.add_argument("--panel-id", default=os.environ.get("SEO_PANEL_ID", ""),
                        help="ID de la planilla Panel (por defecto, la variable SEO_PANEL_ID)")
    parser.add_argument("--site", default="all", help="Con --panel: nombre de un sitio, o all (por defecto)")
    parser.add_argument("--validate-only", action="store_true", help="Solo validar la config y salir")
    parser.add_argument("--output-dir", default="output", help="Dónde guardar los CSV (por defecto: output/)")
    parser.add_argument("--expected", help="YAML de issues esperados (fixture): falla si falta alguno")
    parser.add_argument("--publish", action="store_true", help="Publicar a Google Sheets y Drive (con --config)")
    parser.add_argument("--quiet", action="store_true", help="No imprimir cada URL rastreada")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    ctx = Context(rules=load_rules(), schema=load_schema(), platforms=load_platforms(),
                  output_dir=args.output_dir, quiet=args.quiet or args.panel)

    if args.panel:
        return run_panel(args, ctx)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"ERROR: no existe {args.config}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print("ERROR: config inválida", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 2

    print(f"Config válida: {cfg.name} | {cfg.domain} | modo={cfg.mode} | max_urls={cfg.crawl.max_urls}")
    if args.validate_only:
        return 0
    return audit_site(cfg, ctx, publish=args.publish, upload_csv=True, check_public=False,
                      expected=args.expected).code


if __name__ == "__main__":
    raise SystemExit(main())
