"""Punto de entrada: `python -m seo_auditor_app` abre la ventana. `--selftest` verifica el paquete sin usar la red."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def selftest() -> int:
    """Prueba de humo para el instalador: importa todo y, si hay pantalla, arma y cierra la ventana."""
    lines, ok = [], True

    def step(name, fn):
        nonlocal ok
        try:
            lines.append(f"OK   {name}: {fn() or ''}".rstrip())
        except Exception as exc:  # noqa: BLE001
            ok = False
            lines.append(f"FALLA {name}: {type(exc).__name__}: {exc}")

    from . import __version__, core, store

    step("version", lambda: __version__)
    step("requests+certifi", lambda: __import__("certifi").where() and "certificados presentes")
    step("keyring", lambda: type(__import__("keyring").get_keyring()).__name__)
    tmp = Path(tempfile.mkdtemp())
    step("ajustes", lambda: store.Settings(tmp).save({"repo": "a/b"}) or store.Settings(tmp).load()["repo"])
    step("token", lambda: store.TokenStore(tmp, use_keyring=False).save("a/b", "x") and "archivo")

    def gui():
        from .gui import App
        try:
            app = App(settings=store.Settings(tmp), tokens=store.TokenStore(tmp, use_keyring=False))
        except Exception as exc:  # noqa: BLE001
            if "display" in str(exc).lower() and not os.environ.get("REQUIRE_GUI"):
                return "sin pantalla (se omite)"
            raise
        app.root.update()
        app.root.destroy()
        return "ventana creada y cerrada"
    step("ventana", gui)
    text = "\n".join(lines)
    out = os.environ.get("SEO_APP_SELFTEST_OUT")
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")   # el .exe sin consola no puede imprimir
    print(text)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    from .gui import App
    App().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
