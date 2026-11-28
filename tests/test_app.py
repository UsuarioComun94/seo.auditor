"""App de escritorio: lógica sin pantalla (la ventana se verifica en el workflow con Tk real)."""

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from seo_auditor_app.core import AppError, GitHubClient, RunInfo, clean_repo, clean_site
from seo_auditor_app.store import Settings, TokenStore


class _Gh(BaseHTTPRequestHandler):
    status = 200
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        body = json.dumps(obj or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _Gh.seen.append(("GET", self.path, self.headers.get("Authorization"), None))
        if _Gh.status != 200:
            return self._send(_Gh.status)
        if self.path.endswith("/runs?per_page=2"):
            return self._send(200, {"workflow_runs": [
                {"id": 2, "event": "workflow_dispatch", "status": "in_progress", "conclusion": None,
                 "created_at": "2026-11-27T12:00:00Z", "html_url": "https://github.com/x/y/actions/runs/2"},
                {"id": 1, "event": "schedule", "status": "completed", "conclusion": "failure",
                 "created_at": "2026-11-24T09:00:00Z", "html_url": "https://github.com/x/y/actions/runs/1"}]})
        self._send(200, {"name": "Auditoría SEO"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        _Gh.seen.append(("POST", self.path, self.headers.get("Authorization"), body))
        self._send(204 if _Gh.status == 200 else _Gh.status)


@pytest.fixture
def gh():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Gh)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Gh.status = 200
    _Gh.seen.clear()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def client(base, token="tok"):
    return GitHubClient(token, "u/r", base_url=base)


def test_check_and_dispatch_send_the_right_requests(gh):
    c = client(gh)
    assert c.check() == "Auditoría SEO"
    c.dispatch("  Mi Sitio ")
    method, path, auth, body = _Gh.seen[-1]
    assert (method, path) == ("POST", "/repos/u/r/actions/workflows/audit.yml/dispatches")
    assert auth == "Bearer tok"
    assert body == {"ref": "main", "inputs": {"client": "fixture", "publish": "false", "site": "Mi Sitio"}}


def test_runs_are_translated_to_plain_spanish(gh):
    a, b = client(gh).runs(limit=2)
    assert (a.label, a.running, a.origin) == ("En curso", True, "Manual desde la app o GitHub")
    assert (b.label, b.running, b.origin) == ("Terminó con errores", False, "Automática (semanal)")
    assert a.url.endswith("/runs/2") and ":" in a.local_time()


@pytest.mark.parametrize("code,fragment", [(401, "no es válido"), (403, "permiso"), (404, "No encuentro"), (422, "rechazó"), (500, "500")])
def test_http_errors_become_friendly_messages_without_the_token(gh, code, fragment):
    _Gh.status = code
    with pytest.raises(AppError) as e:
        client(gh, token="SECRETTOKEN").check()
    assert fragment in str(e.value) and "SECRETTOKEN" not in str(e.value)


def test_network_error_message_has_no_token_or_url():
    with pytest.raises(AppError) as e:
        GitHubClient("SECRETTOKEN", "u/r", base_url="http://127.0.0.1:9", timeout=1).check()
    assert "SECRETTOKEN" not in str(e.value) and "127.0.0.1" not in str(e.value) and "internet" in str(e.value)


def test_input_validation():
    for bad in ("", "   ", "a\nb", "x" * 101):
        with pytest.raises(AppError):
            clean_site(bad)
    assert clean_site(" all ") == "all"
    for bad in ("", "solo", "a/b/c", "a b/c"):
        with pytest.raises(AppError):
            clean_repo(bad)
    assert clean_repo("/u/r/") == "u/r"
    with pytest.raises(AppError, match="token"):
        GitHubClient("  ", "u/r")


def test_run_labels_cover_states():
    mk = lambda s, c="": RunInfo(1, "push", s, c, "2026-01-01T00:00:00Z", "")   # noqa: E731
    assert mk("completed", "success").label == "Terminó bien"
    assert mk("queued").label == "En cola" and mk("queued").running
    assert mk("completed", "cancelled").label == "Cancelada"


def test_settings_roundtrip_and_defaults(tmp_path):
    s = Settings(tmp_path / "cfg")
    assert s.load()["repo"] == "UsuarioComun94/seo.auditor" and s.load()["site"] == "all"
    s.save({"repo": "a/b", "panel_url": "https://x", "site": "uno", "otro": "ignorado"})
    assert s.load() == {"repo": "a/b", "panel_url": "https://x", "site": "uno"}
    (tmp_path / "cfg" / "settings.json").write_text("{roto", encoding="utf-8")
    assert s.load()["repo"] == "UsuarioComun94/seo.auditor"          # archivo dañado: vuelve a los valores base


def test_token_file_fallback_is_private_and_deletable(tmp_path):
    t = TokenStore(tmp_path, use_keyring=False)
    assert t.load("a/b") == ""
    assert "archivo" in t.save("a/b", "  tok123 ")
    assert t.load("a/b") == "tok123"
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(t.file).st_mode) == 0o600
    t.delete("a/b")
    assert t.load("a/b") == ""


def test_token_prefers_keyring_when_available(tmp_path):
    class KR:
        data = {}

        def set_password(self, s, u, p):
            self.data[(s, u)] = p

        def get_password(self, s, u):
            return self.data.get((s, u))

        def delete_password(self, s, u):
            self.data.pop((s, u), None)

    t = TokenStore(tmp_path, use_keyring=False)
    t._keyring = KR()
    assert "seguro" in t.save("a/b", "k1") and t.load("a/b") == "k1"
    assert not t.file.exists()                      # no quedó copia en disco
    t._keyring.set_password = lambda *a: (_ for _ in ()).throw(RuntimeError("sin backend"))
    assert "archivo" in t.save("a/b", "k2")        # el almacén falla: usa el archivo y no pierde el token


def test_selftest_runs_headless(tmp_path, monkeypatch):
    from seo_auditor_app.__main__ import main
    monkeypatch.setenv("SEO_APP_SELFTEST_OUT", str(tmp_path / "out.txt"))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    code = main(["--selftest"])
    text = (tmp_path / "out.txt").read_text()
    assert "OK   ajustes" in text and "OK   token" in text
    assert code in (0, 1)       # sin Tk ni keyring en este entorno puede fallar esos pasos; el resto debe estar OK
