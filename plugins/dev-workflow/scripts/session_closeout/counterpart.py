"""`counterpart`: issue（または PR）について、自分の役割から見た相手 / 既存のレビューを保存ファイルだけで判定する。

標準出力は 1 行: `found <session_id>` / `none` / `ambiguous <id>,<id>,…`（いずれも終了コード 0）。
終了コード: 2 = ページが足りない / 3 = get_session での revision の確認が要る / 1 = 入力の失敗。
GitHub は読まない（保存ファイルだけで判定する）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .environment import default_repo, default_self_id
from .bundles import (Page, fill_session_context, group, is_truncated, issue_branch, load_details, load_pages,
                      next_after_id)

EXIT_INCOMPLETE = 2
EXIT_NEEDS_CONTEXT = 3
STOP_AFTER_ARCHIVED_PAGES = 2


def _forget_context(pages: list[Page]) -> list[Page]:
    """list_sessions の行の revision は当てにしない: 候補は必ず get_session の結果で確かめる。"""
    return [replace(p, sessions=[replace(s, context_known=False) for s in p.sessions]) for p in pages]


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="session_closeout.sh counterpart", description=__doc__)
    ap.add_argument("pages", nargs="+", type=Path, help="list_sessions の結果ファイル（取得順）")
    ap.add_argument("--want", required=True, choices=["reviewer", "fixer"], help="探す側（自分の反対側）")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--issue", type=int, help="issue 番号（対象ブランチは claude/issue-<番号>）")
    target.add_argument("--pr", type=int, help="issue を持たない PR の番号（--head が要る）")
    ap.add_argument("--head", help="--pr のときの PR の head ブランチ（対象ブランチ）")
    ap.add_argument("--self-id", default=default_self_id())
    ap.add_argument("--repo", help="owner/repo（既定は git remote origin）")
    ap.add_argument("--session", action="append", type=Path, default=[], help="get_session の結果ファイル")
    args = ap.parse_args(argv)
    if args.pr is not None and not args.head:
        print("--pr には --head（PR の head ブランチ）が要る", file=sys.stderr)
        return 1
    try:
        repo = args.repo or default_repo()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    branch = issue_branch(args.issue) if args.issue is not None else args.head

    try:
        pages = load_pages(args.pages)
        after_id = next_after_id(pages)
        truncated = is_truncated(pages, STOP_AFTER_ARCHIVED_PAGES)
        if after_id is not None and not truncated:
            print(f'ページが足りない: list_sessions(mine=true, limit=100, after_id="{after_id}") の結果を末尾に足す',
                  file=sys.stderr)
            return EXIT_INCOMPLETE
        pages = fill_session_context(_forget_context(pages), load_details(args.session))
    except (OSError, ValueError) as e:
        print(f"結果ファイルを読めない: {e}", file=sys.stderr)
        return 1

    grouping = group(pages, args.self_id, {args.issue} if args.issue is not None else None, repo,
                     prs={args.pr} if args.pr is not None else None)
    if grouping.needs_context:
        ids = " ".join(s.id for s in grouping.needs_context)
        print("list_sessions の行に session_context が無い。次の id を get_session で引き、"
              f"保存された結果を --session で 1 つずつ足す: {ids}", file=sys.stderr)
        return EXIT_NEEDS_CONTEXT
    for s, reason in grouping.excluded:
        print(f"除外: {s.id} — {reason}", file=sys.stderr)
    bundle = (grouping.bundles if args.issue is not None else grouping.pr_bundles).get(args.issue or args.pr, [])
    is_reviewer = args.want == "reviewer"
    found = [s.id for s in bundle if (s.revision == branch) == is_reviewer]
    if not found:
        print("none")
    elif len(found) == 1:
        print(f"found {found[0]}")
    else:
        print(f"ambiguous {','.join(found)}")
    return 0
