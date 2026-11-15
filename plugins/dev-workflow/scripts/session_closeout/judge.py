"""束が「終わっている」かの判定（SKILL.md 手順 2 の 2 つの表）。ネットワークには触らない。"""

from __future__ import annotations

from dataclasses import dataclass

from .bundles import Session, bucket_short

UNFINISHED = "未了"
NEEDS_OWNER = "要確認"
DONE = "終了"
READ_CONVERSATION = "会話で判定"

_WORKING = "SESSION_STATUS_BUCKET_WORKING"
_STUCK = ("SESSION_STATUS_BUCKET_FAILED", "SESSION_STATUS_BUCKET_BLOCKED")


@dataclass(frozen=True)
class PullRequest:
    number: int
    state: str  # "open" | "closed"
    merged: bool
    draft: bool


@dataclass(frozen=True)
class IssueState:
    """束の issue と PR の状態。取得は CLI 側（ここはネットワークに触らない）。"""

    state: str  # "open" | "closed"
    prs: list[PullRequest]


@dataclass(frozen=True)
class Verdict:
    kind: str
    reason: str
    issue_is_candidate: bool = False  # issue そのものを手順 4 の候補に入れるか


def judge(sessions: list[Session], github: IssueState) -> Verdict:
    """束を丸ごと判定する。オーナーへの質問の有無は会話を読まないと分からないので、ここでは見ない（手順 3）。"""
    prs = github.prs
    open_prs = [p for p in prs if p.state == "open"]
    if open_prs:
        p = open_prs[0]
        return Verdict(UNFINISHED, f"PR #{p.number} が {'draft' if p.draft else 'open'}")
    working = [s for s in sessions if s.bucket == _WORKING]
    if working:
        return Verdict(UNFINISHED, f"{working[0].id} が working")
    stuck = [s for s in sessions if s.bucket in _STUCK]
    if stuck:
        return Verdict(NEEDS_OWNER, f"{stuck[0].id} が status_bucket={bucket_short(stuck[0].bucket)}")

    merged = [p for p in prs if p.merged]
    issue_open = github.state == "open"
    if merged:
        reason = f"PR #{merged[0].number} merged"
        if issue_open:
            return Verdict(DONE, reason + "、issue は open（残作業の払い出しかクローズを提案）", True)
        return Verdict(DONE, reason)
    if prs:
        reason = f"PR #{prs[0].number} が未マージで closed"
        if issue_open:
            return Verdict(NEEDS_OWNER, reason + "、issue は open（捨てたのか作り直し中かを会話から）")
        return Verdict(DONE, reason)
    if issue_open:
        return Verdict(READ_CONVERSATION, "PR 無し・issue open（最後のターンで成果を出し切っていれば終了）", True)
    return Verdict(DONE, "PR 無し・issue closed")
