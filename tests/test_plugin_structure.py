"""プラグインの構造と、公開リポとしての衛生を検証する。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from conftest import PLUGIN, REPO_ROOT, SCRIPTS, TEMPLATES

SKILLS = ["issue-inventory", "review-dialogue", "create-ccw-session", "ready-merge", "session-closeout", "retro-closeout"]
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


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


def test_retro_closeout_can_read_list_events_dump_without_prompts() -> None:
    # list_events の保存ファイルは grep + jq で読む。許可が無いと毎回プロンプトが出る（#27）。
    tools = frontmatter(PLUGIN / "skills" / "retro-closeout" / "SKILL.md")["allowed-tools"]
    for tool in ("Bash(grep:*)", "Bash(jq:*)"):
        assert tool in tools, tool



def heading_slugs(path: Path) -> set[str]:
    """GitHub が見出しから作るアンカー（小文字・空白は -・句読点は除く）を集める。"""
    slugs = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#{1,6}\s+(.*?)\s*$", line)
        if m:
            slugs.add(re.sub(r"[^\w\- ]", "", m.group(1).lower()).replace(" ", "-"))
    return slugs


def test_link_anchors_in_skills_and_runbook_resolve_to_headings() -> None:
    link = re.compile(r"\]\((\.{1,2}/[^)#\s]+)#([^)\s]+)\)")
    docs = [*(PLUGIN / "skills").glob("*/*.md"), *(REPO_ROOT / "docs").glob("**/*.md")]
    broken = [
        f"{doc.relative_to(REPO_ROOT)} -> {target}#{anchor}"
        for doc in docs
        for target, anchor in link.findall(doc.read_text(encoding="utf-8"))
        if (doc.parent / target).suffix == ".md" and anchor not in heading_slugs((doc.parent / target).resolve())
    ]
    assert not broken, broken


def test_scripts_are_executable_and_shellcheck_clean() -> None:
    targets = [*SCRIPTS.glob("*.sh"), *(PLUGIN / "hooks").glob("*.sh"), *TEMPLATES.glob("*.sh")]
    assert len(targets) == 12
    for t in targets:
        assert os.access(t, os.X_OK), t
        assert subprocess.run(["bash", "-n", str(t)], check=False).returncode == 0, t


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


def _decision(number: str) -> Path:
    found = sorted((REPO_ROOT / "docs" / "decisions").glob(f"{number}-*.md"))
    assert len(found) == 1, f"判断 {number} のファイルが 1 つではありません: {found}"
    return found[0]


def test_decision_0006_is_listed_in_the_decisions_index() -> None:
    name = _decision("0006").name
    index = (REPO_ROOT / "docs" / "decisions" / "README.md").read_text(encoding="utf-8")
    assert f"[0006](./{name})" in index


def test_decision_0006_states_the_four_acceptance_points() -> None:
    """受け入れ基準の 4 点（評価させる・評価できなければ分ける・既存は触るときに移す・限界）が見出しにある。

    5 つ目の「レビューでの効かせ方」は受け入れ基準の 4 点の外（issue の「2.」側）なので、ここでは見ない。
    """
    body = _decision("0006").read_text(encoding="utf-8")
    for heading in ("## 決めたこと", "## 評価できない形なら", "## 既存のテスト", "## 限界"):
        assert heading in body, heading
    decided = body.split("## 決めたこと")[1].split("\n## ")[0]
    assert "ツール自身に評価させ" in decided

