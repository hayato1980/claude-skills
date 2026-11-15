"""CLI: ページの扱い・失敗時メッセージ・出力（取得関数は偽物を注入し、ネットワークには触らない）。"""

from __future__ import annotations

import sys

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

import json
from pathlib import Path
from typing import Any

import pytest

from session_closeout.__main__ import EXIT_INCOMPLETE, main
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
