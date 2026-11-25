"""check_heading_references.py: 一覧・README の契約表・スキル本文の見出し参照が食い違っていないか。

テストは一時ディレクトリに作った文書でスクリプトを実行し、終了コードと出力だけを見る（判断 0007）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_heading_references.py"

SPEC_FILES = [
    {"path": "docs/agents/a.md", "headings": ["甲"], "optional_headings": ["乙"]},
    {"path": "docs/agents/b.md", "headings": ["丙"]},
]
README = "| ファイル | 見出し |\n|---|---|\n| `docs/agents/a.md` | `## 甲`／`## 乙` |\n| `docs/agents/b.md` | `## 丙` |\n"
BODY = "スキルは `## 甲` と `## 乙` と `## 丙` を読む。\n"


def make_world(tmp_path: Path, *, files: object = SPEC_FILES, readme: str = README, body: str = BODY) -> Path:
    (tmp_path / "plugin" / "skills").mkdir(parents=True)
    (tmp_path / "plugin" / "agent-headings.json").write_text(json.dumps({"files": files}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "plugin" / "skills" / "s.md").write_text(body, encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    return tmp_path


def run(root: Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--spec", str(root / "plugin" / "agent-headings.json"),
        "--readme", str(root / "README.md"),
        "--plugin-root", str(root / "plugin"),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_passes_when_list_readme_and_skills_agree(tmp_path: Path) -> None:
    proc = run(make_world(tmp_path))
    assert proc.returncode == 0, proc.stderr


def test_fails_when_a_listed_heading_is_read_by_no_skill(tmp_path: Path) -> None:
    proc = run(make_world(tmp_path, body="`## 甲` と `## 乙` だけ読む。\n"))
    assert proc.returncode == 1
    assert "丙" in proc.stderr


def test_fails_when_a_skill_reads_a_heading_that_is_not_listed(tmp_path: Path) -> None:
    proc = run(make_world(tmp_path, body=BODY + "`## 丁` も読む。\n"))
    assert proc.returncode == 1
    assert "丁" in proc.stderr


def test_references_in_scripts_count_too(tmp_path: Path) -> None:
    world = make_world(tmp_path, body="`## 甲` `## 乙`\n")
    (world / "plugin" / "skills" / "r.sh").write_text('# "## 丙" ではなく `## 丙` を読む\n', encoding="utf-8")
    assert run(world).returncode == 0


def test_upstream_output_headings_are_not_a_contract(tmp_path: Path) -> None:
    proc = run(make_world(tmp_path, body=BODY + "上流は `## Standards` と `## Spec` を返す。\n"))
    assert proc.returncode == 0, proc.stderr


def test_fails_when_readme_moves_a_heading_to_another_file(tmp_path: Path) -> None:
    """集合同士の比較では、見出しを別ファイルのエントリへ移しても緑のまま、利用側に誤ったファイルを要求する。"""
    readme = "| `docs/agents/a.md` | `## 甲` |\n| `docs/agents/b.md` | `## 乙`／`## 丙` |\n"
    proc = run(make_world(tmp_path, readme=readme))
    assert proc.returncode == 1
    assert "docs/agents/a.md" in proc.stderr and "乙" in proc.stderr


def test_fails_when_readme_lacks_a_listed_pair(tmp_path: Path) -> None:
    proc = run(make_world(tmp_path, readme="| `docs/agents/a.md` | `## 甲`／`## 乙` |\n"))
    assert proc.returncode == 1
    assert "docs/agents/b.md" in proc.stderr


def test_broken_spec_is_a_usage_error_not_a_silent_pass(tmp_path: Path) -> None:
    proc = run(make_world(tmp_path, files=[]))
    assert proc.returncode == 3
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("flag", ["--spec", "--readme", "--plugin-root"])
def test_missing_input_is_a_usage_error(tmp_path: Path, flag: str) -> None:
    root = make_world(tmp_path)
    args = {
        "--spec": root / "nope.json",
        "--readme": root / "NOPE.md",
        "--plugin-root": root / "nope",
    }
    paths = {
        "--spec": root / "plugin" / "agent-headings.json",
        "--readme": root / "README.md",
        "--plugin-root": root / "plugin",
    }
    paths[flag] = args[flag]
    cmd = [sys.executable, str(SCRIPT)] + [x for k, v in paths.items() for x in (k, str(v))]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 3
    assert "Traceback" not in proc.stderr
