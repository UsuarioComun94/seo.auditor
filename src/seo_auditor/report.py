"""Armado de filas para la planilla y de los CSV completos."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .checks import RECOMMENDATIONS
from .models import CrawlResult, Issue
from .platform import limit_for, platform_label
from .rules import default_rules_path
from .state import PreviousState, annotate, issue_key, resolved_rows

MAX_ISSUE_ROWS_IN_SHEET = 5000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def default_schema_path() -> Path:
    return default_rules_path().parent.parent / "schema" / "sheet_schema.json"


def load_schema(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or default_schema_path()).read_text(encoding="utf-8"))


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def count_by_severity(issues: list[Issue]) -> dict[str, int]:
    c = Counter(i.severity for i in issues if i.hat == "white")
    return {s: c.get(s, 0) for s in ("critical", "high", "medium", "low")}


def _row(columns: list[str], values: dict) -> list:
    return [values.get(col, "") for col in columns]


def build_tabs(result: CrawlResult, issues: list[Issue], run_id: str, csv_link: str = "",
               schema: dict | None = None, previous: PreviousState | None = None,
               score: float | None = None, delta: float | None = None,
               platforms: dict | None = None) -> dict[str, list[list]]:
    """Devuelve {pestaña: filas} según schema/sheet_schema.json. Sin encabezados."""
    schema = schema or load_schema()
    platforms = platforms or {}
    cols = {t["name"]: t["columns"] for t in schema["tabs"]}
    counts = count_by_severity(issues)
    when = result.finished_at or result.started_at

    summary = {
        "run_id": run_id, "fecha_utc": when, "dominio": result.domain, "modo": result.mode,
        "urls_rastreadas": len(result.pages),
        "criticos": counts["critical"], "altos": counts["high"], "medios": counts["medium"], "bajos": counts["low"],
        "puntaje": "" if score is None else score,
        "delta_puntaje_vs_anterior": "" if delta is None else delta,
        "link_csv_completo": csv_link,
        "plataforma": platform_label(platforms, result.platform) if result.platform else "",
    }
    history = {k: summary[k] for k in ("run_id", "fecha_utc", "dominio", "puntaje", "criticos", "altos",
                                        "medios", "bajos", "urls_rastreadas")}

    white = [i for i in issues if i.hat == "white"]
    risk = [i for i in issues if i.hat == "signal"]

    annotated = annotate(white, previous, when)
    issue_rows = [
        _row(cols["Issues"], {
            "run_id": run_id, "regla_id": i.rule_id, "severidad": i.severity, "categoria": i.category,
            "url": i.url, "detalle": i.detail,
            "arreglable_en_plataforma": limit_for(platforms, result.platform, i.rule_id),
            "recomendacion": RECOMMENDATIONS.get(i.rule_id, ""),
            "primera_vez_visto": first_seen, "estado": estado, "issue_key": key,
        })
        for i, key, estado, first_seen in annotated
    ]
    # Con crawl truncado faltan URLs: un issue ausente no significa que se haya resuelto.
    if not result.truncated:
        current_keys = {key for _, key, _, _ in annotated}
        for prev in resolved_rows(current_keys, previous):
            row = dict(prev)
            row["run_id"] = run_id
            row["estado"] = "resuelto"
            issue_rows.append(_row(cols["Issues"], row))
    issue_rows = issue_rows[:MAX_ISSUE_ROWS_IN_SHEET]

    risk_rows = [
        _row(cols["Riesgo"], {
            "run_id": run_id, "regla_id": i.rule_id, "nivel_riesgo": i.severity, "url": i.url, "evidencia": i.detail,
        })
        for i in risk[:MAX_ISSUE_ROWS_IN_SHEET]
    ]
    return {
        "Resumen": [_row(cols["Resumen"], summary)],
        "Historico": [_row(cols["Historico"], history)],
        "Issues": issue_rows,
        "Riesgo": risk_rows,
    }


def _safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            writer.writerow([_safe(v) for v in row])


def write_local(output_dir: str | Path, result: CrawlResult, issues: list[Issue], run_id: str,
                score: float | None = None) -> dict[str, Path]:
    """Escribe pages.csv, issues.csv y summary.json. Devuelve las rutas."""
    out = Path(output_dir) / result.name / run_id
    out.mkdir(parents=True, exist_ok=True)

    inlinks: Counter = Counter()
    for p in result.pages.values():
        for link in set(p.links):
            if link in result.pages:
                inlinks[link] += 1

    pages_header = ["url", "status", "redirect_to", "redirect_kind", "indexable", "noindex", "title",
                    "meta_description", "h1_count", "canonical", "in_sitemap", "inlinks", "depth",
                    "response_ms", "content_type", "x_robots_tag", "discovered_from", "error"]
    pages_rows = [
        [p.url, p.status, p.redirect_to, p.redirect_kind, p.indexable, p.noindex, p.title, p.meta_description,
         p.h1_count, p.canonical, p.in_sitemap, inlinks.get(p.url, 0), p.depth, p.response_ms, p.content_type,
         p.x_robots_tag, p.discovered_from, p.error]
        for p in result.pages.values()
    ]
    issues_header = ["rule_id", "severity", "category", "hat", "url", "target", "detail", "issue_key"]
    issues_rows = [[i.rule_id, i.severity, i.category, i.hat, i.url, i.target, i.detail,
                    issue_key(i.rule_id, i.url, i.target)] for i in issues]

    paths = {"pages": out / "pages.csv", "issues": out / "issues.csv", "summary": out / "summary.json"}
    _write_csv(paths["pages"], pages_header, pages_rows)
    _write_csv(paths["issues"], issues_header, issues_rows)
    counts = count_by_severity(issues)
    paths["summary"].write_text(json.dumps({
        "run_id": run_id, "name": result.name, "domain": result.domain, "mode": result.mode,
        "started_at": result.started_at, "finished_at": result.finished_at,
        "urls_crawled": len(result.pages), "truncated": result.truncated, "platform": result.platform,
        "score": score,
        "issues_by_severity": counts, "risk_signals": sum(1 for i in issues if i.hat == "signal"),
        "robots_url": result.robots_url, "robots_status": result.robots_status,
        "notes": result.notes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths
