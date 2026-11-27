"""`session_closeout counterpart`: issue / PR について、自分の役割から見た相手を保存ファイルだけで判定する。

list_sessions の実測の行には session_context が無い（#31）ので、行は context 無しで作り、get_session の結果は別ファイルで渡す。
"""

from __future__ import annotations

import sys

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from session_closeout.__main__ import main
from session_closeout.bundles import EXIT_INCOMPLETE, EXIT_NEEDS_CONTEXT

REPO = "acme/widgets"
REPO_URL = "https://github.com/acme/widgets"
ISSUE_BRANCH = "claude/issue-49"


@pytest.fixture(autouse=True)
def _own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # 自分の session id は呼び出し環境から読む。テストごとに環境へ依存させない。
    monkeypatch.setenv("CLAUDE_CODE_REMOTE_SESSION_ID", "cse_unrelated")


def _row(sid: str, tags: list[str], *, archived: bool = False) -> dict[str, Any]:
    # 実測の list_sessions の行: session_context を持たない。
    return {"id": sid, "session_status": "SESSION_STATUS_ARCHIVED" if archived else "SESSION_STATUS_IDLE",
            "status_bucket": "SESSION_STATUS_BUCKET_COMPLETED", "tags": tags, "title": sid}


def _page(tmp_path: Path, name: str, rows: list[dict[str, Any]], *, has_more: bool = False, last_id: str = "x") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"ccr": {"data": rows, "has_more": has_more, "last_id": last_id}}), encoding="utf-8")
    return p


def _detail(tmp_path: Path, sid: str, revision: str | None, url: str = REPO_URL) -> Path:
    repo: dict[str, Any] = {"url": url}
    if revision:
        repo["revision"] = revision
    p = tmp_path / f"detail-{sid}.json"
    p.write_text(json.dumps({"ccr": {"id": sid, "session_context": {"sources": [{"git_repository": repo}]}}}), encoding="utf-8")
    return p


def _ask(tmp_path: Path, capsys: pytest.CaptureFixture[str], rows: list[dict[str, Any]], revisions: dict[str, str | None],
         *argv: str, self_id: str | None = None) -> tuple[int, str, str]:
    page = _page(tmp_path, "p1", rows)
    details = [f"--session={_detail(tmp_path, sid, rev)}" for sid, rev in revisions.items()]
    extra = ["--self-id", self_id] if self_id else []
    return _run([*argv, *extra, str(page), *details], capsys)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    rc = main(["counterpart", "--repo", REPO, *argv])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_no_session_tagged_for_the_issue_means_none(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    page = _page(tmp_path, "p1", [_row("session_other", ["issue-7"])])
    rc, out, _ = _run(["--want", "reviewer", "--issue", "49", str(page)], capsys)
    assert (rc, out.strip()) == (0, "none")


def test_candidate_without_session_context_asks_for_get_session_even_when_it_is_the_only_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 候補が 1 つでも revision を確かめる。違う相手を起こしても手順上は成功に見えるため（#30）。
    page = _page(tmp_path, "p1", [_row("session_a", ["issue-49"])])
    rc, out, err = _run(["--want", "reviewer", "--issue", "49", str(page)], capsys)
    assert rc == EXIT_NEEDS_CONTEXT
    assert out == ""
    assert "session_a" in err


def test_wants_reviewer_finds_the_session_on_the_issue_branch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    page = _page(tmp_path, "p1", [_row("session_fix", ["issue-49"]), _row("session_rev", ["issue-49"])])
    details = [_detail(tmp_path, "session_fix", None), _detail(tmp_path, "session_rev", ISSUE_BRANCH)]
    rc, out, _ = _run(["--want", "reviewer", "--issue", "49", str(page), *(f"--session={d}" for d in details)], capsys)
    assert (rc, out.strip()) == (0, "found session_rev")


def test_wants_fixer_finds_the_session_not_on_the_issue_branch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_row("session_fix", ["issue-49"]), _row("session_rev", ["issue-49"])]
    revisions = {"session_fix": "main", "session_rev": ISSUE_BRANCH}
    rc, out, _ = _ask(tmp_path, capsys, rows, revisions, "--want", "fixer", "--issue", "49")
    assert (rc, out.strip()) == (0, "found session_fix")


def test_session_without_revision_is_not_the_reviewer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_row("session_a", ["issue-49"])]
    rc, out, _ = _ask(tmp_path, capsys, rows, {"session_a": None}, "--want", "reviewer", "--issue", "49")
    assert (rc, out.strip()) == (0, "none")


def test_two_candidates_are_ambiguous_not_a_pick(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_row("session_r1", ["issue-49"]), _row("session_r2", ["issue-49"])]
    rc, out, _ = _ask(tmp_path, capsys, rows, {"session_r1": ISSUE_BRANCH, "session_r2": ISSUE_BRANCH},
                      "--want", "reviewer", "--issue", "49")
    assert (rc, out.strip()) == (0, "ambiguous session_r1,session_r2")


def test_own_session_is_not_its_own_counterpart(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_row("session_me", ["issue-49"]), _row("session_rev", ["issue-49"])]
    revisions = {"session_rev": ISSUE_BRANCH}
    rc, out, _ = _ask(tmp_path, capsys, rows, revisions, "--want", "reviewer", "--issue", "49", self_id="session_me")
    assert (rc, out.strip()) == (0, "found session_rev")


def test_archived_and_other_issue_and_other_repo_rows_are_not_candidates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = _page(tmp_path, "p1", [_row("session_old", ["issue-49"], archived=True), _row("session_seven", ["issue-7"]),
                                  _row("session_elsewhere", ["issue-49"])])
    detail = _detail(tmp_path, "session_elsewhere", ISSUE_BRANCH, url="https://github.com/acme/other")
    rc, out, err = _run(["--want", "reviewer", "--issue", "49", str(page), f"--session={detail}"], capsys)
    assert (rc, out.strip()) == (0, "none")
    assert "session_elsewhere" in err  # 除いた行と理由は stderr へ


def test_pr_without_issue_is_looked_up_by_pr_tag_and_head_branch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_row("session_fix", ["pr-12"]), _row("session_rev", ["pr-12"]), _row("session_issue", ["issue-12"])]
    revisions = {"session_fix": "main", "session_rev": "feature/x"}
    rc, out, _ = _ask(tmp_path, capsys, rows, revisions, "--want", "reviewer", "--pr", "12", "--head", "feature/x")
    assert (rc, out.strip()) == (0, "found session_rev")


def test_pr_lookup_without_head_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = _ask(tmp_path, capsys, [], {}, "--want", "reviewer", "--pr", "12")
    assert rc == 1
    assert "--head" in err


def test_more_pages_are_required_before_deciding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    page = _page(tmp_path, "p1", [_row("session_a", ["issue-7"])], has_more=True, last_id="session_a")
    rc, out, err = _run(["--want", "reviewer", "--issue", "49", str(page)], capsys)
    assert (rc, out) == (EXIT_INCOMPLETE, "")
    assert 'after_id="session_a"' in err


def test_two_trailing_archived_pages_end_the_search(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    live = _page(tmp_path, "p1", [_row("session_rev", ["issue-49"])], has_more=True, last_id="a")
    old1 = _page(tmp_path, "p2", [_row("s_old1", ["issue-49"], archived=True)], has_more=True, last_id="b")
    old2 = _page(tmp_path, "p3", [_row("s_old2", ["issue-49"], archived=True)], has_more=True, last_id="c")
    detail = _detail(tmp_path, "session_rev", ISSUE_BRANCH)
    rc, out, _ = _run(["--want", "reviewer", "--issue", "49", str(live), str(old1), str(old2), f"--session={detail}"], capsys)
    assert (rc, out.strip()) == (0, "found session_rev")


def test_one_trailing_archived_page_is_not_enough_to_stop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    live = _page(tmp_path, "p1", [_row("session_rev", ["issue-49"])], has_more=True, last_id="a")
    old1 = _page(tmp_path, "p2", [_row("s_old1", ["issue-49"], archived=True)], has_more=True, last_id="b")
    rc, _, err = _run(["--want", "reviewer", "--issue", "49", str(live), str(old1)], capsys)
    assert rc == EXIT_INCOMPLETE
    assert 'after_id="b"' in err


def test_repo_defaults_to_git_remote_origin_like_the_closeout_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "work"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", f"{REPO_URL}.git"], check=True)
    monkeypatch.setenv("SESSION_CLOSEOUT_REPO_ROOT", str(repo))
    page = _page(tmp_path, "p1", [_row("session_rev", ["issue-49"])])
    detail = _detail(tmp_path, "session_rev", ISSUE_BRANCH)
    assert main(["counterpart", "--want", "reviewer", "--issue", "49", str(page), f"--session={detail}"]) == 0
    assert capsys.readouterr().out.strip() == "found session_rev"


def test_self_id_defaults_to_the_environment_variable_with_its_prefix_swapped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_REMOTE_SESSION_ID", "cse_me")
    rows = [_row("session_me", ["issue-49"]), _row("session_rev", ["issue-49"])]
    rc, out, _ = _ask(tmp_path, capsys, rows, {"session_rev": ISSUE_BRANCH}, "--want", "reviewer", "--issue", "49")
    assert (rc, out.strip()) == (0, "found session_rev")


def test_without_a_known_own_session_id_it_stops_instead_of_silently_not_excluding_itself(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_REMOTE_SESSION_ID")
    rc, out, err = _ask(tmp_path, capsys, [], {}, "--want", "reviewer", "--issue", "49")
    assert (rc, out) == (1, "")
    assert "--self-id" in err


def test_head_overrides_the_issue_branch_for_a_pr_whose_head_is_not_the_issue_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [_row("session_fix", ["issue-49"]), _row("session_rev", ["issue-49"])]
    revisions = {"session_fix": "main", "session_rev": "owner/direct-branch"}
    rc, out, _ = _ask(tmp_path, capsys, rows, revisions, "--want", "reviewer", "--issue", "49", "--head", "owner/direct-branch")
    assert (rc, out.strip()) == (0, "found session_rev")
