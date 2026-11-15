import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src"
MIGRATIONS_ROOT = BACKEND_ROOT / "migrations"

BUSINESS_MODULES = frozenset(
    {"audit", "identity", "banking", "periods", "imports", "matching", "ai", "reporting", "demo"}
)
LAYERS = frozenset({"domain", "application", "infrastructure", "api"})
COMPOSITION_ROOTS = frozenset({"concilia.api", "concilia.worker"})


@dataclass(frozen=True)
class SourceFile:
    module: str
    tree: ast.Module

    @classmethod
    def parse(cls, module: str, code: str) -> SourceFile:
        return cls(module, ast.parse(code))

    @property
    def business_module(self) -> str | None:
        parts = self.module.split(".")
        if parts[0] == "concilia" and len(parts) > 1 and parts[1] in BUSINESS_MODULES:
            return parts[1]
        return None

    @property
    def layer(self) -> str | None:
        parts = self.module.split(".")
        if self.business_module and len(parts) > 2 and parts[2] in LAYERS:
            return parts[2]
        return None

    @property
    def is_pure_core(self) -> bool:
        return self.module.startswith("concilia.shared.kernel") or self.layer == "domain"


@dataclass(frozen=True)
class Import:
    module: str
    line: int


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join(parts)


def codebase() -> list[SourceFile]:
    paths = [(path, SOURCE_ROOT) for path in (SOURCE_ROOT / "concilia").rglob("*.py")]
    if MIGRATIONS_ROOT.exists():
        paths += [(path, BACKEND_ROOT) for path in MIGRATIONS_ROOT.rglob("*.py")]
    return [
        SourceFile(_module_name(path, root), ast.parse(path.read_text(encoding="utf-8")))
        for path, root in sorted(paths)
    ]


def imports_of(source: SourceFile) -> Iterator[Import]:
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield Import(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                name = node.module if alias.name == "*" else f"{node.module}.{alias.name}"
                yield Import(name, node.lineno)


def imported_aliases(source: SourceFile) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(source.tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
    return aliases
