"""ruff を起動する補助。`python -m ruff` を先に試し、無ければ PATH の実行ファイルを使う。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class RuffNotFoundError(Exception):
    """`python -m ruff` も PATH 上の `ruff` も使えない。"""


def run_ruff(
    cwd: Path, *, python: str = sys.executable, search_path: str | None = None
) -> subprocess.CompletedProcess[str]:
    probe = subprocess.run(
        [python, "-m", "ruff", "--version"], capture_output=True, text=True, check=False
    )
    if probe.returncode == 0:
        command = [python, "-m", "ruff", "check", "."]
    else:
        executable = shutil.which("ruff", path=search_path)
        if executable is None:
            raise RuffNotFoundError(
                "ruff が見つからない。試したもの: "
                f"`{python} -m ruff`（--version の stderr: {probe.stderr.strip() or '(空)'}）、"
                "PATH の ruff（実行ファイル）"
            )
        command = [executable, "check", "."]
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
