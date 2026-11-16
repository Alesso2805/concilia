import ast
import re
import sys
from collections.abc import Callable, Iterable

from tests.architecture.source import (
    BUSINESS_MODULES,
    COMPOSITION_ROOTS,
    SourceFile,
    imported_aliases,
    imports_of,
)

type Rule = Callable[[Iterable[SourceFile]], list[str]]

PURE_THIRD_PARTY = frozenset({"rapidfuzz"})
CLOCK_IMPLEMENTATION = "concilia.shared.infrastructure.clock"
WALL_CLOCK = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "time.time",
    }
)
SQL_CLOCK = re.compile(
    r"\b(now\s*\(\s*\)|current_date|current_timestamp|localtimestamp|clock_timestamp"
    r"|statement_timestamp|transaction_timestamp)",
    re.IGNORECASE,
)
MONEY_NAME = re.compile(
    r"cents|amount|balance|applied|difference|tolerance|detraction|score", re.IGNORECASE
)
LOGGING_SETUP = "concilia.shared.infrastructure.logging"
LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical"})
LOGGER_FACTORIES = frozenset({"get_logger", "getLogger", "bind", "new"})
BACKGROUND_TASK_NAMES = frozenset({"BackgroundTasks", "BackgroundTask"})
TASK_SPAWNERS = frozenset({"create_task", "ensure_future", "TaskGroup"})


def pure_core_imports(files: Iterable[SourceFile]) -> list[str]:
    violations = []
    for source in files:
        if not source.is_pure_core:
            continue
        own_domain = f"concilia.{source.business_module}.domain"
        for imported in imports_of(source):
            top = imported.module.split(".")[0]
            allowed = (
                top in sys.stdlib_module_names
                or top in PURE_THIRD_PARTY
                or imported.module.startswith("concilia.shared.kernel")
                or (source.layer == "domain" and imported.module.startswith(own_domain))
            )
            if not allowed:
                violations.append(f"{source.module}:{imported.line} imports {imported.module}")
    return violations


def cross_module_access(files: Iterable[SourceFile]) -> list[str]:
    violations = []
    for source in files:
        if source.module in COMPOSITION_ROOTS:
            continue
        for imported in imports_of(source):
            parts = imported.module.split(".")
            if parts[0] != "concilia" or len(parts) < 2:
                continue
            other_module = parts[1] in BUSINESS_MODULES and parts[1] != source.business_module
            if other_module and (len(parts) < 3 or parts[2] != "application"):
                violations.append(
                    f"{source.module}:{imported.line} reaches past the application layer "
                    f"of {parts[1]}: {imported.module}"
                )
            shared_infrastructure = imported.module.startswith("concilia.shared.infrastructure")
            if shared_infrastructure and source.layer in {"domain", "application"}:
                violations.append(
                    f"{source.module}:{imported.line} imports {imported.module} "
                    f"from the {source.layer} layer"
                )
    return violations


def _dotted_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def no_wall_clock(files: Iterable[SourceFile]) -> list[str]:
    violations = []
    for source in files:
        if source.module == CLOCK_IMPLEMENTATION:
            continue
        aliases = imported_aliases(source)
        violations += [
            f"{source.module}:{imported.line} imports {imported.module}"
            for imported in imports_of(source)
            if imported.module in WALL_CLOCK
        ]
        for node in ast.walk(source.tree):
            if isinstance(node, ast.Attribute) and _dotted_name(node, aliases) in WALL_CLOCK:
                violations.append(f"{source.module}:{node.lineno} reads the wall clock")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and SQL_CLOCK.search(node.value)
            ):
                violations.append(f"{source.module}:{node.lineno} reads the clock in SQL")
    return violations


def _mentions_float(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    return any(isinstance(node, ast.Name) and node.id == "float" for node in ast.walk(annotation))


def _annotated_names(node: ast.AST) -> list[tuple[str, ast.expr | None]]:
    if isinstance(node, ast.AnnAssign):
        target = node.target
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        return [(name, node.annotation)]
    if isinstance(node, ast.arg):
        return [(node.arg, node.annotation)]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return [(node.name, node.returns)]
    return []


def no_float_money(files: Iterable[SourceFile]) -> list[str]:
    violations = []
    for source in files:
        for node in ast.walk(source.tree):
            line = getattr(node, "lineno", 0)
            if source.is_pure_core:
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    violations.append(f"{source.module}:{line} uses a float literal")
                if isinstance(node, ast.Name) and node.id == "float":
                    violations.append(f"{source.module}:{line} uses float")
                if isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Div):
                    violations.append(f"{source.module}:{line} uses true division")
            for name, annotation in _annotated_names(node):
                if MONEY_NAME.search(name) and _mentions_float(annotation):
                    violations.append(f"{source.module}:{line} types {name} as float")
    return violations


def _is_logger(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return "log" in node.id.lower()
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute | ast.Name):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        return name in LOGGER_FACTORIES
    return False


def log_events_are_literals(files: Iterable[SourceFile]) -> list[str]:
    violations = []
    for source in files:
        if source.module != LOGGING_SETUP:
            violations += [
                f"{source.module}:{imported.line} imports {imported.module}"
                for imported in imports_of(source)
                if imported.module.split(".")[0] == "logging"
            ]
        for node in ast.walk(source.tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in LOG_METHODS
                and _is_logger(node.func.value)
            ):
                continue
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                violations.append(f"{source.module}:{node.lineno} logs a non-literal event")
            elif len(node.args) > 1:
                violations.append(f"{source.module}:{node.lineno} formats the event with args")
    return violations


def no_background_tasks(files: Iterable[SourceFile]) -> list[str]:
    violations = []
    for source in files:
        violations += [
            f"{source.module}:{imported.line} imports {imported.module}"
            for imported in imports_of(source)
            if imported.module.split(".")[-1] in BACKGROUND_TASK_NAMES
            or imported.module.startswith("starlette.background")
        ]
        if source.module != "concilia.api" and source.layer != "api":
            continue
        for node in ast.walk(source.tree):
            name = getattr(node, "attr", None) or getattr(node, "id", None)
            if isinstance(node, ast.Attribute | ast.Name) and name in TASK_SPAWNERS:
                violations.append(f"{source.module}:{node.lineno} spawns a task with {name}")
    return violations
