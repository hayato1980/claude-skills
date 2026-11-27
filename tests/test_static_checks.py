"""Python の静的検査。リポ全体で ruff が通ること（未使用 import・未使用変数・効かない noqa）。"""

from __future__ import annotations

from conftest import REPO_ROOT
from ruff_runner import run_ruff


def test_ruff_passes_on_the_whole_repository() -> None:
    result = run_ruff(cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
