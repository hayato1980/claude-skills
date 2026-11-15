"""bundles: list_sessions の結果ファイルの読み取りと束ね。"""

from __future__ import annotations

import sys

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

import json
from typing import Any

import pytest

from session_closeout.bundles import ARCHIVED, group, next_after_id, parse_page, repo_from_remote_url

REPO = "acme/widgets"


def _row(
    sid: str,
    *,
    tags: list[str],
    status: str = "SESSION_STATUS_IDLE",
    revision: str | None = None,
    url: str = "https://github.com/acme/widgets",
) -> dict[str, Any]:
    repo: dict[str, Any] = {"url": url}
    if revision is not None:
        repo["revision"] = revision
    return {
        "id": sid,
        "session_status": status,
        "status_bucket": "SESSION_STATUS_BUCKET_COMPLETED",
        "tags": tags,
        "title": sid,
        "session_context": {"sources": [{"git_repository": repo}]},
    }


def _page_json(rows: list[dict[str, Any]], *, has_more: bool = False) -> str:
    return json.dumps({"ccr": {"data": rows, "has_more": has_more, "last_id": rows[-1]["id"] if rows else None}})


def _saved_file(rows: list[dict[str, Any]], *, has_more: bool = False) -> str:
    # 保存された結果ファイルは 4 行で、3 行目だけが JSON（前後はラッパー）。
    return "<other-session nonce=x>\nnote\n" + _page_json(rows, has_more=has_more) + "\n</other-session>\n"


class TestParsePage:
    def test_saved_file_with_wrapper_lines(self) -> None:
        page = parse_page(_saved_file([_row("s1", tags=["issue-1"])], has_more=True))
        assert [s.id for s in page.sessions] == ["s1"]
        assert page.has_more is True
        assert page.last_id == "s1"

    def test_plain_json(self) -> None:
        assert [s.id for s in parse_page(_page_json([_row("s1", tags=[])])).sessions] == ["s1"]

    def test_unreadable_text_names_the_problem(self) -> None:
        with pytest.raises(ValueError, match="list_sessions の結果として読めない"):
            parse_page("not json")

    def test_revision_missing_is_none(self) -> None:
        assert parse_page(_page_json([_row("s1", tags=[])])).sessions[0].revision is None


class TestGroup:
    def test_drops_archived_and_counts_them(self) -> None:
        page = parse_page(_page_json([_row("a", tags=["issue-1"], status=ARCHIVED), _row("b", tags=["issue-1"])]))
        g = group([page], self_id=None, issues=None, repo=REPO)
        assert [s.id for s in g.bundles[1]] == ["b"]
        assert g.archived == 1

    def test_excludes_self_with_reason(self) -> None:
        g = group([parse_page(_page_json([_row("me", tags=["issue-1"])]))], self_id="me", issues=None, repo=REPO)
        assert g.bundles == {}
        assert [(s.id, r) for s, r in g.excluded] == [("me", "自分自身")]

    def test_session_without_issue_tag_is_excluded(self) -> None:
        g = group([parse_page(_page_json([_row("x", tags=["tdd", "issue-x"])]))], self_id=None, issues=None, repo=REPO)
        assert g.bundles == {}
        assert "issue-<番号> タグが無い" in g.excluded[0][1]

    def test_other_repo_session_is_excluded_even_with_issue_tag(self) -> None:
        other = _row("x", tags=["issue-815"], url="https://github.com/hayato1980/keibaai_cloud")
        g = group([parse_page(_page_json([other, _row("b", tags=["issue-815"])]))], self_id=None, issues=None, repo=REPO)
        assert [s.id for s in g.bundles[815]] == ["b"]
        assert [(s.id, reason) for s, reason in g.excluded] == [
            ("x", "別リポ（https://github.com/hayato1980/keibaai_cloud）のセッション")
        ]

    def test_repo_url_with_git_suffix_or_slash_is_still_this_repo(self) -> None:
        rows = [
            _row("a", tags=["issue-1"], url="https://github.com/acme/widgets.git"),
            _row("b", tags=["issue-1"], url="https://github.com/acme/widgets/"),
        ]
        g = group([parse_page(_page_json(rows))], self_id=None, issues=None, repo=REPO)
        assert [s.id for s in g.bundles[1]] == ["a", "b"]

    def test_session_without_source_is_excluded_with_its_own_reason(self) -> None:
        row = {**_row("x", tags=["issue-1"]), "session_context": {"sources": []}}
        g = group([parse_page(_page_json([row]))], self_id=None, issues=None, repo=REPO)
        assert g.bundles == {}
        assert [(s.id, r) for s, r in g.excluded] == [("x", "source のリポジトリが無い")]

    def test_untagged_session_without_source_keeps_the_tag_reason(self) -> None:
        row = {**_row("x", tags=[]), "session_context": {"sources": []}}
        g = group([parse_page(_page_json([row]))], self_id=None, issues=None, repo=REPO)
        assert [r for _, r in g.excluded] == ["issue-<番号> タグが無い（手で開いたセッション）"]

    def test_implementation_and_review_share_one_bundle(self) -> None:
        rows = [_row("impl", tags=["issue-7"]), _row("rev", tags=["issue-7"], revision="claude/issue-7")]
        g = group([parse_page(_page_json(rows))], self_id=None, issues=None, repo=REPO)
        assert [(s.id, s.role(7)) for s in g.bundles[7]] == [("impl", "修正側"), ("rev", "レビュー側")]

    def test_role_uses_revision_not_flow_tag(self) -> None:
        # 領域タグが偶然 review-dialogue でも、revision が無ければ修正側（runbook「相手を引く」の #947 実測）。
        g = group([parse_page(_page_json([_row("impl", tags=["review-dialogue", "issue-9"])]))], None, None, REPO)
        assert g.bundles[9][0].role(9) == "修正側"

    def test_issue_filter(self) -> None:
        rows = [_row("a", tags=["issue-1"]), _row("b", tags=["issue-2"])]
        g = group([parse_page(_page_json(rows))], self_id=None, issues={2}, repo=REPO)
        assert list(g.bundles) == [2]
        assert g.excluded[0][1] == "引数で指定した issue ではない"

    def test_same_session_on_two_pages_counted_once(self) -> None:
        p = parse_page(_page_json([_row("a", tags=["issue-1"])]))
        assert len(group([p, p], self_id=None, issues=None, repo=REPO).bundles[1]) == 1


class TestStatusBucket:
    def test_missing_bucket_on_live_session_fails_loud_with_id(self) -> None:
        row = _row("s9", tags=["issue-1"])
        del row["status_bucket"]
        with pytest.raises(ValueError, match="s9 の status_bucket が想定外: None"):
            parse_page(_page_json([row]))

    def test_unknown_bucket_fails_loud(self) -> None:
        row = _row("s9", tags=["issue-1"])
        row["status_bucket"] = "SESSION_STATUS_BUCKET_SOMETHING_NEW"
        with pytest.raises(ValueError, match="SOMETHING_NEW"):
            parse_page(_page_json([row]))

    def test_archived_session_bucket_is_not_checked(self) -> None:
        row = _row("old", tags=[], status=ARCHIVED)
        del row["status_bucket"]
        assert parse_page(_page_json([row])).sessions[0].id == "old"


class TestNextAfterId:
    def test_complete_when_last_page_has_no_more(self) -> None:
        pages = [parse_page(_page_json([_row("a", tags=[])], has_more=True)),
                 parse_page(_page_json([_row("b", tags=[])]))]
        assert next_after_id(pages) is None

    def test_points_after_last_page_given(self) -> None:
        pages = [parse_page(_page_json([_row("a", tags=[])], has_more=True)),
                 parse_page(_page_json([_row("b", tags=[])], has_more=True))]
        assert next_after_id(pages) == "b"

    def test_final_page_not_at_end_is_an_order_error(self) -> None:
        pages = [parse_page(_page_json([_row("b", tags=[])])),
                 parse_page(_page_json([_row("a", tags=[])], has_more=True))]
        with pytest.raises(ValueError, match="1 枚目が最終ページ"):
            next_after_id(pages)


class TestRepoScope:
    def test_other_repo_with_same_issue_tag_is_not_bundled(self) -> None:
        other = _row("a", tags=["issue-3"], url="https://github.com/acme/other")
        g = group([parse_page(_page_json([other]))], None, None, "acme/widgets")
        assert g.bundles == {}
        assert g.excluded[0][1] == "別リポ（https://github.com/acme/other）のセッション"

    def test_repo_match_ignores_case_and_git_suffix(self) -> None:
        row = _row("a", tags=["issue-3"], url="https://github.com/Acme/Widgets.git")
        g = group([parse_page(_page_json([row]))], None, None, "acme/widgets")
        assert list(g.bundles) == [3]


class TestRepoFromRemoteUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/acme/widgets",
            "https://github.com/acme/widgets.git",
            "git@github.com:acme/widgets.git",
            "http://local_proxy@127.0.0.1:34567/git/acme/widgets",
        ],
    )
    def test_extracts_owner_and_name(self, url: str) -> None:
        assert repo_from_remote_url(url) == "acme/widgets"

    def test_unreadable_url_names_the_url(self) -> None:
        with pytest.raises(ValueError, match="widgets-only"):
            repo_from_remote_url("widgets-only")
