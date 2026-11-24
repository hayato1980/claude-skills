"""CLI: ページの扱い・失敗時メッセージ・出力（取得関数は偽物を注入し、ネットワークには触らない）。"""

from __future__ import annotations

import sys

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

import json
from pathlib import Path
from typing import Any

import pytest

from session_closeout.__main__ import EXIT_INCOMPLETE, EXIT_NEEDS_CONTEXT, main
from session_closeout.judge import IssueState, PullRequest


REPO = "acme/widgets"


def _row(sid: str, tags: list[str], revision: str | None = None) -> dict[str, Any]:
    repo: dict[str, Any] = {"url": "https://github.com/acme/widgets"}
    if revision:
        repo["revision"] = revision
    return {"id": sid, "session_status": "SESSION_STATUS_IDLE", "status_bucket": "SESSION_STATUS_BUCKET_COMPLETED",
            "tags": tags, "title": sid, "session_context": {"sources": [{"git_repository": repo}]}}


def _write(tmp_path: Path, name: str, rows: list[dict[str, Any]], *, has_more: bool, last_id: str) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"ccr": {"data": rows, "has_more": has_more, "last_id": last_id}}), encoding="utf-8")
    return p


def _merged(issue: int) -> IssueState:
    return IssueState(state="closed", prs=[PullRequest(number=issue + 100, state="closed", merged=True, draft=False)])


def test_missing_pages_returns_incomplete_with_after_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--repo", REPO, str(_write(tmp_path, "p1", [], has_more=True, last_id="session_X"))], fetch=_merged)
    assert rc == EXIT_INCOMPLETE
    assert 'after_id="session_X"' in capsys.readouterr().err


def test_after_id_follows_the_last_page_given(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p1 = _write(tmp_path, "p1", [], has_more=True, last_id="a")
    p2 = _write(tmp_path, "p2", [], has_more=True, last_id="b")
    assert main(["--repo", REPO, str(p1), str(p2)], fetch=_merged) == EXIT_INCOMPLETE
    assert 'after_id="b"' in capsys.readouterr().err


def test_pages_out_of_order_are_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    last = _write(tmp_path, "p2", [], has_more=False, last_id="b")
    first = _write(tmp_path, "p1", [], has_more=True, last_id="a")
    assert main(["--repo", REPO, str(last), str(first)], fetch=_merged) == 1
    assert "取得順に渡す" in capsys.readouterr().err


def test_unreadable_file_names_the_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "bad.txt"
    p.write_text("garbage", encoding="utf-8")
    assert main(["--repo", REPO, str(p)], fetch=_merged) == 1
    assert f"{p}: list_sessions の結果として読めない" in capsys.readouterr().err


def test_unexpected_github_shape_names_the_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def broken(issue: int) -> IssueState:
        raise KeyError("state")

    page = _write(tmp_path, "p", [_row("s1", ["issue-5"])], has_more=False, last_id="s1")
    assert main(["--repo", REPO, str(page)], fetch=broken) == 1
    assert "#5 の issue / PR を取れない: KeyError: 'state'" in capsys.readouterr().err


class TestOutput:
    def _page(self, tmp_path: Path) -> Path:
        rows = [_row("impl", ["tdd", "issue-7"]), _row("rev", ["review-dialogue", "issue-7"], "claude/issue-7"),
                _row("me", ["issue-7"]), _row("hand", [])]
        return _write(tmp_path, "p", rows, has_more=False, last_id="hand")

    def test_table(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--repo", REPO, str(self._page(tmp_path)), "--self-id", "me"], fetch=_merged) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[2] == ("| #7 | 終了 | PR #107 merged | closed | #107(merged) | "
                            "impl（修正側 / completed）<br>rev（レビュー側 / completed） |")
        assert "対象外: me — 自分自身" in lines
        assert "対象外: hand — issue-<番号> タグが無い（手で開いたセッション）" in lines

    def test_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--repo", REPO, str(self._page(tmp_path)), "--self-id", "me", "--format", "json"], fetch=_merged) == 0
        out = json.loads(capsys.readouterr().out)
        bundle = out["bundles"][0]
        assert (bundle["issue"], bundle["verdict"]["kind"]) == (7, "終了")
        assert [(s["id"], s["role"]) for s in bundle["sessions"]] == [("impl", "修正側"), ("rev", "レビュー側")]
        assert out["excluded"][0] == {"id": "me", "reason": "自分自身"}


def test_repo_defaults_to_git_remote_origin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "r"), "remote", "add", "origin", "git@github.com:acme/widgets.git"], check=True)
    monkeypatch.chdir(tmp_path / "r")
    page = _write(tmp_path, "p", [_row("impl", ["issue-7"])], has_more=False, last_id="impl")
    assert main([str(page)], fetch=_merged) == 0
    assert "| #7 |" in capsys.readouterr().out


def test_repo_unreadable_without_remote_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    monkeypatch.chdir(tmp_path / "r")
    page = _write(tmp_path, "p", [_row("impl", ["issue-7"])], has_more=False, last_id="impl")
    assert main([str(page)], fetch=_merged) == 1
    assert "--repo owner/repo" in capsys.readouterr().err


def test_repo_root_env_selects_the_repo_regardless_of_cwd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "r"), "remote", "add", "origin", "git@github.com:acme/widgets.git"], check=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("SESSION_CLOSEOUT_REPO_ROOT", str(tmp_path / "r"))
    page = _write(tmp_path, "p", [_row("impl", ["issue-7"])], has_more=False, last_id="impl")
    assert main([str(page)], fetch=_merged) == 0
    assert "| #7 |" in capsys.readouterr().out


class TestCompletionFromGetSession:
    """list_sessions の行に session_context が無いとき、get_session の結果で補う（#31）。"""

    def _rows(self) -> list[dict[str, Any]]:
        # issue #31 に書かれた、list_sessions の行の実測のキー集合（session_context 無し）。
        return [
            {"created_at": "2026-11-20T00:00:00Z", "environment_kind": "anthropic_cloud", "id": sid,
             "origin": "claude_code_mcp_seed", "parent_session_id": "session_parent",
             "post_turn_summary": {"recent_action": "x", "needs_action": False},
             "session_status": "SESSION_STATUS_IDLE", "status_bucket": "SESSION_STATUS_BUCKET_COMPLETED",
             "tags": tags, "task_summary": "x", "title": sid, "unread": False, "updated_at": "2026-11-21T00:00:00Z"}
            for sid, tags in (("impl", ["tdd", "issue-7"]), ("rev", ["review-dialogue", "issue-7"]))
        ]

    def _detail(self, tmp_path: Path, sid: str, revision: str | None) -> Path:
        repo: dict[str, Any] = {"url": "https://github.com/acme/widgets"}
        if revision:
            repo["revision"] = revision
        p = tmp_path / f"detail_{sid}.json"
        p.write_text(json.dumps({"ccr": {"id": sid, "session_context": {"sources": [{"git_repository": repo}]}}}),
                     encoding="utf-8")
        return p

    def test_asks_for_get_session_on_the_ids_that_need_it(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        page = _write(tmp_path, "p", self._rows(), has_more=False, last_id="rev")
        assert main(["--repo", REPO, str(page)], fetch=_merged) == EXIT_NEEDS_CONTEXT
        err = capsys.readouterr().err
        assert "get_session" in err and "impl" in err and "rev" in err and "--session" in err

    def test_bundles_with_role_from_the_completed_revision(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        page = _write(tmp_path, "p", self._rows(), has_more=False, last_id="rev")
        d1, d2 = self._detail(tmp_path, "impl", None), self._detail(tmp_path, "rev", "claude/issue-7")
        assert main(["--repo", REPO, "--session", str(d1), "--session", str(d2), str(page)], fetch=_merged) == 0
        out = capsys.readouterr().out
        assert "impl（修正側" in out and "rev（レビュー側" in out
        assert "対象外" not in out

    def test_partial_completion_still_asks_for_the_rest(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        page = _write(tmp_path, "p", self._rows(), has_more=False, last_id="rev")
        d1 = self._detail(tmp_path, "impl", None)
        assert main(["--repo", REPO, "--session", str(d1), str(page)], fetch=_merged) == EXIT_NEEDS_CONTEXT
        err = capsys.readouterr().err
        assert "rev" in err and "impl" not in err.split("--session")[0]


class TestTruncation:
    def _archived_page(self, tmp_path: Path, name: str) -> Path:
        row = {**_row(name, ["issue-1"]), "session_status": "SESSION_STATUS_ARCHIVED"}
        return _write(tmp_path, name, [row], has_more=True, last_id=name)

    def test_truncates_explicitly_instead_of_asking_for_more(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pages = [str(self._archived_page(tmp_path, n)) for n in ("p1", "p2")]
        assert main(["--repo", REPO, *pages], fetch=_merged) == 0
        out = capsys.readouterr().out
        assert "打ち切り" in out and "2 ページ" in out

    def test_default_k_is_documented_value(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pages = [str(self._archived_page(tmp_path, n)) for n in ("p1", "p2")]
        assert main(["--repo", REPO, *pages], fetch=_merged) == 0
        assert "打ち切り" in capsys.readouterr().out

    def test_without_enough_archived_pages_still_incomplete(self, tmp_path: Path) -> None:
        assert main(["--repo", REPO, str(self._archived_page(tmp_path, "p1"))], fetch=_merged) == EXIT_INCOMPLETE
