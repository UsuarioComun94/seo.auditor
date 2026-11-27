"""Estado entre corridas: qué issues son nuevos, recurrentes o resueltos.

El estado anterior se lee de la propia planilla (pestañas Issues e Historico) antes de escribir,
así que no hace falta ningún almacenamiento extra. Cada issue se identifica con una clave estable
(regla + URL + destino), guardada en la columna issue_key.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .models import Issue


def issue_key(rule_id: str, url: str, target: str = "") -> str:
    return hashlib.sha1(f"{rule_id}|{url}|{target}".encode("utf-8")).hexdigest()[:12]


@dataclass
class PreviousState:
    rows: dict[str, dict] = field(default_factory=dict)   # issue_key -> fila previa (columna -> valor)
    last_score: float | None = None


def _to_float(value) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _as_row(columns: list[str], raw: list) -> dict:
    raw = list(raw)
    return dict(zip(columns, raw + [""] * (len(columns) - len(raw))))


def parse_previous(issue_values: list[list], history_values: list[list], domain: str,
                   issue_cols: list[str], history_cols: list[str]) -> PreviousState:
    state = PreviousState()
    for raw in issue_values:
        row = _as_row(issue_cols, raw)
        key = str(row.get("issue_key", "")).strip()
        # Sin clave no se puede comparar (filas de versiones anteriores); las ya resueltas se
        # informaron una vez y no se arrastran.
        if not key or row.get("estado") == "resuelto":
            continue
        state.rows[key] = row
    for raw in history_values:
        row = _as_row(history_cols, raw)
        if row.get("dominio") == domain:
            score = _to_float(row.get("puntaje", ""))
            if score is not None:
                state.last_score = score
    return state


def annotate(issues: list[Issue], previous: PreviousState | None, when: str) -> list[tuple[Issue, str, str, str]]:
    """Devuelve (issue, clave, estado, primera_vez_visto) para cada issue actual."""
    out = []
    for i in issues:
        key = issue_key(i.rule_id, i.url, i.target)
        prev = previous.rows.get(key) if previous else None
        if prev:
            out.append((i, key, "recurrente", str(prev.get("primera_vez_visto") or when)))
        else:
            out.append((i, key, "nuevo", when))
    return out


def resolved_rows(current_keys: set[str], previous: PreviousState | None) -> list[dict]:
    """Filas previas cuyo issue ya no aparece."""
    if not previous:
        return []
    return [row for key, row in previous.rows.items() if key not in current_keys]
