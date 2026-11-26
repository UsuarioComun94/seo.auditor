"""Compara los issues encontrados contra fixture/EXPECTED_ISSUES.yaml (recall)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import yaml

from .models import Issue
from .rules import Rule
from .urls import normalize_url

MAX_PHASE = 1


@dataclass
class ExpectedReport:
    checked: int = 0
    found: int = 0
    missing: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def check_expected(issues: list[Issue], expected_path: str | Path, rules: dict[str, Rule], mode: str,
                   base_url: str | None = None, skip_rules: dict[str, str] | None = None,
                   max_phase: int = MAX_PHASE) -> ExpectedReport:
    """Verifica que cada issue esperado (de reglas con fase <= max_phase) haya sido detectado.

    base_url permite probar contra un servidor local en lugar de la URL de producción.
    skip_rules: {regla: motivo} para excluir reglas que el entorno de prueba no puede reproducir.
    """
    data = yaml.safe_load(Path(expected_path).read_text(encoding="utf-8"))
    base = base_url or data["base_url"]
    skip_rules = skip_rules or {}
    found_by_key: dict[tuple[str, str], list[Issue]] = {}
    for i in issues:
        found_by_key.setdefault((i.rule_id, normalize_url(i.url)), []).append(i)

    report = ExpectedReport()
    for exp in data["issues"]:
        rule = rules.get(exp["rule"])
        if rule is None or rule.phase > max_phase or mode not in rule.modes:
            tag = f"{exp['rule']} (fase {rule.phase})" if rule else f"{exp['rule']} (desconocida)"
            if tag not in report.skipped:
                report.skipped.append(tag)
            continue
        if exp["rule"] in skip_rules:
            note = f"{exp['rule']} ({skip_rules[exp['rule']]})"
            if note not in report.skipped:
                report.skipped.append(note)
            continue
        report.checked += 1
        url = normalize_url(urljoin(base, exp["url"]))
        candidates = found_by_key.get((exp["rule"], url), [])
        target = exp.get("target")
        if target:
            wanted = normalize_url(urljoin(base, target))
            candidates = [c for c in candidates if normalize_url(c.target) == wanted] if candidates else []
        if candidates:
            report.found += 1
        else:
            report.missing.append(exp)
    return report
