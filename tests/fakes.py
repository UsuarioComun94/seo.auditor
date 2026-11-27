"""Cliente falso de Google Sheets en memoria, con varias planillas.

Emula lo que importa para los bugs reales: rangos con fila de inicio, límite de filas de la grilla
(values.update NO expande la hoja), renombrado de pestañas y valores RAW.
"""

from __future__ import annotations

import re

_RANGE = re.compile(r"^'(?P<tab>.+)'!(?P<c1>[A-Z]+)(?P<r1>\d+)(?::(?P<c2>[A-Z]+)(?P<r2>\d*))?$")


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class MemSheets:
    def __init__(self, books: dict[str, dict[str, list[list]]] | None = None, grid_rows: int = 1000):
        self.books = books or {}
        self.grid = {}      # (spreadsheet_id, tab) -> rowCount
        self.default_grid = grid_rows
        self.writes: list[tuple] = []   # (op, spreadsheet_id, tab, value_input_option)

    # --- navegación de la API
    def spreadsheets(self):
        return self

    def values(self):
        return self

    def _tabs(self, sid):
        return self.books.setdefault(sid, {})

    def _rows(self, sid, tab):
        return self._tabs(sid).setdefault(tab, [])

    def _grid(self, sid, tab):
        return self.grid.setdefault((sid, tab), self.default_grid)

    def get(self, spreadsheetId, fields=None, range=None, valueRenderOption=None):
        if range is None:
            def meta():
                return {"sheets": [{"properties": {"sheetId": i, "title": t, "index": i,
                                                   "gridProperties": {"rowCount": self._grid(spreadsheetId, t)}}}
                                   for i, t in enumerate(self._tabs(spreadsheetId))]}
            return _Exec(meta)

        m = _RANGE.match(range)
        assert m, f"rango no soportado por el falso: {range}"

        def read():
            rows = self._rows(spreadsheetId, m["tab"])[int(m["r1"]) - 1:]
            while rows and not any(str(c) != "" for c in rows[-1]):
                rows = rows[:-1]
            return {"values": [list(r) for r in rows]} if rows else {}
        return _Exec(read)

    def batchUpdate(self, spreadsheetId, body):
        def run():
            tabs = self._tabs(spreadsheetId)
            for req in body["requests"]:
                if "addSheet" in req:
                    tabs.setdefault(req["addSheet"]["properties"]["title"], [])
                elif "updateSheetProperties" in req:
                    props = req["updateSheetProperties"]["properties"]
                    names = list(tabs)
                    if "title" in props:
                        old = names[props["sheetId"]]
                        tabs[props["title"]] = tabs.pop(old)   # (el orden de dict cambia; basta para las pruebas)
                    grid = props.get("gridProperties", {})
                    if "rowCount" in grid:
                        names = list(tabs)
                        self.grid[(spreadsheetId, names[props["sheetId"]])] = grid["rowCount"]
            return {}
        return _Exec(run)

    def update(self, spreadsheetId, range, valueInputOption, body):
        m = _RANGE.match(range)
        assert m, range

        def run():
            self.writes.append(("update", spreadsheetId, m["tab"], valueInputOption))
            rows = self._rows(spreadsheetId, m["tab"])
            start = int(m["r1"]) - 1
            values = body["values"]
            if start + len(values) > self._grid(spreadsheetId, m["tab"]):
                raise RuntimeError(f"Range exceeds grid limits en {m['tab']}")  # como el 400 real
            while len(rows) < start + len(values):
                rows.append([])
            for i, row in enumerate(values):
                rows[start + i] = list(row)
            return {}
        return _Exec(run)

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption=None, body=None):
        m = _RANGE.match(range)

        def run():
            self.writes.append(("append", spreadsheetId, m["tab"], valueInputOption))
            rows = self._rows(spreadsheetId, m["tab"])
            rows.extend(list(r) for r in body["values"])
            return {}
        return _Exec(run)

    def clear(self, spreadsheetId, range, body=None):
        m = _RANGE.match(range)

        def run():
            rows = self._rows(spreadsheetId, m["tab"])
            del rows[int(m["r1"]) - 1:]
            return {}
        return _Exec(run)
