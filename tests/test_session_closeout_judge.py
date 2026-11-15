"""judge: SKILL.md 手順 2 の 2 つの表の各行。"""

from __future__ import annotations

import sys

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

import pytest

from session_closeout.bundles import Session
from session_closeout.judge import (
    DONE,
    NEEDS_OWNER,
    READ_CONVERSATION,
    UNFINISHED,
    IssueState,
    PullRequest,
    judge,
)


def _s(bucket: str = "COMPLETED") -> Session:
    return Session(id="s1", status="SESSION_STATUS_IDLE", bucket=f"SESSION_STATUS_BUCKET_{bucket}",
                   tags=("issue-1",), revision=None, repo_url=None, title="t")


_MERGED = PullRequest(number=10, state="closed", merged=True, draft=False)
_CLOSED = PullRequest(number=11, state="closed", merged=False, draft=False)
_DRAFT = PullRequest(number=12, state="open", merged=False, draft=True)


class TestPrecedingRows:
    def test_open_pr_is_unfinished_even_if_older_pr_merged(self) -> None:
        v = judge([_s()], IssueState("open", [_DRAFT, _MERGED]))
        assert (v.kind, v.reason) == (UNFINISHED, "PR #12 が draft")

    def test_working_session_is_unfinished(self) -> None:
        assert judge([_s("WORKING")], IssueState("closed", [_MERGED])).kind == UNFINISHED

    @pytest.mark.parametrize("bucket", ["FAILED", "BLOCKED"])
    def test_stuck_session_needs_owner(self, bucket: str) -> None:
        assert judge([_s(bucket)], IssueState("closed", [_MERGED])).kind == NEEDS_OWNER

    def test_one_working_session_makes_whole_bundle_unfinished(self) -> None:
        assert judge([_s(), _s("WORKING")], IssueState("closed", [_MERGED])).kind == UNFINISHED


class TestPrIssueTable:
    @pytest.mark.parametrize(
        ("issue", "prs", "kind", "candidate"),
        [
            ("closed", [_MERGED], DONE, False),
            ("open", [_MERGED], DONE, True),
            ("closed", [_CLOSED], DONE, False),
            ("open", [_CLOSED], NEEDS_OWNER, False),
            ("closed", [], DONE, False),
            ("open", [], READ_CONVERSATION, True),
        ],
    )
    def test_rows(self, issue: str, prs: list[PullRequest], kind: str, candidate: bool) -> None:
        v = judge([_s("REVIEW_READY")], IssueState(issue, prs))
        assert (v.kind, v.issue_is_candidate) == (kind, candidate)

    def test_merged_wins_over_closed_unmerged(self) -> None:
        assert judge([_s()], IssueState("closed", [_CLOSED, _MERGED])).reason == "PR #10 merged"
