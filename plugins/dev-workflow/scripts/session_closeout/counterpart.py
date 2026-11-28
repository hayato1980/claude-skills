"""`counterpart`: issue（または PR）について、自分の役割から見た相手を保存ファイルだけで判定する。

標準出力は 1 行: `found <session_id>` / `none` / `ambiguous <id>,<id>,…`（いずれも終了コード 0）。
終了コード: 2 = ページが足りない / 3 = get_session での revision の確認が要る / 1 = 入力の失敗。
GitHub は読まない（保存ファイルだけで判定する）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .bundles import (EXIT_INCOMPLETE, EXIT_NEEDS_CONTEXT, Grouping, ListingIncomplete, Session, group, issue_branch,
                      needs_context_message, parse_timestamp, read_listing)
from .environment import default_repo, default_self_id


@dataclass(frozen=True)
class Target:
    """相手を探す対象。`issue-<番号>` か `pr-<番号>` のタグで引き、`branch` と revision を突き合わせる。"""

    issue: int | None
    pr: int | None
    branch: str

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Target:
        if args.pr is not None and not args.head:
            raise ValueError("--pr には --head（PR の head ブランチ）が要る")
        # --head があれば対象ブランチはそれ。無ければ issue のブランチ（claude/issue-<番号>）。
        return cls(args.issue, args.pr, args.head or issue_branch(args.issue))

    def bundle(self, grouping: Grouping) -> list[Session]:
        return grouping.bundles.get(self.issue, []) if self.issue is not None else grouping.pr_bundles.get(self.pr, [])


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="session_closeout.sh counterpart", description=__doc__)
    ap.add_argument("pages", nargs="+", type=Path, help="list_sessions の結果ファイル（取得順）")
    ap.add_argument("--want", required=True, choices=["reviewer", "fixer"], help="探す側（自分の反対側）")
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--issue", type=int, help="issue 番号（タグ issue-<番号>）")
    which.add_argument("--pr", type=int, help="issue を持たない PR の番号（タグ pr-<番号>。--head が要る）")
    ap.add_argument("--head", help="PR の head ブランチ（対象ブランチ）。--issue と併用すると claude/issue-<番号> より優先する")
    ap.add_argument("--since", help="対象の issue（PR）の作成時刻（ISO 8601）。読んだ最も古い行がこれより前に届いたら、"
                    "続きのページを読まずに判定する（相手のセッションは対象より前には作られない）。無ければ最後のページまで読む")
    ap.add_argument("--self-id", default=default_self_id(), help="除外する自分の session id（既定は環境変数から）")
    ap.add_argument("--repo", help="owner/repo（既定は git remote origin）")
    ap.add_argument("--session", action="append", type=Path, default=[], help="get_session の結果ファイル")
    args = ap.parse_args(argv)
    try:
        target = Target.from_args(args)
        repo = args.repo or default_repo()
        since = parse_timestamp(args.since) if args.since else None
        if not args.self_id:
            raise ValueError("自分の session id が決まらない（環境変数 CLAUDE_CODE_REMOTE_SESSION_ID か --self-id）。"
                             "自分の除外が黙って無効になるので止める")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    try:
        pages, _ = read_listing(args.pages, args.session, confirm_all=True, since=since)
    except ListingIncomplete as e:
        print(e, file=sys.stderr)
        return EXIT_INCOMPLETE
    except (OSError, ValueError) as e:
        print(f"結果ファイルを読めない: {e}", file=sys.stderr)
        return 1

    grouping = group(pages, args.self_id, {target.issue} if target.issue is not None else None, repo,
                     prs={target.pr} if target.pr is not None else None)
    if grouping.needs_context:
        print(needs_context_message(grouping.needs_context), file=sys.stderr)
        return EXIT_NEEDS_CONTEXT
    for s, reason in grouping.excluded:
        print(f"除外: {s.id} — {reason}", file=sys.stderr)
    want_reviewer = args.want == "reviewer"
    found = [s.id for s in target.bundle(grouping) if (s.revision == target.branch) == want_reviewer]
    if not found:
        print("none")
    elif len(found) == 1:
        print(f"found {found[0]}")
    else:
        print(f"ambiguous {','.join(found)}")
    return 0
