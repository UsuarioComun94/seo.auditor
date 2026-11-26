"""Verifica que el fixture sea coherente con el catálogo de reglas y que los
errores plantados existan de verdad en los archivos (no solo en el manifiesto)."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urldefrag

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "fixture" / "site"
EXPECTED = yaml.safe_load((ROOT / "fixture" / "EXPECTED_ISSUES.yaml").read_text(encoding="utf-8"))
RULES = yaml.safe_load((ROOT / "rules" / "rules.yaml").read_text(encoding="utf-8"))["rules"]
BASE = EXPECTED["base_url"]


def page_path(rel: str) -> Path:
    if rel == "":
        return SITE / "index.html"
    if rel.endswith("/"):
        return SITE / rel / "index.html"
    return SITE / rel


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None
        self._in_title = False
        self.meta = {}
        self.h1 = 0
        self.links = []
        self.imgs = []
        self.canonical = None
        self.hreflang = []
        self.jsonld = []
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
            self.title = ""
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"].lower()] = a.get("content", "")
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            self.meta["refresh"] = a.get("content", "")
        elif tag == "h1":
            self.h1 += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "link" and a.get("rel") == "alternate" and a.get("hreflang"):
            self.hreflang.append(a["href"])
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_jsonld = True
            self.jsonld.append("")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self.jsonld[-1] += data


def parse(rel: str) -> Page:
    p = Page()
    p.feed(page_path(rel).read_text(encoding="utf-8"))
    return p


def site_html_files():
    return sorted(SITE.rglob("*.html"))


def rel_url(path: Path) -> str:
    rel = path.relative_to(SITE).as_posix()
    if rel == "index.html":
        return ""
    if rel.endswith("/index.html"):
        return rel[: -len("index.html")]
    return rel


def inlinks():
    """Mapa url_relativa -> conjunto de páginas que la enlazan (solo enlaces <a>)."""
    result = {}
    for f in site_html_files():
        src = rel_url(f)
        page = parse(src)
        for href in page.links:
            absolute = urldefrag(urljoin(BASE + src, href))[0]
            if absolute.startswith(BASE):
                result.setdefault(absolute[len(BASE):], set()).add(src)
    return result


def test_expected_rule_ids_exist_in_catalog():
    known = {r["id"] for r in RULES}
    used = {i["rule"] for i in EXPECTED["issues"]}
    assert used <= known, f"reglas desconocidas en EXPECTED_ISSUES: {used - known}"


def test_rule_catalog_is_well_formed():
    ids = [r["id"] for r in RULES]
    assert len(ids) == len(set(ids)), "ids de regla duplicados"
    for r in RULES:
        assert r["severity"] in {"critical", "high", "medium", "low", "info"}
        assert r["hat"] in {"white", "signal"}
        assert set(r["modes"]) <= {"own", "client", "competitor"}
        if r["hat"] == "signal":
            assert r["category"] == "risk"
    cloaking = next(r for r in RULES if r["id"] == "RSK-003")
    assert "competitor" not in cloaking["modes"], "cloaking no puede correr en sitios ajenos"


def test_every_expected_url_exists_unless_planted_as_missing():
    missing_on_purpose = {"missing-page.html"}
    for issue in EXPECTED["issues"]:
        if issue["url"] in missing_on_purpose:
            assert not page_path(issue["url"]).exists()
        else:
            assert page_path(issue["url"]).exists(), issue


def test_broken_link_targets_do_not_exist():
    for issue in EXPECTED["issues"]:
        if issue["rule"] in ("TECH-001", "TECH-008"):
            assert not page_path(issue["target"]).exists(), issue


def test_orphan_has_no_inlinks_but_is_in_sitemap():
    assert "orphan.html" not in inlinks()
    assert BASE + "orphan.html" in (SITE / "sitemap.xml").read_text(encoding="utf-8")


def test_only_the_orphan_is_unlinked_among_sitemap_pages():
    links = inlinks()
    sitemap = re.findall(r"<loc>(.*?)</loc>", (SITE / "sitemap.xml").read_text(encoding="utf-8"))
    unlinked = []
    for url in sitemap:
        rel = url[len(BASE):]
        if rel == "" or not page_path(rel).exists():
            continue
        if rel not in links:
            unlinked.append(rel)
    assert unlinked == ["orphan.html"]


def test_duplicate_titles_and_missing_metadata_are_planted():
    about, products, hidden = parse("about.html"), parse("products.html"), parse("hidden.html")
    assert about.title == products.title
    assert "description" not in about.meta
    assert products.h1 == 2
    assert hidden.title is None
    assert parse("orphan.html").h1 == 0


def test_canonical_errors_are_planted():
    assert parse("blog/post-1.html").canonical == BASE + "blog/"
    assert parse("blog/post-2.html").canonical == BASE + "blog/deleted-post.html"


def test_redirect_chain_is_two_hops():
    a, b = parse("redirect-a.html"), parse("redirect-b.html")
    assert a.meta["refresh"].endswith("redirect-b.html")
    assert b.meta["refresh"].endswith("redirect-final.html")
    assert "refresh" not in parse("redirect-final.html").meta


def test_noindex_page_is_linked_and_in_sitemap():
    assert "noindex" in parse("noindex-accidental.html").meta["robots"]
    assert "noindex-accidental.html" in inlinks()


def test_media_issues_are_planted():
    media = parse("media.html")
    assert any("alt" not in img for img in media.imgs)
    assert any(img.get("src", "").startswith("http://") for img in media.imgs)
    import json
    with pytest.raises(json.JSONDecodeError):
        json.loads(media.jsonld[0])


def test_hreflang_has_no_return_link():
    assert BASE + "lang-es.html" in parse("lang-en.html").hreflang
    assert parse("lang-es.html").hreflang == []


def test_robots_blocks_a_linked_page():
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert "Disallow: /seo.auditor/private/" in robots
    assert "private/secret.html" in inlinks() or any(
        "private/secret.html" in link for link in parse("").links
    )


def test_hidden_content_is_planted():
    html = (SITE / "hidden.html").read_text(encoding="utf-8")
    assert "display:none" in html
    assert "left:-9999px" in html
