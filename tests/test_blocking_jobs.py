"""blocking_jobs.sh: 各リポの docs/agents/pr-merge-gate.md から CI で止めるジョブ名を読む。

契約: 見出し「## CI で止めるジョブ」の下の箇条書き `- `名前``。次の `## ` で終わる。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "blocking_jobs.sh"


def run(doc: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), str(doc)], capture_output=True, text=True, check=False)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pr-merge-gate.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_single_job(tmp_path: Path) -> None:
    proc = run(write(tmp_path, "# x\n\n## CI で止めるジョブ\n\n- `gate`\n\n## 次\n"))
    assert (proc.returncode, proc.stdout) == (0, "gate\n")


def test_multiple_jobs_in_order(tmp_path: Path) -> None:
    proc = run(write(tmp_path, "## CI で止めるジョブ\n- `lint`\n- `test` — 説明\n"))
    assert proc.stdout.split() == ["lint", "test"]


def test_bullets_outside_the_section_are_ignored(tmp_path: Path) -> None:
    body = "## 使い方\n- `nope`\n\n## CI で止めるジョブ\n- `gate`\n\n## 手動確認\n- `also-nope`\n"
    assert run(write(tmp_path, body)).stdout == "gate\n"


def test_missing_section_fails_loudly(tmp_path: Path) -> None:
    proc = run(write(tmp_path, "## 使い方\n- `x`\n"))
    assert proc.returncode != 0
    assert "CI で止めるジョブ" in proc.stderr


def test_empty_section_fails_loudly(tmp_path: Path) -> None:
    assert run(write(tmp_path, "## CI で止めるジョブ\n\n文章だけ\n")).returncode != 0


def test_missing_file_fails(tmp_path: Path) -> None:
    assert run(tmp_path / "none.md").returncode != 0
