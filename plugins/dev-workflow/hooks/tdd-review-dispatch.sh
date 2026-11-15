#!/bin/bash
#
# PostToolUse hook (matcher: mcp__github__create_pull_request):
# 最初の prompt が `/mattpocock-skills:tdd #NNN` のセッションに、PR 作成直後のレビュー払い出しを思い出させる。
#
# 背景: 手順は create-ccw-session スキル本文にあるが、子はこのスキルを発動しない。PR 作成直後は
# ハーネスの「subscribe してターンを終える」が勝ち、レビューが払い出されないまま止まっていた。
# モデルが文書を読むかどうかに依存しないよう、PR 作成のタイミングで additionalContext を差し込む。
#
# 判定: transcript の先頭のユーザー prompt が `/mattpocock-skills:tdd #NNN` のときだけ反応する。
# 払い出された子かどうかは見ない（hook から区別できる手掛かりが無い）。オーナーが直接セッションで
# 最初に tdd を打った場合も同じく反応し、それを正とする —— tdd フローの差分はどこで回しても
# 別セッションのレビューを通す。最初の prompt が tdd 以外のセッション（ふつうの直接作業・
# review-dialogue の子）では何も出さない。
# jq 不在は黙って成功にしない: stderr に出して exit 1（non-blocking）。黙ると、この hook が
# 防ぎたい「レビューが払い出されないまま止まる」がそのまま起きる。
# transcript が読めないときは判定対象外として何も出さず exit 0。
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "tdd-review-dispatch: jq が見つからないため判定できません。tdd で始まったセッションなら、create-ccw-session スキルの「tdd の自動レビュー払い出し」を手で実行してください。" >&2
  exit 1
fi

input="$(cat)"
transcript="$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null)"
{ [ -n "$transcript" ] && [ -r "$transcript" ]; } || exit 0

# 先頭のユーザー entry（isMeta の hook 出力・スキル本文は除く）の本文（文字列 or text ブロック列）。
first_prompt="$(jq -rs '
  [ .[] | select(.type == "user" and (.isMeta != true)) | .message.content
    | if type == "string" then . else ([.[]? | select(.type == "text") | .text] | join("\n")) end
  ] | .[0] // empty' "$transcript" 2>/dev/null)"
[ -n "$first_prompt" ] || exit 0

# 生の `/mattpocock-skills:tdd #NNN`（先頭アンカー。文中の言及は拾わない）か、
# コマンド展開形 `<command-name>/mattpocock-skills:tdd</command-name> ... <command-args>#NNN</command-args>`。
issue=""
if [[ "$first_prompt" =~ ^[[:space:]]*/mattpocock-skills:tdd[[:space:]]+#?([0-9]+) ]]; then
  issue="${BASH_REMATCH[1]}"
elif [[ "$first_prompt" =~ ^[[:space:]]*\<command-message\>[^\<]*\</command-message\>[[:space:]]*\<command-name\>/mattpocock-skills:tdd\</command-name\> ]] \
  && [[ "$first_prompt" =~ \<command-args\>[[:space:]]*#?([0-9]+) ]]; then
  issue="${BASH_REMATCH[1]}"
fi
[ -n "$issue" ] || exit 0

msg="あなたは tdd で始まった実装セッションで、いま draft PR を作成した。subscribe してターンを終える前に、"
msg+="オーナーの指示を待たず、create-ccw-session スキル（dev-workflow）の「tdd の自動レビュー払い出し」を"
msg+="今すぐ実行せよ（対象 issue: #${issue}、ブランチ claude/issue-${issue}）。"
msg+="list_sessions(mine=true, limit=100) で既存の review-dialogue セッションが無いことを revision で確認し、無ければ create_session を 1 回呼ぶ。"
msg+="その後 review-dialogue スキルの runbook「修正側の手順」に合流する。自分で /code-review は回さない。"

jq -n --arg ctx "$msg" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
