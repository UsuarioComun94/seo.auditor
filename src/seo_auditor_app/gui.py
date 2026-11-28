"""Ventana de la app (Tkinter, viene con Python: sin dependencias extra). La lógica está en core.py."""

from __future__ import annotations

import queue
import threading
import webbrowser

from . import __version__
from .core import AppError, GitHubClient, RunInfo, clean_repo
from .store import Settings, TokenStore

REFRESH_MS = 20_000


class App:
    def __init__(self, settings: Settings | None = None, tokens: TokenStore | None = None, client_factory=GitHubClient):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.settings, self.tokens = settings or Settings(), tokens or TokenStore()
        self.client_factory = client_factory
        self.values = self.settings.load()
        self.runs: list[RunInfo] = []
        self.inbox: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title(f"seo.auditor {__version__}")
        self.root.geometry("760x560")
        self.root.minsize(640, 480)
        self._build()
        self.root.after(200, self._poll_inbox)
        if self.tokens.load(self.values["repo"]):
            self.refresh()
            self.root.after(REFRESH_MS, self._auto_refresh)
        else:
            self._status("Primero pegá tu token de GitHub (abajo, en «Conexión») y tocá Guardar.")

    # ---------- construcción ----------
    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 12, "pady": 6}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Auditar sitios", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(top, text="Escribí el nombre del sitio tal como está en el Panel, o «all» para todos.").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=6)
        self.site = tk.StringVar(value=self.values["site"])
        ttk.Entry(row, textvariable=self.site, width=34).pack(side="left")
        self.run_btn = ttk.Button(row, text="Auditar ahora", command=self.audit)
        self.run_btn.pack(side="left", padx=8)

        mid = ttk.LabelFrame(self.root, text="Últimas ejecuciones")
        mid.pack(fill="both", expand=True, **pad)
        cols = ("fecha", "origen", "estado")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=8, selectmode="browse")
        for col, text, width in (("fecha", "Cuándo", 110), ("origen", "Quién la lanzó", 260), ("estado", "Estado", 160)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda e: self.open_run())
        btns = ttk.Frame(mid)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Actualizar", command=self.refresh).pack(side="left")
        ttk.Button(btns, text="Ver detalle en GitHub", command=self.open_run).pack(side="left", padx=8)
        ttk.Button(btns, text="Abrir mi Panel", command=self.open_panel).pack(side="left")

        conn = ttk.LabelFrame(self.root, text="Conexión")
        conn.pack(fill="x", **pad)
        self.repo = tk.StringVar(value=self.values["repo"])
        self.panel = tk.StringVar(value=self.values["panel_url"])
        self.token = tk.StringVar()
        grid = ttk.Frame(conn)
        grid.pack(fill="x", padx=8, pady=8)
        for r, (label, var, secret) in enumerate((("Repositorio", self.repo, False),
                                                  ("Enlace a tu Panel (opcional)", self.panel, False),
                                                  ("Token de GitHub", self.token, True))):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(grid, textvariable=var, width=52, show="•" if secret else "").grid(row=r, column=1, sticky="we", padx=8)
        grid.columnconfigure(1, weight=1)
        ttk.Button(grid, text="Guardar", command=self.save).grid(row=2, column=2, padx=4)
        ttk.Button(grid, text="Cómo conseguir el token", command=self.help_token).grid(row=3, column=1, sticky="w", pady=4)

        self.status = tk.StringVar()
        ttk.Label(self.root, textvariable=self.status, anchor="w", wraplength=720).pack(fill="x", padx=12, pady=(0, 10))

    # ---------- acciones ----------
    def _status(self, text: str) -> None:
        self.status.set(text)

    def _client(self) -> GitHubClient:
        repo = clean_repo(self.repo.get())
        token = self.tokens.load(repo)
        return self.client_factory(token, repo)

    def _bg(self, work, done) -> None:
        """Trabajo de red en otro hilo para que la ventana no se congele."""
        def run():
            try:
                self.inbox.put((done, work(), None))
            except AppError as exc:
                self.inbox.put((done, None, str(exc)))
            except Exception as exc:  # noqa: BLE001
                self.inbox.put((done, None, f"Error inesperado ({type(exc).__name__})."))
        threading.Thread(target=run, daemon=True).start()

    def _poll_inbox(self) -> None:
        try:
            while True:
                done, result, error = self.inbox.get_nowait()
                done(result, error)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_inbox)

    def save(self) -> None:
        try:
            repo = clean_repo(self.repo.get())
        except AppError as exc:
            return self._status(str(exc))
        self.settings.save({"repo": repo, "panel_url": self.panel.get().strip(), "site": self.site.get().strip() or "all"})
        token = self.token.get().strip()
        if token:
            where = self.tokens.save(repo, token)
            self.token.set("")
            self._status(f"Guardado {where}. Probando la conexión…")
            self._bg(lambda: self._client().check(), lambda r, e: self._status(e or "Conexión correcta. Ya podés auditar.") or self.refresh())
        else:
            self._status("Ajustes guardados.")

    def audit(self) -> None:
        site = self.site.get()
        self.run_btn.state(["disabled"])
        self._status("Enviando la orden a GitHub…")

        def done(_r, error):
            self.run_btn.state(["!disabled"])
            if error:
                return self._status(error)
            self.settings.save({**self.values, "repo": self.repo.get().strip(), "panel_url": self.panel.get().strip(),
                                "site": site.strip()})
            self._status("Listo: la auditoría está en marcha. Tarda entre 3 y 10 minutos; esta lista se actualiza sola.")
            self.root.after(4000, self.refresh)

        self._bg(lambda: self._client().dispatch(site), done)

    def refresh(self) -> None:
        def done(runs, error):
            if error:
                return self._status(error)
            self.runs = runs
            self.tree.delete(*self.tree.get_children())
            for i, r in enumerate(runs):
                self.tree.insert("", "end", iid=str(i), values=(r.local_time(), r.origin, r.label))
            if runs and runs[0].conclusion == "failure":
                self._status("La última ejecución terminó con errores: puede ser un sitio del Panel con algún problema. "
                             "Tocá «Ver detalle en GitHub».")
        self._bg(lambda: self._client().runs(), done)

    def _auto_refresh(self) -> None:
        if any(r.running for r in self.runs):
            self.refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    def open_run(self) -> None:
        sel = self.tree.selection()
        if sel and self.runs:
            webbrowser.open(self.runs[int(sel[0])].url)
        else:
            self._status("Elegí una ejecución de la lista.")

    def open_panel(self) -> None:
        url = self.panel.get().strip()
        if url.startswith("https://"):
            webbrowser.open(url)
        else:
            self._status("Pegá el enlace de tu planilla Panel (empieza con https://) y tocá Guardar.")

    def help_token(self) -> None:
        webbrowser.open("https://github.com/settings/personal-access-tokens/new")
        self._status("En GitHub: elegí «Only select repositories» → este repo; en Permissions → Repository → "
                     "Actions: «Read and write»; creá el token y pegalo acá.")

    def run(self) -> None:
        self.root.mainloop()
