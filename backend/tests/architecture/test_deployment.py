import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_the_api_trusts_forwarded_addresses_only_from_caddy() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    caddy_address = services["web"]["networks"]["default"]["ipv4_address"]

    assert services["api"]["environment"]["FORWARDED_ALLOW_IPS"] == caddy_address


def test_caddy_overwrites_the_forwarded_address_and_limits_request_size() -> None:
    caddyfile = (ROOT / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")

    assert "header_up X-Forwarded-For {remote_host}" in caddyfile
    assert "max_size 6MB" in caddyfile


def test_every_tls_mode_in_compose_has_a_caddy_snippet() -> None:
    snippets = {path.stem for path in (ROOT / "infra" / "caddy" / "tls").glob("*.caddy")}
    compose_files = "".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("docker-compose.yml", "docker-compose.prod.yml")
    )
    defaults = set(re.findall(r"\$\{TLS_MODE:-(\w+)\}", compose_files))

    assert defaults == {"internal", "public"}
    assert snippets == {"internal", "public", "gts"}


def test_production_requires_every_password_and_secret() -> None:
    production = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    sensitive = re.findall(r"\$\{(\w*(?:PASSWORD|SECRET)\w*)(:[?-])?\}", production)

    assert sensitive
    assert [name for name, check in sensitive if check != ":?"] == []
