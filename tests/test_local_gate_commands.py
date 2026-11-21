"""local_gate_commands.sh: 各リポの docs/agents/pr-merge-gate.md から「ready 前に実行するコマンド」を読む。

契約: 見出し `## ready 前に実行するコマンド` の下の箇条書き ``- `コマンド` ``。次の `## ` で終わる。
見出しが無ければ何も出さず 0（後方互換）。見出しはあるのに箇条書きが空なら非ゼロ（書き損じを素通りさせない）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "local_gate_commands.sh"


def run(doc: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), str(doc)], capture_output=True, text=True, check=False)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pr-merge-gate.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_single_command(tmp_path: Path) -> None:
    proc = run(write(tmp_path, "## ready 前に実行するコマンド\n\n- `make lint`\n\n## 次\n"))
    assert (proc.returncode, proc.stdout) == (0, "make lint\n")


def test_multiple_commands_keep_written_order_and_inner_text(tmp_path: Path) -> None:
    body = "## ready 前に実行するコマンド\n- `pytest -q tests/`\n- `ruff check . && ruff format --check .` — 説明\n"
    assert run(write(tmp_path, body)).stdout.splitlines() == ["pytest -q tests/", "ruff check . && ruff format --check ."]


def test_bullets_outside_the_section_are_ignored(tmp_path: Path) -> None:
    body = "## CI で止めるジョブ\n- `test`\n\n## ready 前に実行するコマンド\n- `make lint`\n\n## 手動確認\n- `nope`\n"
    assert run(write(tmp_path, body)).stdout == "make lint\n"


def test_missing_heading_does_nothing_and_succeeds(tmp_path: Path) -> None:
    proc = run(write(tmp_path, "## CI で止めるジョブ\n- `test`\n"))
    assert (proc.returncode, proc.stdout) == (0, "")


def test_heading_without_bullets_fails_loudly(tmp_path: Path) -> None:
    proc = run(write(tmp_path, "## ready 前に実行するコマンド\n\n文章だけ\n"))
    assert proc.returncode != 0
    assert "ready 前に実行するコマンド" in proc.stderr


def test_missing_file_fails(tmp_path: Path) -> None:
    assert run(tmp_path / "none.md").returncode != 0
