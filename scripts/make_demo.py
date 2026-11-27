"""Genera la demo pública (docs/demo/report.html y capturas en docs/img/) con el sitio fixture.

Solo usa datos del fixture público: nunca sitios reales. Reproducible:
    python scripts/make_demo.py
"""

from __future__ import annotations

import html
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

from conftest import PREFIX, _fixture_handler, _Server  # noqa: E402  (servidor local del fixture)

from seo_auditor.checks import run_checks  # noqa: E402
from seo_auditor.config import parse_config  # noqa: E402
from seo_auditor.crawler import Crawler  # noqa: E402
from seo_auditor.benchmark import compute_benchmark  # noqa: E402
from seo_auditor.report import load_schema  # noqa: E402
from seo_auditor.rules import load_rules  # noqa: E402
from seo_auditor.score import compute_comparable_score, compute_score  # noqa: E402
from seo_auditor.urls import Scope  # noqa: E402

SEV = {"critical": "Crítico", "high": "Alto", "medium": "Medio", "low": "Bajo"}
CSS = """
:root{--bg:#fff;--fg:#1f2328;--mut:#656d76;--line:#d0d7de;--card:#f6f8fa;--c:#cf222e;--h:#bc4c00;--m:#9a6700;--l:#0969da}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8d96a0;--line:#30363d;--card:#161b22;--c:#ff7b72;--h:#ffa657;--m:#e3b341;--l:#79c0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.mut{color:var(--mut)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}.card b{display:block;font-size:26px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--card);position:sticky;top:0}code{font-size:12px;word-break:break-all}td:nth-child(2) code{white-space:nowrap}
.tag{display:inline-block;padding:0 6px;border-radius:10px;font-size:12px;border:1px solid currentColor}
.critical{color:var(--c)}.high{color:var(--h)}.medium{color:var(--m)}.low{color:var(--l)}.wrap{overflow-x:auto}
"""


def build() -> dict:
    server = _Server(_fixture_handler(lambda: holder["origin"]))
    holder = {"origin": server.origin}
    base = server.origin + PREFIX
    try:
        cfg = parse_config({"name": "fixture", "domain": base, "mode": "own",
                            "crawl": {"max_urls": 200, "delay_seconds": 0,
                                      "user_agent": "seo-auditor/0.1 (+https://github.com/UsuarioComun94/seo.auditor)"}})
        result = Crawler(cfg).run()
    finally:
        server.close()
    rules, schema = load_rules(), load_schema()
    issues = run_checks(result, rules, Scope(base))
    w = schema["severity_weights"]
    return {"base": base, "result": result, "issues": issues, "rules": rules,
            "score": compute_score(issues, len(result.pages), w, schema["score_scale"]),
            "comparable": compute_comparable_score(issues, len(result.pages), w, rules, schema["score_scale"]),
            "bench": compute_benchmark(result)}


def page(d: dict) -> str:
    esc = lambda s: html.escape(str(s))                                   # noqa: E731
    short = lambda u: esc(u.replace(d["base"], "/"))                      # noqa: E731
    PUBLIC = "https://usuariocomun94.github.io/seo.auditor/"
    origin = d["base"].rsplit("/seo.auditor/", 1)[0]
    clean = lambda t: esc(str(t).replace(d["base"], PUBLIC).replace(origin, "https://usuariocomun94.github.io"))  # noqa: E731
    white = [i for i in d["issues"] if i.hat == "white"]
    risk = [i for i in d["issues"] if i.hat == "signal"]
    counts = Counter(i.severity for i in white)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows = "".join(
        f'<tr><td><span class="tag {i.severity}">{SEV[i.severity]}</span></td><td><code>{esc(i.rule_id)}</code></td>'
        f"<td><code>{short(i.url)}</code></td><td>{clean(i.detail)}</td></tr>"
        for i in sorted(white, key=lambda i: (order[i.severity], i.rule_id, i.url)))
    rrows = "".join(f'<tr><td><code>{esc(i.rule_id)}</code></td><td><code>{short(i.url)}</code></td><td>{clean(i.detail)}</td></tr>'
                    for i in risk)
    b = d["bench"]
    cards = "".join(f'<div class="card"><span class="mut">{k}</span><b>{v}</b></div>' for k, v in [
        ("Puntaje de salud", d["score"]), ("URLs rastreadas", len(d["result"].pages)),
        ("Críticos / altos", f'{counts["critical"]} / {counts["high"]}'), ("Medios / bajos", f'{counts["medium"]} / {counts["low"]}'),
        ("Señales de riesgo", len(risk)), ("Title presente", f'{b["pct_title"]}%'), ("H1 único", f'{b["pct_h1_unico"]}%')])
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demo seo.auditor</title><style>{CSS}</style></head><body><main>
<h1>seo.auditor — informe de demo</h1>
<p class="mut">Sitio de prueba público con errores plantados a propósito. No hay datos de clientes ni de sitios reales.</p>
<div class="cards">{cards}</div>
<h2>Issues técnicos y on-page ({len(white)})</h2><div class="wrap"><table><tr><th>Severidad</th><th>Regla</th><th>URL</th><th>Detalle</th></tr>{rows}</table></div>
<h2>Señales de riesgo grey/black hat ({len(risk)}) — solo detección, fuera del puntaje</h2>
<div class="wrap"><table><tr><th>Regla</th><th>URL</th><th>Evidencia</th></tr>{rrows}</table></div>
</main></body></html>"""


def main() -> None:
    data = build()
    out = ROOT / "docs" / "demo" / "report.html"
    out.write_text(page(data), encoding="utf-8")
    print(f"informe: {out} | issues={len(data['issues'])} score={data['score']}")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1000, "height": 700}, device_scale_factor=2)
        pg = ctx.new_page()
        pg.goto(out.as_uri())
        pg.screenshot(path=str(ROOT / "docs" / "img" / "demo-informe.png"), full_page=True)
        pg.set_viewport_size({"width": 390, "height": 800})
        pg.screenshot(path=str(ROOT / "docs" / "img" / "demo-informe-movil.png"), full_page=False)
        browser.close()


if __name__ == "__main__":
    main()
