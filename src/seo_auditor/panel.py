"""Planilla maestra (Panel): configs de los sitios y comparativa, solo para el administrador.

- Clientes: la mantiene la persona, una fila por sitio. Las columnas se leen por NOMBRE, así que se
  pueden reordenar. Solo corren las filas con activo = TRUE.
- Comparativa: la escribe el motor; una fila por sitio, que se actualiza por nombre.

Cada fila de Clientes pasa por la misma validación que un YAML (config.parse_config), así que las
reglas del modo competitor se aplican igual. Una fila inválida no frena a las demás.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import ClientConfig, ConfigError, parse_config
from .fetcher import DEFAULT_USER_AGENT
from .sheets import PublishError, _col

REQUIRED_COLUMNS = ("nombre", "dominio", "modo", "spreadsheet_id", "activo")
_TRUE = {"true", "verdadero", "si", "sí", "yes", "1", "x"}


@dataclass
class SiteEntry:
    name: str
    row: int                       # fila en la planilla (para mensajes de error)
    active: bool
    cfg: ClientConfig | None = None
    errors: list[str] = field(default_factory=list)


def _truthy(value) -> bool:
    return str(value).strip().lower() in _TRUE


def _number(value, default, cast):
    text = str(value).strip().replace(",", ".")
    if text == "":
        return default
    try:
        return cast(float(text))
    except ValueError:
        raise ValueError(f"no es un número: {value!r}") from None


def parse_clients(header: list, rows: list[list]) -> list[SiteEntry]:
    """Convierte las filas de la pestaña Clientes en SiteEntry. Las filas totalmente vacías se ignoran."""
    cols = [str(h).strip().lower() for h in header]
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise PublishError("la pestaña Clientes no tiene las columnas: " + ", ".join(missing))

    entries: list[SiteEntry] = []
    seen: set[str] = set()
    for offset, raw in enumerate(rows):
        raw = list(raw)
        if not any(str(c).strip() for c in raw):
            continue
        row = dict(zip(cols, raw + [""] * (len(cols) - len(raw))))
        number = offset + 2
        name = str(row.get("nombre", "")).strip()
        entry = SiteEntry(name=name, row=number, active=_truthy(row.get("activo", "")))
        entries.append(entry)
        if not entry.active:
            continue
        if not name:
            entry.errors.append("falta el nombre")
            continue
        if name.casefold() in seen:
            entry.errors.append("nombre repetido")
            continue
        seen.add(name.casefold())

        mode = str(row.get("modo", "")).strip().lower()
        competitor = mode == "competitor"
        try:
            crawl = {
                "max_urls": _number(row.get("max_urls", ""), 500 if competitor else 1000, int),
                "delay_seconds": _number(row.get("delay_seconds", ""), 2.0 if competitor else 0.5, float),
                "respect_robots": True,
                "user_agent": DEFAULT_USER_AGENT,
                "render_js": _truthy(row.get("render_js", "")),
                "compare_googlebot_ua": _truthy(row.get("comparar_googlebot", "")),
                "robots_url": str(row.get("robots_url", "")).strip(),
            }
        except ValueError as exc:
            entry.errors.append(str(exc))
            continue
        raw_cfg = {
            "name": name,
            "domain": str(row.get("dominio", "")).strip(),
            "mode": mode,
            "authorized": _truthy(row.get("autorizado", "")),
            "crawl": crawl,
            "sheets": {"spreadsheet_id": str(row.get("spreadsheet_id", "")).strip()},
        }
        try:
            entry.cfg = parse_config(raw_cfg)
        except ConfigError as exc:
            entry.errors.extend(exc.errors)
            continue
        if not entry.cfg.sheets.spreadsheet_id:
            entry.errors.append("falta spreadsheet_id (la planilla del sitio)")
            entry.cfg = None
    return entries


class SheetsPanel:
    def __init__(self, sheets_service, panel_id: str, schema: dict):
        self.svc = sheets_service
        self.id = panel_id
        self.tabs = {t["name"]: t for t in schema["panel"]["tabs"]}

    def _values(self, rng: str) -> list[list]:
        resp = self.svc.spreadsheets().values().get(
            spreadsheetId=self.id, range=rng, valueRenderOption="UNFORMATTED_VALUE").execute()
        return resp.get("values", [])

    def ensure_tabs(self) -> None:
        """Una planilla importada desde CSV trae una sola pestaña con otro nombre: pasa a ser Clientes."""
        meta = self.svc.spreadsheets().get(
            spreadsheetId=self.id, fields="sheets.properties(sheetId,title,index)").execute()
        existing = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}
        requests = []
        if "Clientes" not in existing and existing:
            first = min(existing.values(), key=lambda p: p["index"])
            if first["title"] not in self.tabs:
                requests.append({"updateSheetProperties": {
                    "properties": {"sheetId": first["sheetId"], "title": "Clientes"}, "fields": "title"}})
        for name in ("Comparativa", "Benchmark"):
            if name not in existing:
                requests.append({"addSheet": {"properties": {"title": name}}})
        if requests:
            self.svc.spreadsheets().batchUpdate(spreadsheetId=self.id, body={"requests": requests}).execute()
        for name in ("Comparativa", "Benchmark"):
            self.svc.spreadsheets().values().update(
                spreadsheetId=self.id, range=f"'{name}'!A1", valueInputOption="RAW",
                body={"values": [self.tabs[name]["columns"]]}).execute()

    def read_clients(self) -> list[SiteEntry]:
        values = self._values("'Clientes'!A1:Z")
        if not values:
            raise PublishError("la pestaña Clientes está vacía")
        return parse_clients(values[0], values[1:])

    def upsert_comparativa(self, rows: list[dict]) -> None:
        self.upsert("Comparativa", rows)

    def upsert_benchmark(self, rows: list[dict]) -> None:
        self.upsert("Benchmark", rows)

    def upsert(self, tab: str, rows: list[dict]) -> None:
        """Actualiza por nombre las filas de los sitios auditados; conserva las demás.

        None se escribe como celda vacía (no medible), nunca como 0.
        """
        columns = self.tabs[tab]["columns"]
        existing = self._values(f"'{tab}'!A2:{_col(len(columns))}")
        merged: dict[str, list] = {}
        for raw in existing:
            raw = list(raw) + [""] * (len(columns) - len(raw))
            if str(raw[0]).strip():
                merged[str(raw[0]).strip().casefold()] = raw
        for new in rows:
            merged[new["nombre"].casefold()] = [("" if new.get(c) is None else new.get(c)) for c in columns]
        out = list(merged.values())
        self.svc.spreadsheets().values().clear(
            spreadsheetId=self.id, range=f"'{tab}'!A2:{_col(len(columns))}", body={}).execute()
        if out:
            self.svc.spreadsheets().values().update(
                spreadsheetId=self.id, range=f"'{tab}'!A2", valueInputOption="RAW",
                body={"values": out}).execute()
