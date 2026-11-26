"""CLI del auditor.

Códigos de salida: 0 ok | 2 config inválida | 3 faltan issues esperados (fixture)
                   4 falló la publicación a Sheets | 5 crawl abortado
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .checks import run_checks
from .config import ConfigError, load_config
from .crawler import CrawlAbort, Crawler
from .expected import check_expected
from .report import build_tabs, count_by_severity, load_schema, new_run_id, write_local
from .rules import load_rules
from .urls import Scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seo_auditor", description="Auditor SEO autónomo")
    parser.add_argument("--config", required=True, help="Ruta al YAML del cliente")
    parser.add_argument("--validate-only", action="store_true", help="Solo validar la config y salir")
    parser.add_argument("--output-dir", default="output", help="Dónde guardar los CSV (por defecto: output/)")
    parser.add_argument("--expected", help="YAML de issues esperados (fixture): falla si falta alguno")
    parser.add_argument("--publish", action="store_true", help="Publicar a Google Sheets y Drive")
    parser.add_argument("--quiet", action="store_true", help="No imprimir cada URL rastreada")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

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

    rules = load_rules()
    run_id = new_run_id()
    crawler = Crawler(cfg, log=(lambda m: None) if args.quiet else print)
    try:
        result = crawler.run()
    except CrawlAbort as exc:
        print(f"ERROR: crawl abortado: {exc}", file=sys.stderr)
        return 5

    issues = run_checks(result, rules, Scope(cfg.domain))
    counts = count_by_severity(issues)
    paths = write_local(args.output_dir, result, issues, run_id)
    print(f"\nRastreadas {len(result.pages)} URLs ({crawler.fetcher.requests_made} pedidos)"
          f"{' [TRUNCADO por max_urls]' if result.truncated else ''}")
    print(f"Issues: {counts['critical']} críticos, {counts['high']} altos, {counts['medium']} medios, {counts['low']} bajos")
    for note in result.notes:
        print(f"Nota: {note}")
    print(f"CSV completos en {paths['pages'].parent}")

    exit_code = 0

    if args.publish:
        from .sheets import PublishError, SheetsPublisher, build_services, upload_csv_to_drive

        try:
            if not cfg.sheets.spreadsheet_id:
                raise PublishError("la config no tiene sheets.spreadsheet_id")
            sheets_svc, drive_svc, sa_email = build_services()
            link = upload_csv_to_drive(drive_svc, cfg.sheets.drive_folder_id, paths["pages"],
                                       f"{cfg.name}-{run_id}-pages.csv")
            tabs = build_tabs(result, issues, run_id, csv_link=link or "ver artifact del workflow", schema=load_schema())
            SheetsPublisher(sheets_svc, cfg.sheets.spreadsheet_id, load_schema()).publish(tabs)
            print(f"Publicado en la planilla {cfg.sheets.spreadsheet_id} (cuenta {sa_email})")
        except PublishError as exc:
            print(f"ERROR: publicación: {exc}", file=sys.stderr)
            exit_code = 4
        except Exception as exc:  # noqa: BLE001 - se muestra el motivo y se falla con código propio
            print(f"ERROR: publicación a Google falló: {type(exc).__name__}: {str(exc)[:500]}", file=sys.stderr)
            exit_code = 4

    if args.expected:
        report = check_expected(issues, args.expected, rules, cfg.mode)
        print(f"\nFixture: {report.found}/{report.checked} issues esperados detectados")
        if report.skipped:
            print("No evaluados: " + ", ".join(report.skipped))
        for exp in report.missing:
            print(f"  FALTA {exp['rule']} en {exp['url'] or '/'}"
                  + (f" → {exp['target']}" if exp.get("target") else ""), file=sys.stderr)
        if not report.ok:
            exit_code = exit_code or 3

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
