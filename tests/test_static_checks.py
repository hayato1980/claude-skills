"""Python の静的検査。リポ全体で ruff が通ること（未使用 import・未使用変数・効かない noqa）。"""

from __future__ import annotations

import subprocess
import sys

from conftest import REPO_ROOT


def test_ruff_passes_on_the_whole_repository() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
