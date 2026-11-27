"""Search Console (fase 4): solo para sitios propios o de clientes que den acceso. API gratuita.

Requisito: agregar el mail del service account como usuario (permiso "Restringido") de la propiedad en
Search Console. Sin ese permiso la API responde 403 y el motor sigue sin estos datos.
La propiedad puede ser de dominio ("sc-domain:ejemplo.com") o de prefijo de URL ("https://ejemplo.com/").
"""

from __future__ import annotations

from datetime import date, timedelta

DAYS = 28
LAG_DAYS = 3                      # Search Console tarda ~2-3 días en consolidar
PAGE_ROW_LIMIT = 5000
QUERY_ROW_LIMIT = 1000


class GscError(RuntimeError):
    pass


def _query(svc, prop: str, dimension: str, start: str, end: str, limit: int) -> list[dict]:
    body = {"startDate": start, "endDate": end, "dimensions": [dimension], "rowLimit": limit, "dataState": "final"}
    try:
        resp = svc.searchanalytics().query(siteUrl=prop, body=body).execute()
    except Exception as exc:  # noqa: BLE001
        status = getattr(getattr(exc, "resp", None), "status", "")
        raise GscError(f"Search Console falló ({type(exc).__name__} {status})".strip()) from None
    return [{"key": r["keys"][0], "clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0),
             "ctr": r.get("ctr", 0.0), "position": r.get("position", 0.0)} for r in resp.get("rows", [])]


def fetch(svc, prop: str, today: date | None = None) -> dict:
    today = today or date.today()
    end = today - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=DAYS - 1)
    s, e = start.isoformat(), end.isoformat()
    return {"property": prop, "start": s, "end": e,
            "pages": _query(svc, prop, "page", s, e, PAGE_ROW_LIMIT),
            "queries": _query(svc, prop, "query", s, e, QUERY_ROW_LIMIT)}


def expected_ctr(position: float) -> float:
    """CTR orgánico típico por posición (aproximado; sirve como umbral, no como promesa)."""
    return 0.08 if position <= 3 else 0.03 if position <= 6 else 0.015 if position <= 10 else 0.0
