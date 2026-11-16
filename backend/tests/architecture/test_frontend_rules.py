import json
import re
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from tests.architecture.source import BACKEND_ROOT

WEB_ROOT = BACKEND_ROOT.parent / "web"
ZONE_IN_SOURCE = re.compile(
    r"""from\s+['"]zone\.js|import\s+['"]zone\.js|provideZoneChangeDetection"""
)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def zoneless_frontend(
    package_json: Mapping[str, Any], angular_json: Mapping[str, Any], sources: Mapping[str, str]
) -> list[str]:
    violations = [
        f"package.json {section} depends on zone.js"
        for section in ("dependencies", "devDependencies")
        if "zone.js" in package_json.get(section, {})
    ]
    if any("zone.js" in text for text in _strings(angular_json)):
        violations.append("angular.json references zone.js")
    violations += [
        f"{path} uses zone.js" for path, text in sources.items() if ZONE_IN_SOURCE.search(text)
    ]
    return violations


def _web_project() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    package_json = json.loads((WEB_ROOT / "package.json").read_text(encoding="utf-8"))
    angular_json = json.loads((WEB_ROOT / "angular.json").read_text(encoding="utf-8"))
    sources = {
        str(path.relative_to(WEB_ROOT)): path.read_text(encoding="utf-8")
        for path in (WEB_ROOT / "src").rglob("*.ts")
    }
    return package_json, angular_json, sources


def test_frontend_is_zoneless() -> None:
    assert zoneless_frontend(*_web_project()) == []


@pytest.mark.parametrize(
    ("package_json", "angular_json", "sources"),
    [
        ({"dependencies": {"zone.js": "~0.16.0"}}, {}, {}),
        ({}, {"projects": {"web": {"options": {"polyfills": ["zone.js"]}}}}, {}),
        ({}, {}, {"src/main.ts": "import 'zone.js';"}),
        (
            {},
            {},
            {"src/app/app.config.ts": "provideZoneChangeDetection({ eventCoalescing: true })"},
        ),
    ],
)
def test_zone_js_is_detected(
    package_json: dict[str, Any], angular_json: dict[str, Any], sources: dict[str, str]
) -> None:
    assert zoneless_frontend(package_json, angular_json, sources) != []
