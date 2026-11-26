"""Crawler real contra servidores locales: recall del fixture y comportamientos HTTP."""

import pytest

from conftest import PREFIX, ROOT, local_config
from seo_auditor.checks import run_checks
from seo_auditor.crawler import CrawlAbort, Crawler
from seo_auditor.expected import check_expected
from seo_auditor.fetcher import Fetcher
from seo_auditor.rules import load_rules
from seo_auditor.urls import Scope

RULES = load_rules()
EXPECTED = ROOT / "fixture" / "EXPECTED_ISSUES.yaml"


@pytest.fixture(scope="module")
def fixture_run(fixture_server):
    base = fixture_server.origin + PREFIX
    cfg = local_config(base, robots_url=base + "robots.txt")
    result = Crawler(cfg).run()
    return base, result, run_checks(result, RULES, Scope(base))


def test_fixture_recall_is_100_percent(fixture_run):
    base, result, issues = fixture_run
    report = check_expected(issues, EXPECTED, RULES, "own", base_url=base,
                            skip_rules={"TECH-011": "el servidor de test no usa HTTPS"})
    assert report.checked >= 17
    assert report.missing == [], f"no detectados: {report.missing}"


def test_phase_2_and_5_rules_are_not_claimed_yet(fixture_run):
    _, _, issues = fixture_run
    assert not {i.rule_id for i in issues} & {"TECH-007", "SCH-001", "INT-001", "RSK-001", "RSK-002"}


def test_blocked_page_is_not_fetched(fixture_run):
    base, result, _ = fixture_run
    assert base + "private/secret.html" not in result.pages
    assert base + "private/secret.html" in result.blocked_links


def test_external_dead_link_is_reported(fixture_run):
    _, _, issues = fixture_run
    assert any(i.rule_id == "TECH-002" and "example.invalid" in i.target for i in issues)


def test_no_false_positive_on_clean_pages(fixture_run):
    base, _, issues = fixture_run
    clean = {base + "blog/", base + "redirect-final.html", base + "lang-es.html"}
    noisy = [i for i in issues if i.url in clean and i.severity in ("critical", "high", "medium")]
    assert noisy == []


def test_real_http_redirect_chain_and_loop(behavior_server):
    o = behavior_server.origin
    cfg = local_config(o + "/", robots_url=o + "/robots.txt")
    result = Crawler(cfg).run()
    issues = run_checks(result, RULES, Scope(o + "/"))
    by = {(i.rule_id, i.url) for i in issues}
    assert ("TECH-003", o + "/chain-1") in by
    assert ("TECH-004", o + "/loop-a") in by
    assert ("TECH-006", o + "/gone") in by           # 410 en el sitemap
    assert ("TECH-006", o + "/chain-1") in by        # redirección en el sitemap


def test_x_robots_tag_header_counts_as_noindex(behavior_server):
    o = behavior_server.origin
    result = Crawler(local_config(o + "/", robots_url=o + "/robots.txt")).run()
    assert result.pages[o + "/xrobots"].noindex
    issues = run_checks(result, RULES, Scope(o + "/"))
    assert ("TECH-005", o + "/xrobots") in {(i.rule_id, i.url) for i in issues}


def test_robots_blocked_link_flagged_and_not_crawled(behavior_server):
    o = behavior_server.origin
    result = Crawler(local_config(o + "/", robots_url=o + "/robots.txt")).run()
    assert o + "/blocked/page" not in result.pages
    issues = run_checks(result, RULES, Scope(o + "/"))
    assert ("TECH-010", o + "/blocked/page") in {(i.rule_id, i.url) for i in issues}


def test_max_urls_truncates(behavior_server):
    o = behavior_server.origin
    result = Crawler(local_config(o + "/", max_urls=2, robots_url=o + "/robots.txt")).run()
    assert len(result.pages) == 2 and result.truncated


def test_competitor_mode_skips_external_checks_and_cloaking_rule(behavior_server):
    o = behavior_server.origin
    cfg = local_config(o + "/", mode="competitor", delay_seconds=2.0, robots_url=o + "/robots.txt")
    result = Crawler(cfg, fetcher=Fetcher(cfg.crawl.user_agent, delay_seconds=0)).run()
    assert result.external == {}
    assert "TECH-002" not in {i.rule_id for i in run_checks(result, RULES, Scope(o + "/"))}


def test_competitor_aborts_when_robots_is_unreachable():
    # Puerto cerrado: sin robots.txt confiable no se rastrea un sitio ajeno.
    cfg = local_config("http://127.0.0.1:9/", mode="competitor", delay_seconds=2.0)
    with pytest.raises(CrawlAbort):
        Crawler(cfg, fetcher=Fetcher(cfg.crawl.user_agent, delay_seconds=0)).run()


def test_own_mode_continues_when_robots_is_unreachable():
    cfg = local_config("http://127.0.0.1:9/")
    result = Crawler(cfg, fetcher=Fetcher(cfg.crawl.user_agent, delay_seconds=0, timeout=2)).run()
    assert any("robots.txt no disponible" in n for n in result.notes)
