"""CLI del auditor.

Fase 0: solo valida la config. El crawler se agrega en la fase 1.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seo_auditor", description="Auditor SEO autónomo")
    parser.add_argument("--config", required=True, help="Ruta al YAML del cliente")
    parser.add_argument("--validate-only", action="store_true", help="Solo validar la config y salir")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"ERROR: no existe {args.config}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print("ERROR: config inválida", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 2

    print(f"Config válida: {cfg.name} | {cfg.domain} | modo={cfg.mode} | max_urls={cfg.crawl.max_urls}")

    if args.validate_only:
        return 0

    print("El crawler todavía no está implementado (fase 1).", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
