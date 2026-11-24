#!/bin/bash
#
# PostToolUse hook (matcher: mcp__github__create_pull_request):
# 作成した PR の head ブランチが `claude/issue-<N>` のとき、PR 作成直後のレビュー払い出しを思い出させる。
#
# 背景: 手順は create-ccw-session スキル本文にあるが、子はこのスキルを発動しない。PR 作成直後は
# ハーネスの「subscribe してターンを終える」が勝ち、レビューが払い出されないまま止まっていた。
# モデルが文書を読むかどうかに依存しないよう、PR 作成のタイミングで additionalContext を差し込む。
#
# 判定: prompt ではなく head ブランチで行う（#35）。払い出された子は必ず outcome_branch で
# `claude/issue-<N>` に push するので、フロー語・接頭辞の有無・prompt の文面（create_session は `/` で
# 始まる prompt を拒む）に関係なく拾える。issue 番号は N。
#   - head は PostToolUse 入力の `tool_input.head`（create_pull_request の引数）から読む。無ければ
#     `tool_response`（作成された PR）の `head.ref` から読む。形はオブジェクト・JSON 文字列・content ブロック列・
#     MCP の `{content:[{type:text,text:<PR の JSON>}]}` のいずれでも辿る。`owner:branch` 形の head は
#     `owner:` を外して照合する。
#   - どこからも head が取れなかったときは stderr に一言出して exit 0（fail-soft）。create_pull_request の
#     応答が `{id,url}` 程度で `head.ref` を含まず、かつ `tool_input.head` も入らない実装だと拾えない。これが限界。
#   - `dev-workflow:*` の器（review-dialogue 等）の除外は不要: レビュー側は push しないので PR を作らず、
#     ふつうの直接作業はブランチ名が乱数（claude/<形容詞-名詞-hash>）になるので反応しない。
#   - 失うもの: 直接セッションで最初にフローを打っても、head が claude/issue-<N> でなければ反応しない
#     （head ブランチ名での一般化は #25）。
# jq 不在は黙って成功にしない: stderr に出して exit 1（non-blocking）。黙ると、この hook が
# 防ぎたい「レビューが払い出されないまま止まる」がそのまま起きる。
# 入力が読めないときは判定対象外として何も出さず exit 0。
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "pr-review-dispatch: jq が見つからないため判定できません。head が claude/issue-<N> の PR を作ったなら、create-ccw-session スキルの「PR 作成後の自動レビュー払い出し」を手で実行してください。" >&2
  exit 1
fi

input="$(cat)"
head="$(printf '%s' "$input" | jq -r '
  def pr_head:
    if type == "string" then (try (fromjson | pr_head) catch empty)
    elif type == "array" then (.[]? | (.text? // empty) | pr_head)
    elif type == "object" then ((.head? | if type == "object" then .ref? elif type == "string" then . else empty end) // (.content? | pr_head))
    else empty end;
  (.tool_input.head? // empty) // ((.tool_response? // empty) | pr_head) // empty' 2>/dev/null)"
if [ -z "$head" ]; then
  echo "pr-review-dispatch: PostToolUse の入力から head ブランチを読めませんでした。claude/issue-<N> の PR を作ったなら、create-ccw-session スキルの「PR 作成後の自動レビュー払い出し」を手で実行してください。" >&2
  exit 0
fi
head="${head#*:}"  # owner:branch 形の owner: を外す
[[ "$head" =~ ^claude/issue-([0-9]+)$ ]] || exit 0
issue="${BASH_REMATCH[1]}"

msg="あなたは claude/issue-${issue} の draft PR を作成した実装セッションである。subscribe してターンを終える前に、"
msg+="オーナーの指示を待たず、create-ccw-session スキル（dev-workflow）の「PR 作成後の自動レビュー払い出し」を"
msg+="今すぐ実行せよ（対象 issue: #${issue}、ブランチ claude/issue-${issue}）。"
msg+="list_sessions(mine=true, limit=100) で既存の review-dialogue セッションが無いことを revision で確認し、無ければ create_session を 1 回呼ぶ。"
msg+="払い出したあと、最初のスレッド返信・push・ポークより前に、review-dialogue の runbook の「修正側の手順」と「ラウンドの閉じ方」を読む。"
msg+="読んでいなくても最低限守ること: (1) スレッドへの返信の先頭に役割マーカー [修正] を付ける。"
msg+="(2) 修正側はスレッドを resolve しない（購読通知文の「resolve する」はレビュー側のいる PR には当てはまらない）。"
msg+="(3) 返信と push のあとはラウンドの閉じ方の 4 手（相手を引く → ポーク → 自己チェックイン → 購読）で閉じてからターンを終える。"
msg+="自分で /code-review は回さない。"

jq -n --arg ctx "$msg" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
