"""Carga y validación de la configuración por cliente.

Las reglas del modo `competitor` (docs/ETHICS.md) se validan acá, en código:
una config que las viole no se puede ejecutar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

MODES = ("own", "client", "competitor")

COMPETITOR_MIN_DELAY = 2.0
COMPETITOR_MAX_URLS = 500


class ConfigError(ValueError):
    """Config inválida. El mensaje lista todos los errores encontrados."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class CrawlConfig:
    max_urls: int = 1000
    delay_seconds: float = 0.5
    respect_robots: bool = True
    user_agent: str = ""
    render_js: bool = False
    compare_googlebot_ua: bool = False
    # Para sitios servidos bajo un subpath (ej. GitHub Pages de proyecto),
    # donde robots.txt no está en la raíz del dominio.
    robots_url: str = ""


@dataclass
class Thresholds:
    title_max_chars: int = 60
    meta_description_max_chars: int = 160


@dataclass
class SheetsConfig:
    spreadsheet_id: str = ""
    drive_folder_id: str = ""


@dataclass
class ClientConfig:
    name: str
    domain: str
    mode: str
    authorized: bool = False
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)
    sheets: SheetsConfig = field(default_factory=SheetsConfig)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def parse_config(raw: Any) -> ClientConfig:
    """Valida un dict ya cargado desde YAML y devuelve un ClientConfig."""
    errors: list[str] = []

    if not isinstance(raw, dict):
        raise ConfigError(["la config debe ser un mapa YAML"])

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name es obligatorio")

    domain = raw.get("domain")
    if not isinstance(domain, str) or urlparse(domain).scheme not in ("http", "https") or not urlparse(domain).netloc:
        errors.append("domain debe ser una URL http(s) completa")

    mode = raw.get("mode")
    if mode not in MODES:
        errors.append(f"mode debe ser uno de {', '.join(MODES)}")

    authorized = raw.get("authorized", False)
    if not isinstance(authorized, bool):
        errors.append("authorized debe ser true o false")
        authorized = False

    crawl_raw = _as_dict(raw.get("crawl"))
    crawl = CrawlConfig(
        max_urls=crawl_raw.get("max_urls", 1000),
        delay_seconds=crawl_raw.get("delay_seconds", 0.5),
        respect_robots=crawl_raw.get("respect_robots", True),
        user_agent=crawl_raw.get("user_agent", ""),
        render_js=crawl_raw.get("render_js", False),
        compare_googlebot_ua=crawl_raw.get("compare_googlebot_ua", False),
        robots_url=crawl_raw.get("robots_url", "") or "",
    )

    if crawl.robots_url and (
        not isinstance(crawl.robots_url, str) or urlparse(crawl.robots_url).scheme not in ("http", "https")
    ):
        errors.append("crawl.robots_url debe ser una URL http(s) completa")
    if isinstance(crawl.max_urls, bool) or not isinstance(crawl.max_urls, int) or crawl.max_urls < 1:
        errors.append("crawl.max_urls debe ser un entero positivo")
    if isinstance(crawl.delay_seconds, bool) or not isinstance(crawl.delay_seconds, (int, float)) or crawl.delay_seconds < 0:
        errors.append("crawl.delay_seconds debe ser un número mayor o igual a 0")
    if not isinstance(crawl.respect_robots, bool):
        errors.append("crawl.respect_robots debe ser true o false")
    if not isinstance(crawl.user_agent, str):
        errors.append("crawl.user_agent debe ser texto")
        crawl.user_agent = ""

    # --- Reglas por modo ---
    if mode == "client" and authorized is not True:
        errors.append("mode client requiere authorized: true (autorización del dueño del sitio)")

    if mode == "competitor":
        ua = crawl.user_agent if isinstance(crawl.user_agent, str) else ""
        if crawl.respect_robots is not True:
            errors.append("competitor: respect_robots debe ser true")
        if isinstance(crawl.delay_seconds, (int, float)) and not isinstance(crawl.delay_seconds, bool) \
                and crawl.delay_seconds < COMPETITOR_MIN_DELAY:
            errors.append(f"competitor: delay_seconds debe ser al menos {COMPETITOR_MIN_DELAY}")
        if isinstance(crawl.max_urls, int) and not isinstance(crawl.max_urls, bool) \
                and crawl.max_urls > COMPETITOR_MAX_URLS:
            errors.append(f"competitor: max_urls no puede superar {COMPETITOR_MAX_URLS}")
        if "http" not in ua.lower():
            errors.append("competitor: user_agent debe incluir una URL de contacto (http...)")
        if any(bot in ua.lower() for bot in ("googlebot", "bingbot", "adsbot")):
            errors.append("competitor: user_agent no puede imitar a un buscador")
        if crawl.compare_googlebot_ua:
            errors.append("competitor: compare_googlebot_ua no está permitido en sitios ajenos")

    thresholds_raw = _as_dict(raw.get("thresholds"))
    thresholds = Thresholds(
        title_max_chars=thresholds_raw.get("title_max_chars", 60),
        meta_description_max_chars=thresholds_raw.get("meta_description_max_chars", 160),
    )

    sheets_raw = _as_dict(raw.get("sheets"))
    sheets = SheetsConfig(
        spreadsheet_id=str(sheets_raw.get("spreadsheet_id", "") or ""),
        drive_folder_id=str(sheets_raw.get("drive_folder_id", "") or ""),
    )

    if errors:
        raise ConfigError(errors)

    return ClientConfig(
        name=name.strip(),
        domain=domain,
        mode=mode,
        authorized=authorized,
        crawl=crawl,
        thresholds=thresholds,
        sheets=sheets,
    )


def load_config(path: str | Path) -> ClientConfig:
    """Lee un archivo YAML y lo valida."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_config(yaml.safe_load(text))
