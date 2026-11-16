import io

import pytest

from concilia.cli import read_password


def test_reads_the_password_from_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("una clave larga\r\nignored\n"))

    assert read_password(from_stdin=True) == "una clave larga"


def test_asks_twice_and_rejects_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["una clave larga", "otra clave"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    with pytest.raises(SystemExit, match="do not match"):
        read_password(from_stdin=False)
