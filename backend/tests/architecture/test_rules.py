import pytest

from tests.architecture.rules import (
    Rule,
    cross_module_access,
    no_background_tasks,
    no_float_money,
    no_wall_clock,
    pure_core_imports,
)
from tests.architecture.source import SourceFile, codebase

RULES: dict[str, Rule] = {
    "AR-03": pure_core_imports,
    "AR-04": cross_module_access,
    "AR-05": no_wall_clock,
    "AR-06": no_float_money,
    "AR-07": no_background_tasks,
}

VIOLATIONS = [
    ("AR-03", "concilia.matching.domain.engine", "import sqlalchemy"),
    ("AR-03", "concilia.shared.kernel.money", "from pydantic import BaseModel"),
    ("AR-03", "concilia.matching.domain.engine", "from concilia.imports.domain import Movement"),
    ("AR-04", "concilia.matching.application.run", "from concilia.imports.infrastructure import x"),
    ("AR-04", "concilia.matching.infrastructure.repo", "import concilia.imports"),
    ("AR-04", "concilia.matching.application.run", "from concilia.shared.infrastructure import db"),
    ("AR-05", "concilia.periods.application.close", "import datetime\ndatetime.datetime.now()"),
    ("AR-05", "concilia.periods.domain.period", "from datetime import date as d\nd.today()"),
    ("AR-05", "concilia.identity.infrastructure.repo", "from time import time"),
    ("AR-05", "concilia.identity.infrastructure.repo", 'SQL = "UPDATE x SET at = now()"'),
    ("AR-05", "migrations.versions.0001_init", 'op.execute("DEFAULT CURRENT_TIMESTAMP")'),
    ("AR-06", "concilia.matching.domain.engine", "def half(x: int) -> int:\n    return x / 2"),
    ("AR-06", "concilia.matching.domain.engine", "RATE = 0.12"),
    ("AR-06", "concilia.reporting.application.panel", "def f(amount_cents: float) -> None: ..."),
    ("AR-06", "concilia.reporting.application.panel", "class R:\n    open_balance: float"),
    ("AR-07", "concilia.identity.api.routes", "from fastapi import BackgroundTasks"),
    ("AR-07", "concilia.api", "import asyncio\nasyncio.create_task(job())"),
]

ALLOWED = [
    ("AR-04", "concilia.matching.application.run", "from concilia.imports.application import q"),
    (
        "AR-04",
        "concilia.matching.infrastructure.repo",
        "from concilia.shared.infrastructure import db",
    ),
    (
        "AR-05",
        "concilia.shared.infrastructure.clock",
        "from datetime import datetime\ndatetime.now()",
    ),
    ("AR-06", "concilia.shared.infrastructure.http", "TIMEOUT_SECONDS: float = 30.0"),
    ("AR-07", "concilia.worker", "import asyncio\nasyncio.create_task(job())"),
]


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_codebase_follows_rule(rule_id: str) -> None:
    assert RULES[rule_id](codebase()) == []


@pytest.mark.parametrize(("rule_id", "module", "code"), VIOLATIONS)
def test_rule_detects_violation(rule_id: str, module: str, code: str) -> None:
    assert RULES[rule_id]([SourceFile.parse(module, code)]) != []


@pytest.mark.parametrize(("rule_id", "module", "code"), ALLOWED)
def test_rule_allows_legitimate_code(rule_id: str, module: str, code: str) -> None:
    assert RULES[rule_id]([SourceFile.parse(module, code)]) == []
