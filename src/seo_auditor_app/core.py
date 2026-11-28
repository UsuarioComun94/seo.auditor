"""Lógica de la app, sin pantalla (se prueba sin Tk). Habla con la API de GitHub.

La app NO guarda claves de Google: el rastreo corre en GitHub Actions, donde ya están. Solo necesita un
token de GitHub limitado a este repositorio (Actions: lectura y escritura).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

API = "https://api.github.com"
WORKFLOW = "audit.yml"
DEFAULT_REPO = "UsuarioComun94/seo.auditor"
MAX_SITE_LEN = 100


class AppError(RuntimeError):
    """Error con un mensaje listo para mostrarle a la persona (nunca incluye el token)."""


@dataclass
class RunInfo:
    id: int
    event: str
    status: str
    conclusion: str
    created_at: str
    url: str

    @property
    def origin(self) -> str:
        return {"schedule": "Automática (semanal)", "workflow_dispatch": "Manual desde la app o GitHub",
                "push": "Cambio de código"}.get(self.event, self.event)

    @property
    def label(self) -> str:
        if self.status == "completed":
            return {"success": "Terminó bien", "failure": "Terminó con errores", "cancelled": "Cancelada",
                    "skipped": "Omitida"}.get(self.conclusion, self.conclusion or "Terminada")
        return {"in_progress": "En curso", "queued": "En cola", "waiting": "En espera",
                "pending": "En cola"}.get(self.status, self.status)

    @property
    def running(self) -> bool:
        return self.status != "completed"

    def local_time(self) -> str:
        try:
            dt = datetime.fromisoformat(self.created_at.replace("Z", "+00:00")).astimezone()
            return dt.strftime("%d/%m %H:%M")
        except ValueError:
            return self.created_at


def clean_site(site: str) -> str:
    site = (site or "").strip()
    if not site:
        raise AppError("Escribí el nombre del sitio (como figura en el Panel) o 'all' para auditar todos.")
    if len(site) > MAX_SITE_LEN or "\n" in site or "\r" in site:
        raise AppError("El nombre del sitio no es válido.")
    return site


def clean_repo(repo: str) -> str:
    repo = (repo or "").strip().strip("/")
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name or " " in repo:
        raise AppError("El repositorio tiene que tener la forma usuario/nombre.")
    return repo


class GitHubClient:
    def __init__(self, token: str, repo: str = DEFAULT_REPO, base_url: str = API,
                 session: requests.Session | None = None, timeout: float = 20.0):
        if not (token or "").strip():
            raise AppError("Falta el token de GitHub. Pegalo en la app y tocá Guardar.")
        self.repo = clean_repo(repo)
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token.strip()}",
                                     "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "seo-auditor-app"})

    def _call(self, method: str, path: str, **kw):
        try:
            resp = self.session.request(method, f"{self.base_url}/repos/{self.repo}{path}", timeout=self.timeout, **kw)
        except requests.RequestException as exc:
            raise AppError(f"No pude conectarme a GitHub ({type(exc).__name__}). ¿Hay internet?") from None
        if resp.status_code in (200, 201, 204):
            return resp
        raise AppError({
            401: "El token no es válido o venció. Creá uno nuevo y pegalo de nuevo.",
            403: "El token no tiene permiso. Tiene que ser de ESTE repositorio con 'Actions: lectura y escritura'.",
            404: "No encuentro el repositorio o el flujo de auditoría. Revisá el nombre del repo y que el token tenga acceso.",
            422: "GitHub rechazó la orden (¿el flujo está desactivado o falta la rama main?).",
        }.get(resp.status_code, f"GitHub respondió con el código {resp.status_code}."))

    def check(self) -> str:
        """Verifica token y repo. Devuelve el nombre del flujo."""
        return self._call("GET", f"/actions/workflows/{WORKFLOW}").json().get("name", WORKFLOW)

    def dispatch(self, site: str) -> None:
        """Lanza el flujo de auditoría para un sitio del Panel (o all)."""
        body = {"ref": "main", "inputs": {"client": "fixture", "publish": "false", "site": clean_site(site)}}
        self._call("POST", f"/actions/workflows/{WORKFLOW}/dispatches", json=body)

    def runs(self, limit: int = 8) -> list[RunInfo]:
        data = self._call("GET", f"/actions/workflows/{WORKFLOW}/runs", params={"per_page": limit}).json()
        return [RunInfo(id=r["id"], event=r.get("event", ""), status=r.get("status", ""),
                        conclusion=r.get("conclusion") or "", created_at=r.get("created_at", ""),
                        url=r.get("html_url", "")) for r in data.get("workflow_runs", [])]
