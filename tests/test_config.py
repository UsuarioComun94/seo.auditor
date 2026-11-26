from pathlib import Path

import pytest

from seo_auditor.config import ConfigError, load_config, parse_config

ROOT = Path(__file__).resolve().parent.parent

GOOD_UA = "seo-auditor/0.1 (+https://github.com/UsuarioComun94/seo.auditor)"


def competitor(**crawl_overrides):
    crawl = {
        "max_urls": 200,
        "delay_seconds": 2.5,
        "respect_robots": True,
        "user_agent": GOOD_UA,
        "compare_googlebot_ua": False,
    }
    crawl.update(crawl_overrides)
    return {
        "name": "rival",
        "domain": "https://www.ejemplo.com",
        "mode": "competitor",
        "crawl": crawl,
    }


def test_fixture_config_is_valid():
    cfg = load_config(ROOT / "clients" / "fixture.yaml")
    assert cfg.mode == "own"
    assert cfg.domain.startswith("https://")


def test_template_without_authorization_is_rejected():
    # La plantilla viene con mode: client y authorized: false a propósito.
    with pytest.raises(ConfigError) as exc:
        load_config(ROOT / "clients" / "_template.yaml")
    assert any("authorized" in e for e in exc.value.errors)


def test_valid_competitor_config_passes():
    cfg = parse_config(competitor())
    assert cfg.mode == "competitor"


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"respect_robots": False}, "respect_robots"),
        ({"delay_seconds": 0.5}, "delay_seconds"),
        ({"max_urls": 5000}, "max_urls"),
        ({"user_agent": "seo-auditor/0.1"}, "URL de contacto"),
        ({"user_agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}, "imitar"),
        ({"compare_googlebot_ua": True}, "compare_googlebot_ua"),
    ],
)
def test_competitor_rules_are_enforced(override, fragment):
    with pytest.raises(ConfigError) as exc:
        parse_config(competitor(**override))
    assert any(fragment in e for e in exc.value.errors)


def test_client_requires_authorization():
    raw = {"name": "c", "domain": "https://x.com", "mode": "client"}
    with pytest.raises(ConfigError):
        parse_config(raw)
    raw["authorized"] = True
    assert parse_config(raw).authorized is True


def test_invalid_basics_report_all_errors_at_once():
    with pytest.raises(ConfigError) as exc:
        parse_config({"name": "", "domain": "ejemplo.com", "mode": "otro"})
    assert len(exc.value.errors) == 3


def test_non_mapping_is_rejected():
    with pytest.raises(ConfigError):
        parse_config(["no", "es", "un", "mapa"])
