"""プラグインの hook 2 本と hooks.json の検証。

- pr-review-dispatch.sh: 作成した PR の head が claude/issue-<N> のときだけ、PR 作成直後にレビュー払い出しを促す。
- deny-mattpocock-implement.sh: 対象リポの docs/agents/dev-workflow.md で有効にしたときだけ /implement を止める。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import HOOKS

DISPATCH_HOOK = HOOKS / "pr-review-dispatch.sh"
DENY_HOOK = HOOKS / "deny-mattpocock-implement.sh"


def run_dispatch(head: str | None, *, env_path: str | None = None, stdin_override: str | None = None,
                 tool_response: object | None = None) -> subprocess.CompletedProcess[str]:
    tool_input: dict[str, object] = {"owner": "o", "repo": "r", "title": "t", "base": "main"}
    if head is not None:
        tool_input["head"] = head
    payload: dict[str, object] = {"hook_event_name": "PostToolUse", "tool_name": "mcp__github__create_pull_request",
                                  "tool_input": tool_input}
    if tool_response is not None:
        payload["tool_response"] = tool_response
    env = {**os.environ, **({"PATH": env_path} if env_path is not None else {})}
    return subprocess.run(["bash", str(DISPATCH_HOOK)], input=stdin_override if stdin_override is not None else json.dumps(payload),
                          capture_output=True, text=True, check=False, env=env)


class TestPrReviewDispatch:
    """判定は prompt ではなく、作成した PR の head ブランチ（claude/issue-<N>）で行う。"""

    def test_issue_branch_gets_the_dispatch_reminder(self) -> None:
        proc = run_dispatch("claude/issue-1429")
        assert proc.returncode == 0
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        assert out["hookEventName"] == "PostToolUse"
        ctx = out["additionalContext"]
        assert "PR 作成後の自動レビュー払い出し" in ctx
        assert "create-ccw-session" in ctx
        assert "#1429" in ctx and "claude/issue-1429" in ctx
        assert "/code-review は回さない" in ctx

    def test_reminder_pins_the_fixer_side_wording(self) -> None:
        # #32: 最初の返信の前に runbook の修正側の手順を読む。要点 3 つは本文にも書く。
        ctx = json.loads(run_dispatch("claude/issue-7").stdout)["hookSpecificOutput"]["additionalContext"]
        assert "最初のスレッド返信・push・ポークより前に" in ctx
        assert "修正側の手順" in ctx and "ラウンドの閉じ方" in ctx
        assert "[修正]" in ctx
        assert "resolve しない" in ctx
        assert "相手を引く" in ctx and "ポーク" in ctx and "自己チェックイン" in ctx and "購読" in ctx

    def test_reminder_hands_the_lookup_to_the_counterpart_script(self) -> None:
        # 判断 0008: 相手引きの規則はスクリプトの 1 か所だけ。hook はその呼び方と、結果ごとの動作だけを渡す。
        ctx = json.loads(run_dispatch("claude/issue-7").stdout)["hookSpecificOutput"]["additionalContext"]
        assert "scripts/ci/session_closeout.sh counterpart --want reviewer --issue 7" in ctx
        assert "found なら" in ctx and "払い出さない" in ctx
        assert "none なら" in ctx and "create_session" in ctx
        assert "ambiguous" in ctx and "人へ渡す" in ctx
        assert "tags に issue-7 を含み" not in ctx  # 規則の写しは残さない

    def test_head_is_read_from_tool_response_when_tool_input_has_none(self) -> None:
        resp = {"head": {"ref": "claude/issue-88"}}
        proc = run_dispatch(None, tool_response=resp)
        assert "claude/issue-88" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_head_is_read_from_stringified_tool_response(self) -> None:
        resp = json.dumps({"head": {"ref": "claude/issue-89"}})
        proc = run_dispatch(None, tool_response=resp)
        assert "claude/issue-89" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_head_is_read_from_content_block_array(self) -> None:
        resp = [{"type": "text", "text": json.dumps({"head": {"ref": "claude/issue-90"}})}]
        proc = run_dispatch(None, tool_response=resp)
        assert "claude/issue-90" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_head_is_read_from_mcp_content_object(self) -> None:
        # MCP ツールの結果の典型形: {"content":[{"type":"text","text":"<PR の JSON>"}]}
        resp = {"content": [{"type": "text", "text": json.dumps({"head": {"ref": "claude/issue-91"}})}]}
        proc = run_dispatch(None, tool_response=resp)
        assert "claude/issue-91" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.parametrize(
        "head",
        [
            "claude/happy-fox-1a2b3c",
            "claude/issue-",
            "claude/issue-12-extra",
            "feature/claude/issue-12",
            "main",
            "",
        ],
    )
    def test_other_heads_get_nothing(self, head: str) -> None:
        proc = run_dispatch(head)
        assert (proc.returncode, proc.stdout.strip()) == (0, "")

    def test_no_head_anywhere_gets_nothing(self) -> None:
        proc = run_dispatch(None)
        assert (proc.returncode, proc.stdout.strip()) == (0, "")

    @pytest.mark.parametrize("stdin_override", ["", "not json", "[]"])
    def test_unreadable_input_is_fail_soft(self, stdin_override: str) -> None:
        proc = run_dispatch(None, stdin_override=stdin_override)
        assert (proc.returncode, proc.stdout.strip()) == (0, "")

    def test_no_head_anywhere_says_so_on_stderr(self) -> None:
        proc = run_dispatch(None, tool_response={"id": 1, "url": "u"})
        assert (proc.returncode, proc.stdout.strip()) == (0, "")
        assert "head" in proc.stderr

    def test_owner_prefixed_head_is_matched(self) -> None:
        proc = run_dispatch("hayato1980:claude/issue-90")
        assert "claude/issue-90" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_missing_jq_is_loud_not_silent(self, tmp_path: Path) -> None:
        # jq が無いのに黙って成功すると、この hook が防ぎたい「レビューが払い出されないまま止まる」が起きる。
        bindir = tmp_path / "bin"
        bindir.mkdir()
        for tool in ("bash", "cat", "dirname"):
            found = shutil.which(tool)
            assert found
            (bindir / tool).symlink_to(found)
        proc = run_dispatch("claude/issue-1", env_path=str(bindir))
        assert proc.returncode == 1
        assert "jq" in proc.stderr
        assert proc.stdout.strip() == ""


def write_dev_workflow(project: Path, body: str | None) -> None:
    (project / "docs" / "agents").mkdir(parents=True, exist_ok=True)
    if body is not None:
        (project / "docs" / "agents" / "dev-workflow.md").write_text(body, encoding="utf-8")


def run_deny(project: Path, prompt: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
    return subprocess.run(["bash", str(DENY_HOOK)], input=json.dumps(payload), capture_output=True, text=True, check=False, env=env)


ENABLED = "# dev-workflow\n\n## /implement\n\n止める: はい\n"
DISABLED = "# dev-workflow\n\n## /implement\n\n止める: いいえ\n"


class TestDenyImplement:
    @pytest.mark.parametrize("prompt", ["/mattpocock-skills:implement", "/implement", "  /Implement 引数", "/implement\n続き"])
    def test_blocks_when_enabled(self, tmp_path: Path, prompt: str) -> None:
        write_dev_workflow(tmp_path, ENABLED)
        proc = run_deny(tmp_path, prompt)
        assert proc.returncode == 2
        assert "/tdd" in proc.stderr or "tdd" in proc.stderr

    @pytest.mark.parametrize("body", [DISABLED, None, "## /implement\n\n止める: たぶん\n", "## 別の節\n止める: はい\n"])
    def test_passes_when_not_enabled(self, tmp_path: Path, body: str | None) -> None:
        # 設定が無い・読めない・曖昧なときは止めない（このリポの設定が無いのに他リポ流儀を押し付けない）。
        write_dev_workflow(tmp_path, body)
        assert run_deny(tmp_path, "/implement").returncode == 0

    @pytest.mark.parametrize(
        "prompt",
        ["/mattpocock-skills:implement-spec", "なぜ /implement は禁止？", "/tdd #1", "普通の依頼"],
    )
    def test_never_blocks_other_prompts(self, tmp_path: Path, prompt: str) -> None:
        write_dev_workflow(tmp_path, ENABLED)
        assert run_deny(tmp_path, prompt).returncode == 0

    def test_empty_or_broken_input_is_fail_soft(self, tmp_path: Path) -> None:
        write_dev_workflow(tmp_path, ENABLED)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        for raw in ("", "{not json"):
            proc = subprocess.run(["bash", str(DENY_HOOK)], input=raw, capture_output=True, text=True, check=False, env=env)
            assert proc.returncode == 0


class TestHooksJson:
    def test_registers_both_hooks_via_plugin_root(self) -> None:
        cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
        submit = cfg["UserPromptSubmit"][0]["hooks"][0]["command"]
        post = cfg["PostToolUse"][0]
        assert submit == "${CLAUDE_PLUGIN_ROOT}/hooks/deny-mattpocock-implement.sh"
        assert post["matcher"] == "mcp__github__create_pull_request"
        assert post["hooks"][0]["command"] == "${CLAUDE_PLUGIN_ROOT}/hooks/pr-review-dispatch.sh"

    def test_registered_scripts_exist_and_are_executable(self) -> None:
        for name in ("deny-mattpocock-implement.sh", "pr-review-dispatch.sh"):
            assert os.access(HOOKS / name, os.X_OK), name
