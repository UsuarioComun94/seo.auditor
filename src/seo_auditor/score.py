"""Puntaje de salud SEO (0-100).

    castigo  = suma de pesos por severidad de los issues white hat (schema: severity_weights)
    densidad = castigo / cantidad de URLs rastreadas
    puntaje  = 100 * exp(-densidad / score_scale)

La densidad hace que un sitio grande no puntúe peor solo por ser grande. La exponencial lo
acota entre 0 y 100: baja rápido con los primeros problemas y se achata, así un sitio muy roto
no queda clavado en 0. Las señales de riesgo (grey/black hat) no entran: se reportan aparte.
"""

from __future__ import annotations

import math

from .models import Issue

DEFAULT_SCALE = 2.0


def compute_score(issues: list[Issue], urls_crawled: int, weights: dict[str, int | float],
                  scale: float = DEFAULT_SCALE) -> float:
    penalty = sum(weights.get(i.severity, 0) for i in issues if i.hat == "white")
    density = penalty / max(urls_crawled, 1)
    return round(100.0 * math.exp(-density / scale), 1)


ALL_MODES = {"own", "client", "competitor"}


def comparable_rule_ids(rules: dict) -> set[str]:
    """Reglas que corren en TODOS los modos: la base para comparar sitios propios con ajenos."""
    return {r.id for r in rules.values() if set(r.modes) >= ALL_MODES}


def compute_comparable_score(issues: list[Issue], urls_crawled: int, weights: dict, rules: dict,
                             scale: float = DEFAULT_SCALE) -> float:
    ids = comparable_rule_ids(rules)
    return compute_score([i for i in issues if i.rule_id in ids], urls_crawled, weights, scale)
