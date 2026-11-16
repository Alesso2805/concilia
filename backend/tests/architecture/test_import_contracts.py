import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.source import BACKEND_ROOT, SOURCE_ROOT

LINT_IMPORTS = shutil.which("lint-imports", path=str(Path(sys.executable).parent))


def _lint_with_extra_module(tmp_path: Path, module: str, code: str) -> str:
    assert LINT_IMPORTS is not None
    package = tmp_path / "src" / "concilia"
    shutil.copytree(SOURCE_ROOT / "concilia", package, ignore=shutil.ignore_patterns("__pycache__"))
    if module:
        (tmp_path / "src" / Path(*module.split("."))).with_suffix(".py").write_text(
            code, encoding="utf-8"
        )
    shutil.copy(BACKEND_ROOT / ".importlinter", tmp_path / ".importlinter")
    result = subprocess.run(
        [LINT_IMPORTS, "--no-cache"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout + result.stderr


def test_unchanged_codebase_keeps_every_contract(tmp_path: Path) -> None:
    assert "0 broken" in _lint_with_extra_module(tmp_path, "", "")


@pytest.mark.parametrize(
    ("contract", "module", "code"),
    [
        (
            "AR-01 Modules import only earlier modules",
            "concilia.audit.application.probe",
            "import concilia.identity.application",
        ),
        (
            "AR-01 No module imports a composition root",
            "concilia.demo.infrastructure.probe",
            "import concilia.api",
        ),
        (
            "AR-02 Layers inside each business module",
            "concilia.matching.domain.probe",
            "import concilia.matching.application",
        ),
        (
            "AR-02 Layers inside each business module",
            "concilia.matching.api.probe",
            "import concilia.matching.infrastructure",
        ),
    ],
)
def test_contract_detects_violation(tmp_path: Path, contract: str, module: str, code: str) -> None:
    output = _lint_with_extra_module(tmp_path, module, code)

    assert f"{contract} BROKEN" in output
