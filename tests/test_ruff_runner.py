"""ruff の起動方法の選択。`python -m ruff` が無くても PATH の実行ファイルで通し、どちらも無ければ明示的に失敗させる。"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ruff_runner import RuffNotFoundError, run_ruff


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def python_without_ruff(tmp_path: Path) -> Path:
    # `-m ruff` が No module named ruff で落ちる python の代役
    return _script(tmp_path / "python-without-ruff", 'echo "No module named ruff" >&2; exit 1')


def test_fails_loudly_when_ruff_is_available_in_neither_form(
    tmp_path: Path, python_without_ruff: Path
) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    with pytest.raises(RuffNotFoundError, match="ruff が見つからない") as excinfo:
        run_ruff(cwd=tmp_path, python=str(python_without_ruff), search_path=str(empty_bin))

    # 切り分けのため、試したものと probe の stderr を文言に載せる
    message = str(excinfo.value)
    assert f"{python_without_ruff} -m ruff" in message
    assert "PATH の ruff" in message
    assert "No module named ruff" in message


def test_uses_the_ruff_executable_on_path_when_the_module_is_missing(
    tmp_path: Path, python_without_ruff: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir / "ruff", 'echo "executable ran: $*"; exit 0')

    result = run_ruff(cwd=tmp_path, python=str(python_without_ruff), search_path=str(bin_dir))

    assert result.returncode == 0
    assert "executable ran: check ." in result.stdout


def test_reports_violations_through_the_module_form(tmp_path: Path) -> None:
    python_with_ruff = _script(
        tmp_path / "python-with-ruff",
        'case "$*" in *--version*) echo "ruff 0.0"; exit 0;; esac\n'
        'echo "F401 unused import"; exit 1',
    )
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    result = run_ruff(cwd=tmp_path, python=str(python_with_ruff), search_path=str(empty_bin))

    assert result.returncode == 1
    assert "F401 unused import" in result.stdout


def test_reports_violations_through_the_executable_form(
    tmp_path: Path, python_without_ruff: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir / "ruff", 'echo "F401 unused import"; exit 1')

    result = run_ruff(cwd=tmp_path, python=str(python_without_ruff), search_path=str(bin_dir))

    assert result.returncode == 1
    assert "F401 unused import" in result.stdout
