"""Publicación a Google Sheets y Drive con un service account.

Modos de escritura por pestaña (schema/sheet_schema.json, campo write_mode):
  append  -> Resumen e Historico acumulan una fila por corrida.
  replace -> Issues y Riesgo muestran solo la última corrida (el histórico completo vive en el CSV).

Los valores se escriben con valueInputOption=RAW: el contenido rastreado (títulos, URLs) es entrada
no confiable y nunca debe interpretarse como fórmula.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
CREDENTIALS_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
CHUNK_ROWS = 1000  # filas por pedido: evita payloads grandes con la pestaña Crawl


class PublishError(RuntimeError):
    pass


def build_services(credentials_json: str | None = None):
    """Crea los clientes de Sheets y Drive. El JSON viene de una variable de entorno (GitHub Secret)."""
    raw = credentials_json or os.environ.get(CREDENTIALS_ENV, "")
    if not raw.strip():
        raise PublishError(f"falta la variable de entorno {CREDENTIALS_ENV} (GitHub Secret)")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError(f"{CREDENTIALS_ENV} no es un JSON válido") from exc
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return sheets, drive, info.get("client_email", "")


def build_gsc_service(credentials_json: str | None = None):
    """Cliente de Search Console (solo lectura) con el mismo service account."""
    raw = credentials_json or os.environ.get(CREDENTIALS_ENV, "")
    if not raw.strip():
        raise PublishError(f"falta la variable de entorno {CREDENTIALS_ENV} (GitHub Secret)")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError(f"{CREDENTIALS_ENV} no es un JSON válido") from exc
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


class SheetsPublisher:
    def __init__(self, sheets_service, spreadsheet_id: str, schema: dict):
        self.svc = sheets_service
        self.id = spreadsheet_id
        self.schema = schema
        self.tabs = {t["name"]: t for t in schema["tabs"]}

    # ---------- estructura ----------
    def _titles(self) -> dict[str, int]:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.id, fields="sheets.properties(sheetId,title,index)").execute()
        return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    def ensure_tabs(self) -> None:
        """Crea las pestañas que faltan y deja los encabezados. Idempotente."""
        meta = self.svc.spreadsheets().get(spreadsheetId=self.id, fields="sheets.properties(sheetId,title,index)").execute()
        existing = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}
        requests = []

        # Arranque: la planilla creada desde un CSV trae una sola pestaña con otro nombre y la config adentro.
        if "Config" not in existing and existing:
            first = min(existing.values(), key=lambda p: p["index"])
            if first["title"] not in self.tabs:
                requests.append({"updateSheetProperties": {
                    "properties": {"sheetId": first["sheetId"], "title": "Config"}, "fields": "title"}})
                existing["Config"] = {**first, "title": "Config"}
                existing.pop(first["title"], None)

        for name in self.tabs:
            if name not in existing:
                requests.append({"addSheet": {"properties": {"title": name}}})
        if requests:
            self.svc.spreadsheets().batchUpdate(spreadsheetId=self.id, body={"requests": requests}).execute()

        ids = self._titles()
        fmt = []
        for name, tab in self.tabs.items():
            if name == "Config":
                continue  # la config la mantiene la persona; no se pisa
            header = tab["columns"]
            self.svc.spreadsheets().values().update(
                spreadsheetId=self.id, range=f"'{name}'!A1", valueInputOption="RAW", body={"values": [header]},
            ).execute()
            sid = ids.get(name)
            if sid is not None:
                fmt.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold"}})
                fmt.append({"updateSheetProperties": {
                    "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount"}})
        if fmt:
            self.svc.spreadsheets().batchUpdate(spreadsheetId=self.id, body={"requests": fmt}).execute()

    # ---------- escritura ----------
    def _ensure_rows(self, name: str, needed: int) -> None:
        """values.update no expande la hoja: una planilla nueva trae 1000 filas, así que se agranda antes."""
        meta = self.svc.spreadsheets().get(
            spreadsheetId=self.id, fields="sheets.properties(sheetId,title,gridProperties)").execute()
        for s in meta.get("sheets", []):
            props = s["properties"]
            if props.get("title") == name:
                current = props.get("gridProperties", {}).get("rowCount")
                if current is not None and current < needed:
                    self.svc.spreadsheets().batchUpdate(spreadsheetId=self.id, body={"requests": [
                        {"updateSheetProperties": {
                            "properties": {"sheetId": props["sheetId"], "gridProperties": {"rowCount": needed + 100}},
                            "fields": "gridProperties.rowCount"}}]}).execute()
                return

    def write_tab(self, name: str, rows: list[list]) -> None:
        tab = self.tabs[name]
        mode = tab.get("write_mode", "append")
        width = len(tab["columns"])
        if mode == "replace":
            self.svc.spreadsheets().values().clear(
                spreadsheetId=self.id, range=f"'{name}'!A2:{_col(width)}", body={}).execute()
            if rows:
                self._ensure_rows(name, len(rows) + 1)
            for start in range(0, len(rows), CHUNK_ROWS):
                self.svc.spreadsheets().values().update(
                    spreadsheetId=self.id, range=f"'{name}'!A{2 + start}", valueInputOption="RAW",
                    body={"values": rows[start:start + CHUNK_ROWS]}).execute()
        else:
            for start in range(0, len(rows), CHUNK_ROWS):
                self.svc.spreadsheets().values().append(
                    spreadsheetId=self.id, range=f"'{name}'!A1", valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS", body={"values": rows[start:start + CHUNK_ROWS]}).execute()

    def read_previous(self, domain: str):
        """Lee el estado de la corrida anterior (pestañas Issues e Historico) antes de escribir.

        No se atrapan los errores de lectura a propósito: si falla, abortar es mejor que escribir
        con estado vacío y perder el historial de issues (Issues se sobreescribe).
        """
        from .state import parse_previous

        def rows(tab: str) -> list[list]:
            ncols = len(self.tabs[tab]["columns"])
            resp = self.svc.spreadsheets().values().get(
                spreadsheetId=self.id, range=f"'{tab}'!A2:{_col(ncols)}").execute()
            return resp.get("values", [])

        return parse_previous(rows("Issues"), rows("Historico"), domain,
                              self.tabs["Issues"]["columns"], self.tabs["Historico"]["columns"])

    def write_all(self, tabs: dict[str, list[list]]) -> None:
        for name, rows in tabs.items():
            self.write_tab(name, rows)

    def publish(self, tabs: dict[str, list[list]]) -> None:
        self.ensure_tabs()
        self.write_all(tabs)


def _col(n: int) -> str:
    """Número de columna (1-based) a letra: 1 -> A, 27 -> AA."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def upload_csv_to_drive(drive_service, folder_id: str, path: Path, name: str) -> str:
    """Sube un CSV a la carpeta de Drive. Devuelve el enlace, o "" si falla (best effort).

    Un service account no tiene cuota propia en el Drive de otra persona, así que este paso puede
    fallar; el motor sigue y el CSV queda como artifact del workflow.
    """
    if not folder_id:
        return ""
    try:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(path), mimetype="text/csv", resumable=False)
        created = drive_service.files().create(
            body={"name": name, "parents": [folder_id]}, media_body=media,
            fields="id,webViewLink", supportsAllDrives=True,
        ).execute()
        return created.get("webViewLink", "")
    except Exception as exc:  # noqa: BLE001 - best effort por diseño
        print(f"AVISO: no se pudo subir {name} a Drive: {type(exc).__name__}: {str(exc)[:200]}")
        return ""
