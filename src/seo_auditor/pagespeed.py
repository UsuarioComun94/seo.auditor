"""Rendimiento (fase 4): laboratorio con PageSpeed Insights y campo con la API de CrUX. Ambas son gratuitas.

- PSI (Lighthouse en servidores de Google, móvil simulado): la clave es opcional pero recomendada; sin clave
  la cuota compartida suele agotarse (429) desde IPs de runners.
- CrUX API (datos reales de usuarios de Chrome, p75): exige clave. Sin datos del sitio devuelve 404: no es un error.
- La clave nunca se imprime ni se guarda: los mensajes de error no incluyen la URL del pedido.

Los datos de laboratorio son una simulación (móvil lento): sirven para comparar y detectar regresiones, no
representan a los usuarios reales. Los de campo sí, pero solo existen para sitios con tráfico suficiente.
"""

from __future__ import annotations

import time

import requests

from .urls import canon_key

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CRUX_URL = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"


class PerfError(RuntimeError):
    pass


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PsiClient:
    def __init__(self, api_key: str = "", base_url: str = PSI_URL, session: requests.Session | None = None,
                 sleep=time.sleep, timeout: float = 120.0, retries: int = 2):
        self.key, self.base_url = api_key, base_url
        self.session, self._sleep, self.timeout, self.retries = session or requests.Session(), sleep, timeout, retries

    def lab(self, url: str, strategy: str = "mobile") -> dict:
        params = {"url": url, "strategy": strategy, "category": "performance"}
        if self.key:
            params["key"] = self.key
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(self.base_url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                raise PerfError(f"PSI no respondió ({type(exc).__name__})") from None   # sin URL: llevaría la clave
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                self._sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 429:
                raise PerfError("PSI: cuota agotada (429)" + ("" if self.key else "; usá una clave PSI_API_KEY"))
            if resp.status_code != 200:
                raise PerfError(f"PSI respondió {resp.status_code}")
            break
        try:
            lh = resp.json()["lighthouseResult"]
        except (ValueError, KeyError):
            raise PerfError("PSI devolvió una respuesta inesperada") from None
        audits = lh.get("audits", {})
        score = _num((lh.get("categories", {}).get("performance") or {}).get("score"))
        value = lambda aid: _num((audits.get(aid) or {}).get("numericValue"))   # noqa: E731
        return {
            "score": None if score is None else round(score * 100),
            "lcp_ms": value("largest-contentful-paint"), "cls": value("cumulative-layout-shift"),
            "tbt_ms": value("total-blocking-time"), "fcp_ms": value("first-contentful-paint"),
            "ttfb_ms": value("server-response-time"), "speed_index_ms": value("speed-index"),
        }


class CruxClient:
    def __init__(self, api_key: str, base_url: str = CRUX_URL, session: requests.Session | None = None,
                 timeout: float = 30.0):
        self.key, self.base_url = api_key, base_url
        self.session, self.timeout = session or requests.Session(), timeout

    def origin(self, origin: str, form_factor: str = "PHONE") -> dict:
        """p75 de campo del origen. {} si Chrome no tiene datos suficientes (404)."""
        try:
            resp = self.session.post(self.base_url, params={"key": self.key}, timeout=self.timeout,
                                     json={"origin": origin, "formFactor": form_factor})
        except requests.RequestException as exc:
            raise PerfError(f"CrUX no respondió ({type(exc).__name__})") from None
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise PerfError(f"CrUX respondió {resp.status_code}")
        try:
            metrics = resp.json()["record"]["metrics"]
        except (ValueError, KeyError):
            raise PerfError("CrUX devolvió una respuesta inesperada") from None
        p75 = lambda name: _num(((metrics.get(name) or {}).get("percentiles") or {}).get("p75"))   # noqa: E731
        return {"lcp_ms": p75("largest_contentful_paint"), "inp_ms": p75("interaction_to_next_paint"),
                "cls": p75("cumulative_layout_shift"), "ttfb_ms": p75("experimental_time_to_first_byte")}


def pick_pages(result, root: str, limit: int) -> list[str]:
    """La home y las páginas indexables más enlazadas (donde un problema de velocidad pesa más)."""
    inlinks: dict[str, int] = {}
    for p in result.pages.values():
        for link in set(p.links):
            inlinks[canon_key(link)] = inlinks.get(canon_key(link), 0) + 1
    indexable = [p for p in result.pages.values() if p.indexable]
    indexable.sort(key=lambda p: (-inlinks.get(canon_key(p.url), 0), p.url))
    chosen, seen = [], set()
    for url in [root] + [p.url for p in indexable]:
        key = canon_key(url)
        if key not in seen and (url == root or url in result.pages):
            seen.add(key)
            chosen.append(url)
        if len(chosen) >= max(limit, 1):
            break
    return chosen


def measure(result, root: str, psi: PsiClient | None, crux: CruxClient | None, max_pages: int, log=print) -> None:
    """Llena result.perf (filas) y result.perf_status: ok | parcial | no_disponible. Nunca lanza."""
    result.perf, result.perf_status = [], "no_disponible"
    if psi is None:
        return
    ok = failed = 0
    for url in pick_pages(result, root, max_pages):
        try:
            result.perf.append({"url": url, "strategy": "mobile", **psi.lab(url), "error": ""})
            ok += 1
        except PerfError as exc:
            result.perf.append({"url": url, "strategy": "mobile", "error": str(exc)})
            failed += 1
            if "cuota" in str(exc):          # no tiene sentido seguir pidiendo
                break
    if crux is not None:
        try:
            field = crux.origin(_origin(root))
            if field and result.perf:
                result.perf[0]["field"] = field
            elif not field:
                result.notes.append("CrUX: Chrome no tiene datos de campo suficientes para este origen")
        except PerfError as exc:
            result.notes.append(str(exc))
    else:
        result.notes.append("sin clave de API: no se consultan datos de campo (CrUX)")
    result.perf_status = "ok" if ok and not failed else ("parcial" if ok else "no_disponible")
    errors = sorted({r["error"] for r in result.perf if r.get("error")})
    if errors:
        result.notes.append("PageSpeed: " + "; ".join(errors))
    log(f"rendimiento: {ok} páginas medidas, {failed} con error")


def _origin(url: str) -> str:
    from urllib.parse import urlsplit
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"
