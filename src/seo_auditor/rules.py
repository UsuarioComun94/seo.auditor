"""Catálogo de reglas (rules/rules.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    category: str
    severity: str
    hat: str
    modes: tuple[str, ...]
    phase: int
    description: str


def default_rules_path() -> Path:
    override = os.environ.get("SEO_AUDITOR_RULES")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def load_rules(path: str | Path | None = None) -> dict[str, Rule]:
    data = yaml.safe_load(Path(path or default_rules_path()).read_text(encoding="utf-8"))
    rules: dict[str, Rule] = {}
    for r in data["rules"]:
        rules[r["id"]] = Rule(
            id=r["id"], name=r["name"], category=r["category"], severity=r["severity"],
            hat=r["hat"], modes=tuple(r["modes"]), phase=int(r["phase"]), description=r["description"],
        )
    return rules
