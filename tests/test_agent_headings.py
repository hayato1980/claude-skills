"""check_agent_headings.py: 利用側リポの docs/agents/*.md に、共有スキルが読む見出しがあるか。

見出しは共有スキルとの契約で、変えるとスキルは何も言わずにその節を読まなくなる。
必須の見出しの一覧は plugins/dev-workflow/agent-headings.json の 1 か所だけが持つ。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PLUGIN, REPO_ROOT, SCRIPTS

SCRIPT = REPO_ROOT / ".github" / "actions" / "check-agent-headings" / "check_agent_headings.py"
SPEC = PLUGIN / "agent-headings.json"


def run(spec: Path, root: Path, *ignore: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), "--spec", str(spec), "--root", str(root)]
    for path in ignore:
        cmd += ["--ignore", path]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def make_spec(tmp_path: Path, files: list[dict[str, object]]) -> Path:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"files": files}, ensure_ascii=False), encoding="utf-8")
    return spec


def make_doc(root: Path, name: str, body: str) -> None:
    path = root / "docs" / "agents" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


ONE = [{"path": "docs/agents/a.md", "headings": ["見出し甲", "見出し乙"]}]


def test_passes_when_every_heading_is_present(tmp_path: Path) -> None:
    make_doc(tmp_path, "a.md", "# t\n\n## 見出し甲\n\n## 見出し乙\n")
    assert run(make_spec(tmp_path, ONE), tmp_path).returncode == 0


def test_fails_and_names_the_missing_heading_and_file(tmp_path: Path) -> None:
    make_doc(tmp_path, "a.md", "# t\n\n## 見出し甲\n")
    proc = run(make_spec(tmp_path, ONE), tmp_path)
    assert proc.returncode == 1
    assert "docs/agents/a.md" in proc.stderr
    assert "## 見出し乙" in proc.stderr
    assert "## 見出し甲" not in proc.stderr


def test_heading_must_match_exactly_at_level_two(tmp_path: Path) -> None:
    """言い換え・段落違い・部分一致では契約を満たさない（スキルは行の完全一致で読む）。"""
    make_doc(tmp_path, "a.md", "## 見出し甲です\n### 見出し乙\n見出し乙\n")
    proc = run(make_spec(tmp_path, ONE), tmp_path)
    assert proc.returncode == 1
    assert "## 見出し甲" in proc.stderr and "## 見出し乙" in proc.stderr


def test_trailing_whitespace_and_cr_are_not_a_match(tmp_path: Path) -> None:
    """スキル側（blocking_jobs.sh 等）は行の完全一致で読む。検査だけが緩いと、緑なのにスキルが読めない。"""
    make_doc(tmp_path, "a.md", "## 見出し甲  \n## 見出し乙\r\n")
    proc = run(make_spec(tmp_path, ONE), tmp_path)
    assert proc.returncode == 1
    assert "## 見出し甲" in proc.stderr and "## 見出し乙" in proc.stderr


def test_the_rule_agrees_with_the_skill_side_reader(tmp_path: Path) -> None:
    """スキル側の実読者（blocking_jobs.sh）が読めない文書を、この検査も通さない。"""
    reader = SCRIPTS / "blocking_jobs.sh"
    spec = make_spec(tmp_path, [{"path": "docs/agents/a.md", "headings": ["CI で止めるジョブ"]}])
    for body in ("## CI で止めるジョブ\n- `g`\n", "## CI で止めるジョブ \n- `g`\n", "## CI で止めるジョブ\r\n- `g`\r\n"):
        make_doc(tmp_path, "a.md", body)
        skill_reads = subprocess.run(
            ["bash", str(reader), str(tmp_path / "docs" / "agents" / "a.md")], capture_output=True, check=False
        ).returncode == 0
        assert (run(spec, tmp_path).returncode == 0) == skill_reads, repr(body)


def test_missing_required_file_fails(tmp_path: Path) -> None:
    proc = run(make_spec(tmp_path, ONE), tmp_path)
    assert proc.returncode == 1
    assert "docs/agents/a.md" in proc.stderr


def test_missing_optional_file_passes_but_present_one_is_checked(tmp_path: Path) -> None:
    spec = make_spec(tmp_path, [{**ONE[0], "optional": True}])
    assert run(spec, tmp_path).returncode == 0
    make_doc(tmp_path, "a.md", "## 見出し甲\n")
    assert run(spec, tmp_path).returncode == 1


def test_optional_heading_may_be_absent_from_an_existing_file_but_required_ones_may_not(tmp_path: Path) -> None:
    """後から足した見出しを、足していない利用側リポの CI で落とさない（ファイルが無くてよい optional とは別）。"""
    spec = make_spec(tmp_path, [{**ONE[0], "optional_headings": ["任意の見出し"]}])
    make_doc(tmp_path, "a.md", "## 見出し甲\n## 見出し乙\n")
    assert run(spec, tmp_path).returncode == 0
    make_doc(tmp_path, "a.md", "## 見出し甲\n")
    proc = run(spec, tmp_path)
    assert proc.returncode == 1
    assert "## 見出し乙" in proc.stderr and "任意の見出し" not in proc.stderr


@pytest.mark.parametrize("bad", ["任意", [1], [""]], ids=["str", "non-str-item", "empty-item"])
def test_malformed_optional_headings_is_a_usage_error(tmp_path: Path, bad: object) -> None:
    make_doc(tmp_path, "a.md", "## 見出し甲\n## 見出し乙\n")
    proc = run(make_spec(tmp_path, [{**ONE[0], "optional_headings": bad}]), tmp_path)
    assert proc.returncode == 3
    assert "Traceback" not in proc.stderr


def test_ignored_file_is_skipped(tmp_path: Path) -> None:
    assert run(make_spec(tmp_path, ONE), tmp_path, "docs/agents/a.md").returncode == 0


def run_with_list(spec: Path, root: Path, ignore_list: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), "--spec", str(spec), "--root", str(root), "--ignore-list", ignore_list]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)


def test_ignore_list_is_split_on_whitespace_and_never_globbed(tmp_path: Path) -> None:
    """glob はカレントに対して展開される。root を変えている呼び出し側で、外すファイルがずれる。"""
    files = [*ONE, {"path": "docs/agents/b.md", "headings": ["丙"]}]
    spec = make_spec(tmp_path, files)
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    make_doc(cwd, "a.md", "")  # カレントに a.md があっても、glob で拾われてはいけない
    both = run_with_list(spec, root, "docs/agents/a.md  docs/agents/b.md", cwd)
    assert both.returncode == 0, both.stderr
    glob = run_with_list(spec, root, "docs/agents/*.md", cwd)
    assert glob.returncode == 1, "glob は展開せず、文字列としてしか照合しない"


def test_every_missing_heading_is_reported_in_one_run(tmp_path: Path) -> None:
    files = [*ONE, {"path": "docs/agents/b.md", "headings": ["丙"]}]
    make_doc(tmp_path, "a.md", "# t\n")
    make_doc(tmp_path, "b.md", "# t\n")
    proc = run(make_spec(tmp_path, files), tmp_path)
    assert proc.returncode == 1
    assert all(h in proc.stderr for h in ("## 見出し甲", "## 見出し乙", "## 丙"))


def test_broken_spec_is_a_usage_error_not_a_silent_pass(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    assert run(spec, tmp_path).returncode == 3
    assert run(tmp_path / "nope.json", tmp_path).returncode == 3


@pytest.mark.parametrize(
    "entry",
    [
        {"headings": ["x"]},
        {"path": "docs/agents/a.md"},
        {"path": "docs/agents/a.md", "headings": "見出し甲"},
        {"path": "docs/agents/a.md", "headings": []},
        {"path": "docs/agents/a.md", "headings": [1]},
        {"path": 1, "headings": ["x"]},
        {"path": "docs/agents/a.md", "headings": ["x"], "optional": "yes"},
        "docs/agents/a.md",
    ],
    ids=["no-path", "no-headings", "str-headings", "empty-headings", "non-str-heading", "non-str-path", "bad-optional", "not-a-dict"],
)
def test_malformed_entry_is_a_usage_error_without_a_traceback(tmp_path: Path, entry: object) -> None:
    """終了コード 1（不足あり）と区別する。トレースバックも出さない。"""
    make_doc(tmp_path, "a.md", "## x\n")
    proc = run(make_spec(tmp_path, [entry]), tmp_path)  # type: ignore[list-item]
    assert proc.returncode == 3
    assert "Traceback" not in proc.stderr


# --- 一覧とスキル本文の整合 -----------------------------------------------------

BACKTICKED_HEADING = re.compile(r"`## ([^`]+)`")

# 上流の code-review が返す出力の見出し。利用側の docs/agents との契約ではない。
NOT_A_CONTRACT = {"Standards", "Spec"}


def listed_headings() -> set[str]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    return {h for entry in spec["files"] for h in [*entry["headings"], *entry.get("optional_headings", [])]}


def referenced_headings() -> set[str]:
    found: set[str] = set()
    for path in PLUGIN.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".sh", ".py"}:
            found |= set(BACKTICKED_HEADING.findall(path.read_text(encoding="utf-8")))
    return found - NOT_A_CONTRACT


def test_every_listed_heading_is_read_by_a_skill() -> None:
    """一覧にあるのにスキルが読まない見出しは、利用側に不要な縛りを課す。"""
    assert listed_headings() - referenced_headings() == set()


def test_every_heading_a_skill_reads_is_listed() -> None:
    """スキルが読むのに一覧に無い見出しは、変えられても検出されない。"""
    assert referenced_headings() - listed_headings() == set()


README_ROW = re.compile(r"^\|\s*`(docs/agents/[^`]+)`\s*\|(.*)$")


def readme_pairs() -> set[tuple[str, str]]:
    """README の表（ファイル列と、契約する見出し列）から (ファイル, 見出し) の対を取る。"""
    pairs: set[tuple[str, str]] = set()
    for line in (REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        row = README_ROW.match(line)
        if row:
            pairs |= {(row.group(1), h) for h in BACKTICKED_HEADING.findall(row.group(2))}
    return pairs


def test_listed_pairs_match_the_readme_table_by_file_and_heading() -> None:
    """集合同士の比較では、見出しを別ファイルのエントリへ移しても緑のまま、利用側に誤ったファイルを要求する。"""
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    listed = {(e["path"], h) for e in spec["files"] for h in [*e["headings"], *e.get("optional_headings", [])]}
    assert listed == readme_pairs()


@pytest.mark.parametrize("entry", json.loads(SPEC.read_text(encoding="utf-8"))["files"], ids=lambda e: e["path"])
def test_spec_entries_are_well_formed(entry: dict[str, object]) -> None:
    assert str(entry["path"]).startswith("docs/agents/")
    assert entry["headings"] and len(set(entry["headings"])) == len(entry["headings"])  # type: ignore[arg-type]
