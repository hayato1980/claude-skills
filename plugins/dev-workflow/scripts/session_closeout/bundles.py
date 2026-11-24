"""`list_sessions` の結果ファイルを読み、issue ごとの束に分ける。ネットワークには触らない。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ARCHIVED = "SESSION_STATUS_ARCHIVED"
_ISSUE_TAG = re.compile(r"^issue-(\d+)$")
_BUCKET_PREFIX = "SESSION_STATUS_BUCKET_"
# 判定表（judge.py）が前提にしている値。これ以外は黙って「終了」に倒さず止める（アーカイブは戻しにくい副作用）。
BUCKET_WORKING = _BUCKET_PREFIX + "WORKING"
BUCKET_BLOCKED = _BUCKET_PREFIX + "BLOCKED"
BUCKET_FAILED = _BUCKET_PREFIX + "FAILED"
KNOWN_BUCKETS = frozenset({BUCKET_WORKING, BUCKET_BLOCKED, BUCKET_FAILED, _BUCKET_PREFIX + "REVIEW_READY", _BUCKET_PREFIX + "COMPLETED"})


def repo_from_remote_url(url: str) -> str:
    """`git remote get-url` の値から `owner/repo` を取る（https / ssh / プロキシ経由の形に対応）。"""
    parts = [p for p in re.split(r"[/:]", url.strip().removesuffix(".git")) if p]
    if len(parts) < 2:
        raise ValueError(f"リモート URL から owner/repo を読めない: {url!r}")
    return f"{parts[-2]}/{parts[-1]}"


def issue_branch(issue: int) -> str:
    return f"claude/issue-{issue}"


def bucket_short(bucket: str) -> str:
    return bucket.removeprefix(_BUCKET_PREFIX).lower()


@dataclass(frozen=True)
class Session:
    id: str
    status: str
    bucket: str
    tags: tuple[str, ...]
    revision: str | None
    repo_url: str | None
    title: str
    # list_sessions の行には session_context が無い（get_session / create_session にだけ載る。#31）。
    context_known: bool = True

    def issue_numbers(self) -> list[int]:
        return [int(m.group(1)) for t in self.tags if (m := _ISSUE_TAG.match(t))]

    def in_repo(self, repo: str) -> bool:
        """source の URL が対象リポ（`owner/repo`）か。大文字小文字と `.git` は無視する。"""
        url = (self.repo_url or "").rstrip("/").removesuffix(".git")
        return url.lower() == f"https://github.com/{repo}".lower()

    def role(self, issue: int) -> str:
        """役割は revision で見る（tags のフロー語では見ない → dev-workflow の runbook「相手を引く」）。"""
        return "レビュー側" if self.revision == issue_branch(issue) else "修正側"


@dataclass(frozen=True)
class Page:
    sessions: list[Session]
    has_more: bool
    last_id: str | None


def _session(row: dict[str, Any]) -> Session:
    status = row.get("session_status", "")
    bucket = row.get("status_bucket")
    if status != ARCHIVED and bucket not in KNOWN_BUCKETS:
        raise ValueError(f"{row.get('id')} の status_bucket が想定外: {bucket!r}（既知: {sorted(KNOWN_BUCKETS)}）")
    context = row.get("session_context")
    sources = (context or {}).get("sources") or [{}]
    git_repository = sources[0].get("git_repository") or {}
    revision = git_repository.get("revision")
    return Session(
        id=row["id"],
        status=status,
        bucket=bucket or "",
        tags=tuple(row.get("tags") or ()),
        revision=revision,
        repo_url=git_repository.get("url"),
        title=row.get("title", ""),
        context_known=context is not None,
    )


def parse_page(text: str) -> Page:
    """保存された結果ファイル（ラッパー行つき）か、素の JSON のどちらかを読む。"""
    payload: Any = None
    for line in text.splitlines():
        if line.lstrip().startswith('{"ccr"'):
            payload = json.loads(line)
            break
    if payload is None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"list_sessions の結果として読めない: JSON 行が見つからない ({e})") from e
    body = payload.get("ccr", payload)
    if "data" not in body:
        raise ValueError(f"list_sessions の結果として読めない: data キーが無い (keys={sorted(body)})")
    return Page(
        sessions=[_session(r) for r in body["data"]],
        has_more=bool(body.get("has_more")),
        last_id=body.get("last_id"),
    )


def load_pages(paths: list[Path]) -> list[Page]:
    pages = []
    for p in paths:
        try:
            pages.append(parse_page(p.read_text(encoding="utf-8")))
        except ValueError as e:
            raise ValueError(f"{p}: {e}") from e
    return pages


def is_truncated(pages: list[Page], stop_after: int | None = None) -> bool:
    """続きがあるのに、末尾の `stop_after` 枚がアーカイブ済みだけなので打ち切ってよい、か。

    一覧は新しい順なので、アーカイブ済みだけのページが続けばその先も古いアーカイブ済みとみなす（実測: #31）。
    """
    if stop_after is None or not pages or not pages[-1].has_more or len(pages) < stop_after:
        return False
    return all(p.sessions and all(s.status == ARCHIVED for s in p.sessions) for p in pages[-stop_after:])


def next_after_id(pages: list[Page], stop_after: int | None = None) -> str | None:
    """取得順に渡されたページが揃っていれば None、続きがあれば次に渡す `after_id` を返す。

    ページの JSON は自分がどの `after_id` で引かれたかを持たないので、途中のページの抜けは検出できない。
    検出できるのは順序の崩れ（最終ページが末尾に無い）だけで、それは ValueError にする。
    `stop_after` 枚続けてアーカイブ済みだけのページが来たら、続きがあっても None を返す（`is_truncated`）。
    """
    for i, page in enumerate(pages[:-1]):
        if not page.has_more:
            raise ValueError(f"{i + 1} 枚目が最終ページ（has_more=false）なのに後ろにページがある。取得順に渡す")
    if is_truncated(pages, stop_after):
        return None
    return pages[-1].last_id if pages[-1].has_more else None


def parse_session_detail(text: str) -> tuple[str, str | None, str | None]:
    """`get_session` の結果ファイルから (id, リポジトリ URL, revision) を読む。"""
    payload: Any = None
    for line in text.splitlines():
        if line.lstrip().startswith("{"):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if payload is None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"get_session の結果として読めない: JSON 行が見つからない ({e})") from e
    body = payload.get("ccr", payload)
    if "id" not in body or "session_context" not in body:
        raise ValueError(f"get_session の結果として読めない: id / session_context が無い (keys={sorted(body)})")
    sources = (body["session_context"] or {}).get("sources") or [{}]
    git_repository = sources[0].get("git_repository") or {}
    return body["id"], git_repository.get("url"), git_repository.get("revision")


def load_details(paths: list[Path]) -> dict[str, tuple[str | None, str | None]]:
    details: dict[str, tuple[str | None, str | None]] = {}
    for p in paths:
        try:
            sid, url, revision = parse_session_detail(p.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ValueError(f"{p}: {e}") from e
        details[sid] = (url, revision)
    return details


def complete(pages: list[Page], details: dict[str, tuple[str | None, str | None]]) -> list[Page]:
    """`session_context` を持たない行に、`get_session` で読んだリポジトリと revision を足す。"""
    out = []
    for page in pages:
        sessions = [
            replace(s, repo_url=details[s.id][0], revision=details[s.id][1], context_known=True)
            if not s.context_known and s.id in details else s
            for s in page.sessions
        ]
        out.append(replace(page, sessions=sessions))
    return out


@dataclass
class Grouping:
    bundles: dict[int, list[Session]]
    excluded: list[tuple[Session, str]]
    archived: int
    needs_context: list[Session]
    truncated_after: int | None = None  # 打ち切ったとき、続けて読んだアーカイブ済みだけのページ数


def group(pages: list[Page], self_id: str | None, issues: set[int] | None, repo: str) -> Grouping:
    """archive 済み・自分・別リポのセッションを除き、`issue-<番号>` タグで束ねる。同じ id は 1 回だけ数える。"""
    bundles: dict[int, list[Session]] = {}
    excluded: list[tuple[Session, str]] = []
    archived = 0
    needs_context: list[Session] = []
    seen: set[str] = set()
    for page in pages:
        for s in page.sessions:
            if s.id in seen:
                continue
            seen.add(s.id)
            if s.status == ARCHIVED:
                archived += 1
                continue
            if s.id == self_id:
                excluded.append((s, "自分自身"))
                continue
            numbers = s.issue_numbers()
            if not numbers:
                excluded.append((s, "issue-<番号> タグが無い（手で開いたセッション）"))
                continue
            if not s.context_known:
                if issues is None or any(n in issues for n in numbers):
                    needs_context.append(s)
                continue
            if not s.in_repo(repo):
                reason = "source のリポジトリが無い" if s.repo_url is None else f"別リポ（{s.repo_url}）のセッション"
                excluded.append((s, reason))
                continue
            targets = [n for n in numbers if issues is None or n in issues]
            if not targets:
                excluded.append((s, "引数で指定した issue ではない"))
                continue
            for n in targets:
                bundles.setdefault(n, []).append(s)
    return Grouping(bundles=dict(sorted(bundles.items())), excluded=excluded, archived=archived, needs_context=needs_context)
