"""プラグインの hook 2 本と hooks.json の検証。

- pr-review-dispatch.sh: 最初の prompt がフロー起動（dev-workflow の器以外）のセッションにだけ、PR 作成直後にレビュー払い出しを促す。
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


def transcript(tmp_path: Path, first_prompt: str, *, as_command_tag: str | None = None) -> Path:
    if as_command_tag:
        first_prompt = (
            f"<command-message>{as_command_tag}</command-message>\n"
            f"<command-name>/{as_command_tag}</command-name>\n"
            f"<command-args>{first_prompt}</command-args>"
        )
    entries = [
        {"type": "user", "message": {"role": "user", "content": first_prompt}},
        {"type": "assistant", "message": {"role": "assistant", "content": []}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "後続"}]}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n")
    return path


def run_dispatch(path: Path | None, *, env_path: str | None = None) -> subprocess.CompletedProcess[str]:
    payload = {"hook_event_name": "PostToolUse", "tool_name": "mcp__github__create_pull_request",
               "transcript_path": str(path) if path else ""}
    env = {**os.environ, **({"PATH": env_path} if env_path is not None else {})}
    return subprocess.run(["bash", str(DISPATCH_HOOK)], input=json.dumps(payload), capture_output=True, text=True, check=False, env=env)


class TestPrReviewDispatch:
    @pytest.mark.parametrize("flow", ["mattpocock-skills:tdd", "mattpocock-skills:diagnosing-bugs", "mattpocock-skills:grill-with-docs"])
    def test_flow_session_gets_the_dispatch_reminder(self, tmp_path: Path, flow: str) -> None:
        proc = run_dispatch(transcript(tmp_path, f"/{flow} #1429"))
        assert proc.returncode == 0
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        assert out["hookEventName"] == "PostToolUse"
        ctx = out["additionalContext"]
        assert f"/{flow} で始まった" in ctx
        assert "PR 作成後の自動レビュー払い出し" in ctx
        assert "create-ccw-session" in ctx
        assert "#1429" in ctx and "claude/issue-1429" in ctx
        assert "/code-review は回さない" in ctx

    @pytest.mark.parametrize("flow", ["mattpocock-skills:tdd", "mattpocock-skills:diagnosing-bugs"])
    def test_command_tag_form_also_matches(self, tmp_path: Path, flow: str) -> None:
        proc = run_dispatch(transcript(tmp_path, "#88", as_command_tag=flow))
        assert "claude/issue-88" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.parametrize(
        "prompt",
        [
            "この Issue を直して",
            "/review-dialogue #1429",
            "/dev-workflow:review-dialogue #1429",
            "/dev-workflow:create-ccw-session #1429 tdd",
            "/dev-workflow:session-closeout #1429",
            "/mattpocock-skills:code-review",
            "メモ: /mattpocock-skills:tdd #1429 を使う予定",
        ],
    )
    def test_other_sessions_get_nothing(self, tmp_path: Path, prompt: str) -> None:
        proc = run_dispatch(transcript(tmp_path, prompt))
        assert (proc.returncode, proc.stdout.strip()) == (0, "")

    def test_review_dialogue_command_tag_form_gets_nothing(self, tmp_path: Path) -> None:
        # レビュー側の子が払い出し直すと、往復の「相手を引く」で相手が 2 件になる。
        proc = run_dispatch(transcript(tmp_path, "#1429", as_command_tag="dev-workflow:review-dialogue"))
        assert (proc.returncode, proc.stdout.strip()) == (0, "")

    @pytest.mark.parametrize("kind", ["unset", "nonexistent"])
    def test_unreadable_transcript_is_fail_soft(self, tmp_path: Path, kind: str) -> None:
        path = None if kind == "unset" else tmp_path / "nope.jsonl"
        proc = run_dispatch(path)
        assert (proc.returncode, proc.stdout.strip()) == (0, "")

    def test_missing_jq_is_loud_not_silent(self, tmp_path: Path) -> None:
        # jq が無いのに黙って成功すると、この hook が防ぎたい「レビューが払い出されないまま止まる」が起きる。
        bindir = tmp_path / "bin"
        bindir.mkdir()
        for tool in ("bash", "cat", "dirname"):
            found = shutil.which(tool)
            assert found
            (bindir / tool).symlink_to(found)
        proc = run_dispatch(transcript(tmp_path, "/mattpocock-skills:tdd #1"), env_path=str(bindir))
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
