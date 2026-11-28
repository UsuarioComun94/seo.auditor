"""Ajustes locales y token. El token va al almacén seguro del sistema (Windows/macOS) si se puede;
si no, a un archivo de la carpeta del usuario con permisos restringidos."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SERVICE = "seo-auditor"
DEFAULTS = {"repo": "UsuarioComun94/seo.auditor", "panel_url": "", "site": "all"}


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "seo-auditor"


class Settings:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or config_dir()
        self.path = self.dir / "settings.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {**DEFAULTS, **{k: str(v) for k, v in data.items() if k in DEFAULTS}}
        except (OSError, ValueError):
            return dict(DEFAULTS)

    def save(self, values: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        clean = {k: str(values.get(k, DEFAULTS[k])) for k in DEFAULTS}
        self.path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


class TokenStore:
    def __init__(self, directory: Path | None = None, use_keyring: bool = True):
        self.dir = directory or config_dir()
        self.file = self.dir / "token"
        self._keyring = None
        if use_keyring:
            try:
                import keyring
                self._keyring = keyring
            except Exception:  # noqa: BLE001 - sin keyring se usa el archivo
                self._keyring = None

    def save(self, repo: str, token: str) -> str:
        """Guarda el token. Devuelve dónde quedó, en palabras simples."""
        token = token.strip()
        if self._keyring is not None:
            try:
                self._keyring.set_password(SERVICE, repo, token)
                return "en el almacén seguro de tu sistema"
            except Exception:  # noqa: BLE001
                pass
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        return "en un archivo de tu usuario (solo vos podés leerlo)"

    def load(self, repo: str) -> str:
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(SERVICE, repo)
                if value:
                    return value
            except Exception:  # noqa: BLE001
                pass
        try:
            return self.file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def delete(self, repo: str) -> None:
        if self._keyring is not None:
            try:
                self._keyring.delete_password(SERVICE, repo)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.file.unlink()
        except OSError:
            pass
