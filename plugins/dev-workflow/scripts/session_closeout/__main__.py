"""CLI（締めの判定。先頭の語 `counterpart` / `events` で、セッションの関係を読む別の問い合わせになる → counterpart.py / events.py）:
`session_closeout.sh <list_sessions の結果ファイル（取得順）>... [--session <get_session の結果ファイル>]... [--issue N ...] [--repo owner/repo]`。

終了コード: 0 = 判定を出した / 2 = ページが足りない（次の `after_id` を stderr に出す）/
3 = list_sessions の行に session_context が無く、get_session での補完が要る（id を stderr に出す）/ 1 = 入力・通信の失敗。
GitHub は環境の GH_TOKEN（無ければ GITHUB_TOKEN）で REST を直接読む（gh CLI には依存しない）。
対象リポは `--repo`、無ければ `git remote origin`。呼び出しは各リポの中継スクリプト経由（許可ルールが固定パスを指すため）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bundles import Grouping, bucket_short, fill_session_context, group, is_truncated, load_details, issue_branch, load_pages, next_after_id, repo_from_remote_url
from .judge import IssueState, PullRequest, Verdict, judge, judge_pr

_GH_API = "https://api.github.com"
EXIT_INCOMPLETE = 2
EXIT_NEEDS_CONTEXT = 3
STOP_AFTER_ARCHIVED_PAGES = 2  # アーカイブ済みだけのページがこの枚数続いたら打ち切る（SKILL.md と一致させる）

Fetch = Callable[[int], IssueState]
FetchPr = Callable[[int], PullRequest]


def _default_self_id() -> str | None:
    # CCR の環境変数は cse_<id>、list_sessions の id は session_<id>（接尾辞が同じ）。
    raw = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID")
    return "session_" + raw.removeprefix("cse_") if raw else None


def _default_repo() -> str:
    # 中継が SESSION_CLOSEOUT_REPO_ROOT で対象リポを渡す（cwd は変えない: 結果ファイルの相対パスを保つため）。
    root = os.environ.get("SESSION_CLOSEOUT_REPO_ROOT")
    cmd = ["git", *(["-C", root] if root else []), "remote", "get-url", "origin"]
    try:
        url = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise ValueError(f"git remote origin を読めない（--repo owner/repo で渡す）: {e}") from e
    return repo_from_remote_url(url)


def _gh_get(path: str, token: str) -> Any:
    req = urllib.request.Request(
        _GH_API + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def github_fetcher(repo: str, token: str) -> Fetch:
    owner = repo.split("/")[0]

    def fetch(issue: int) -> IssueState:
        state = _gh_get(f"/repos/{repo}/issues/{issue}", token)["state"]
        query = urllib.parse.urlencode({"head": f"{owner}:{issue_branch(issue)}", "state": "all", "per_page": 100})
        prs = [
            PullRequest(number=p["number"], state=p["state"], merged=p.get("merged_at") is not None, draft=p["draft"])
            for p in _gh_get(f"/repos/{repo}/pulls?{query}", token)
        ]
        return IssueState(state=state, prs=prs)

    return fetch


def github_pr_fetcher(repo: str, token: str) -> FetchPr:
    def fetch(number: int) -> PullRequest:
        p = _gh_get(f"/repos/{repo}/pulls/{number}", token)
        return PullRequest(number=p["number"], state=p["state"], merged=p.get("merged_at") is not None,
                           draft=p["draft"], head=p["head"]["ref"])

    return fetch


def _render_table(grouping: Grouping, states: dict[int, IssueState], verdicts: dict[int, Verdict],
                  prs: dict[int, PullRequest], pr_verdicts: dict[int, Verdict]) -> str:
    lines = ["| 束 | 判定 | 理由 | issue | PR | セッション（役割 / status_bucket） |", "|---|---|---|---|---|---|"]
    for n, sessions in grouping.bundles.items():
        st, v = states[n], verdicts[n]
        pr_text = ", ".join(f"#{p.number}({'merged' if p.merged else p.state})" for p in st.prs) or "無し"
        sess = "<br>".join(f"{s.id}（{s.role(n)} / {bucket_short(s.bucket)}）" for s in sessions)
        lines.append(f"| #{n} | {v.kind} | {v.reason} | {st.state} | {pr_text} | {sess} |")
    for n, sessions in grouping.pr_bundles.items():
        pr, v = prs[n], pr_verdicts[n]
        sess = "<br>".join(f"{s.id}（{s.role_on(pr.head)} / {bucket_short(s.bucket)}）" for s in sessions)
        lines.append(f"| PR #{n} | {v.kind} | {v.reason} | 無し | #{n}({'merged' if pr.merged else pr.state}) | {sess} |")
    lines.append("")
    lines.append(f"archive 済み（除外）: {grouping.archived} 件")
    if grouping.truncated_after:
        lines.append(f"打ち切り: archive 済みだけのページが {grouping.truncated_after} ページ続いたので、それ以降は引いていない")
    for s, reason in grouping.excluded:
        lines.append(f"対象外: {s.id} — {reason}")
    return "\n".join(lines)


def _render_json(grouping: Grouping, states: dict[int, IssueState], verdicts: dict[int, Verdict],
                 prs: dict[int, PullRequest], pr_verdicts: dict[int, Verdict]) -> str:
    out = {
        "bundles": [
            {
                "issue": n,
                "issue_state": states[n].state,
                "prs": [asdict(p) for p in states[n].prs],
                "verdict": asdict(verdicts[n]),
                "sessions": [{"id": s.id, "role": s.role(n), "status": s.status, "bucket": s.bucket,
                              "revision": s.revision, "title": s.title} for s in sessions],
            }
            for n, sessions in grouping.bundles.items()
        ],
        "pr_bundles": [
            {
                "pr": n,
                "pr_state": asdict(prs[n]),
                "verdict": asdict(pr_verdicts[n]),
                "sessions": [{"id": s.id, "role": s.role_on(prs[n].head), "status": s.status, "bucket": s.bucket,
                              "revision": s.revision, "title": s.title} for s in sessions],
            }
            for n, sessions in grouping.pr_bundles.items()
        ],
        "archived": grouping.archived,
        "truncated_after_archived_pages": grouping.truncated_after,
        "excluded": [{"id": s.id, "reason": r} for s, r in grouping.excluded],
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


def _github_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GH_TOKEN（または GITHUB_TOKEN）が未設定です。")
    return token


def _github_from_env(repo: str) -> Fetch:
    return github_fetcher(repo, _github_token())


def _github_pr_from_env(repo: str) -> FetchPr:
    return github_pr_fetcher(repo, _github_token())


def main(argv: list[str] | None = None, fetch: Fetch | None = None, fetch_pr: FetchPr | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    if args_in[:1] == ["counterpart"]:
        from .counterpart import run as run_counterpart

        return run_counterpart(args_in[1:])
    if args_in[:1] == ["events"]:
        from .events import run as run_events

        return run_events(args_in[1:])
    ap = argparse.ArgumentParser(prog="session_closeout.sh", description=__doc__)
    ap.add_argument("pages", nargs="+", type=Path, help="list_sessions の結果ファイル（取得順）")
    ap.add_argument("--issue", type=int, action="append", help="対象を絞る issue 番号（複数可）")
    ap.add_argument("--pr", type=int, action="append", help="対象を絞る PR 番号（issue を持たない PR の `pr-<番号>` タグ。複数可）")
    ap.add_argument("--self-id", default=_default_self_id(), help="除外する自分の session id（既定は環境変数から）")
    ap.add_argument("--repo", help="owner/repo（既定は git remote origin）")
    ap.add_argument("--session", action="append", type=Path, default=[],
                    help="get_session の結果ファイル（要補完の id ごとに 1 つ。複数可）")
    ap.add_argument("--format", choices=["table", "json"], default="table")
    args = ap.parse_args(args_in)

    try:
        repo = args.repo or _default_repo()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    try:
        pages = load_pages(args.pages)
        after_id = next_after_id(pages)  # 順序の誤りはここで検出する
        truncated = is_truncated(pages, STOP_AFTER_ARCHIVED_PAGES)
    except (OSError, ValueError) as e:
        print(f"結果ファイルを読めない: {e}", file=sys.stderr)
        return 1
    if after_id is not None and not truncated:
        print(f'ページが足りない: list_sessions(mine=true, limit=100, after_id="{after_id}") の結果を末尾に足す',
              file=sys.stderr)
        return EXIT_INCOMPLETE

    try:
        pages = fill_session_context(pages, load_details(args.session))
    except (OSError, ValueError) as e:
        print(f"結果ファイルを読めない: {e}", file=sys.stderr)
        return 1
    grouping = group(pages, args.self_id, set(args.issue) if args.issue else None, repo,
                     truncated_after=STOP_AFTER_ARCHIVED_PAGES if truncated else None,
                     prs=set(args.pr) if args.pr else None)
    if grouping.needs_context:
        ids = " ".join(s.id for s in grouping.needs_context)
        print("list_sessions の行に session_context が無い。次の id を get_session で引き、"
              f"保存された結果を --session で 1 つずつ足す: {ids}", file=sys.stderr)
        return EXIT_NEEDS_CONTEXT
    states: dict[int, IssueState] = {}
    verdicts: dict[int, Verdict] = {}
    prs: dict[int, PullRequest] = {}
    pr_verdicts: dict[int, Verdict] = {}
    try:
        get = fetch or _github_from_env(repo)
        for n, sessions in grouping.bundles.items():
            try:
                states[n] = get(n)
            except (OSError, KeyError, json.JSONDecodeError) as e:
                raise ValueError(f"#{n} の issue / PR を取れない: {type(e).__name__}: {e}") from e
            verdicts[n] = judge(sessions, states[n])
        if grouping.pr_bundles:
            get_pr = fetch_pr or _github_pr_from_env(repo)
            for n, sessions in grouping.pr_bundles.items():
                try:
                    prs[n] = get_pr(n)
                except (OSError, KeyError, json.JSONDecodeError) as e:
                    raise ValueError(f"PR #{n} を取れない: {type(e).__name__}: {e}") from e
                pr_verdicts[n] = judge_pr(sessions, prs[n])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    render = _render_json if args.format == "json" else _render_table
    print(render(grouping, states, verdicts, prs, pr_verdicts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
