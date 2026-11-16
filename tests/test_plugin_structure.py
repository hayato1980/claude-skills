"""プラグインの構造と、公開リポとしての衛生を検証する。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from conftest import PLUGIN, REPO_ROOT, SCRIPTS, TEMPLATES

SKILLS = ["issue-inventory", "review-dialogue", "create-ccw-session", "ready-merge", "session-closeout"]
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)

# 非公開リポの名前・ホスト名・業務ドメインの語。正規表現の文字クラスで組み、このファイル自身に
# 語がそのまま現れないようにする（git grep が自分自身にヒットしない）。
FORBIDDEN = r"[k]eiba|[j]rvltsql|[t]erraform|[a]urora"


def frontmatter(path: Path) -> dict[str, str]:
    m = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert m, f"frontmatter がありません: {path}"
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"')
    return fields


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_matching_name_and_description(name: str) -> None:
    fm = frontmatter(PLUGIN / "skills" / name / "SKILL.md")
    assert fm["name"] == name
    assert fm.get("description")


def test_ready_merge_is_owner_invoked_only() -> None:
    fm = frontmatter(PLUGIN / "skills" / "ready-merge" / "SKILL.md")
    assert fm["disable-model-invocation"] == "true"
    assert fm["allowed-tools"] == "Bash(scripts/ci/ready_wait_merge.sh*)"


def test_create_ccw_session_carries_its_own_write_permissions() -> None:
    tools = frontmatter(PLUGIN / "skills" / "create-ccw-session" / "SKILL.md")["allowed-tools"]
    assert "mcp__claude-code-remote__create_session" in tools


def test_issue_inventory_carries_its_own_write_permissions() -> None:
    # 利用側は同名の command を持たず、この allowed-tools に頼る。書き込み系が落ちても CI は
    # 緑のまま、承認後の書き込みのたびに許可プロンプトが出るだけになるので、ここで固定する。
    tools = frontmatter(PLUGIN / "skills" / "issue-inventory" / "SKILL.md")["allowed-tools"]
    for tool in (
        "mcp__github__issue_write",
        "mcp__github__add_issue_comment",
        "Bash(gh issue edit:*)",
        "Bash(gh issue comment:*)",
        "Bash(gh issue close:*)",
        "Bash(gh label create:*)",
    ):
        assert tool in tools, tool


def test_scripts_are_executable_and_shellcheck_clean() -> None:
    targets = [*SCRIPTS.glob("*.sh"), *(PLUGIN / "hooks").glob("*.sh"), *TEMPLATES.glob("*.sh")]
    assert len(targets) == 9
    for t in targets:
        assert os.access(t, os.X_OK), t
        assert subprocess.run(["bash", "-n", str(t)], check=False).returncode == 0, t


def test_no_private_names_anywhere_in_tracked_files() -> None:
    proc = subprocess.run(
        ["git", "grep", "-nIiE", FORBIDDEN, "--", "."], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 1, f"公開リポに載せてはいけない語が含まれています:\n{proc.stdout}"


def test_relative_links_in_skills_and_runbook_resolve() -> None:
    link = re.compile(r"\]\((\.{1,2}/[^)#\s]+)")
    docs = [*(PLUGIN / "skills").glob("*/*.md"), REPO_ROOT / "README.md", *(REPO_ROOT / "docs").glob("**/*.md")]
    broken = [
        f"{doc.relative_to(REPO_ROOT)} -> {target}"
        for doc in docs
        for target in link.findall(doc.read_text(encoding="utf-8"))
        if not (doc.parent / target).exists()
    ]
    assert not broken, broken


def test_decision_links_point_at_existing_files() -> None:
    url = re.compile(r"docs/decisions/(\d{4}-[a-z0-9-]+\.md)")
    existing = {p.name for p in (REPO_ROOT / "docs" / "decisions").glob("*.md")}
    missing = {
        f"{doc.relative_to(REPO_ROOT)} -> {name}"
        for doc in [*(PLUGIN / "skills").glob("*/*.md"), PLUGIN / "scripts" / "ready_wait_merge.sh"]
        for name in url.findall(doc.read_text(encoding="utf-8"))
        if name not in existing
    }
    assert not missing, missing


def test_marketplace_and_plugin_manifests_are_valid_json() -> None:
    market = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["plugins"][0]["name"] == "dev-workflow"
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert "version" not in plugin  # 版を書くと上げ忘れた変更が配られない（README 参照）


def test_agent_contract_headings_are_documented() -> None:
    # スキルが実行時に読む見出しは README の契約表に載っていること（載せ忘れると利用側が書けない）。
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for heading in [
        "## オーナーマージの基準表", "## CI が走る条件", "## push 前に流すコマンド", "## CI で止めるジョブ",
        "## 払い出しを止めるラベル", "## タグの決め方", "## モデル表に足す行", "## source_url", "## /implement", "## 更新するプラグイン",
    ]:
        assert heading in readme, heading


def _decision(number: str) -> Path:
    found = sorted((REPO_ROOT / "docs" / "decisions").glob(f"{number}-*.md"))
    assert len(found) == 1, f"判断 {number} のファイルが 1 つではありません: {found}"
    return found[0]


def test_decision_0006_is_listed_in_the_decisions_index() -> None:
    name = _decision("0006").name
    index = (REPO_ROOT / "docs" / "decisions" / "README.md").read_text(encoding="utf-8")
    assert f"[0006](./{name})" in index


def test_decision_0006_states_the_four_points() -> None:
    body = _decision("0006").read_text(encoding="utf-8")
    for heading in ("## 決めたこと", "## 評価できない形なら", "## 既存のテスト", "## 限界"):
        assert heading in body, heading
    assert "評価" in body.split("## 評価できない形なら")[0]
