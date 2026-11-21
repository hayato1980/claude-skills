#!/bin/bash
#
# PostToolUse hook (matcher: mcp__github__create_pull_request):
# 最初の prompt が `/<プラグイン>:<フロー語> #NNN` のセッションに、PR 作成直後のレビュー払い出しを思い出させる。
#
# 背景: 手順は create-ccw-session スキル本文にあるが、子はこのスキルを発動しない。PR 作成直後は
# ハーネスの「subscribe してターンを終える」が勝ち、レビューが払い出されないまま止まっていた。
# モデルが文書を読むかどうかに依存しないよう、PR 作成のタイミングで additionalContext を差し込む。
#
# 判定: transcript の先頭のユーザー prompt が `/<プラグイン>:<フロー語> #NNN` のときだけ反応する。
# フロー語は問わない（tdd / diagnosing-bugs / grill-with-docs ...）—— この hook は PR を作った時点でしか
# 動かないので、「PR を作るとは限らない」フローも PR を作ったならレビューを通す。
# 除外は `dev-workflow:*`（review-dialogue / create-ccw-session / session-closeout 等の器）だけ。
# review-dialogue の子が払い出し直すと相手が 2 件になり往復が壊れる。
# 払い出された子かどうかは見ない（hook から区別できる手掛かりが無い）。オーナーが直接セッションで
# 最初にフローを打った場合も同じく反応し、それを正とする。最初の prompt がフロー起動でない
# セッション（ふつうの直接作業）では何も出さない。
# jq 不在は黙って成功にしない: stderr に出して exit 1（non-blocking）。黙ると、この hook が
# 防ぎたい「レビューが払い出されないまま止まる」がそのまま起きる。
# transcript が読めないときは判定対象外として何も出さず exit 0。
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "pr-review-dispatch: jq が見つからないため判定できません。フロー起動で始まったセッションなら、create-ccw-session スキルの「PR 作成後の自動レビュー払い出し」を手で実行してください。" >&2
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

# 生の `/<plugin>:<flow> #NNN`（先頭アンカー。文中の言及は拾わない）か、
# コマンド展開形 `<command-name>/<plugin>:<flow></command-name> ... <command-args>#NNN</command-args>`。
name_re='[A-Za-z0-9_-]+:[A-Za-z0-9_-]+'
flow="" issue=""
if [[ "$first_prompt" =~ ^[[:space:]]*/($name_re)[[:space:]]+#?([0-9]+) ]]; then
  flow="${BASH_REMATCH[1]}" issue="${BASH_REMATCH[2]}"
elif [[ "$first_prompt" =~ ^[[:space:]]*\<command-message\>[^\<]*\</command-message\>[[:space:]]*\<command-name\>/($name_re)\</command-name\> ]]; then
  flow="${BASH_REMATCH[1]}"
  [[ "$first_prompt" =~ \<command-args\>[[:space:]]*#?([0-9]+) ]] && issue="${BASH_REMATCH[1]}"
fi
[ -n "$issue" ] || exit 0
[[ "$flow" == dev-workflow:* ]] && exit 0

msg="あなたは /${flow} で始まった実装セッションで、いま draft PR を作成した。subscribe してターンを終える前に、"
msg+="オーナーの指示を待たず、create-ccw-session スキル（dev-workflow）の「PR 作成後の自動レビュー払い出し」を"
msg+="今すぐ実行せよ（対象 issue: #${issue}、ブランチ claude/issue-${issue}）。"
msg+="list_sessions(mine=true, limit=100) で既存の review-dialogue セッションが無いことを revision で確認し、無ければ create_session を 1 回呼ぶ。"
msg+="その後 review-dialogue スキルの runbook「修正側の手順」に合流する。自分で /code-review は回さない。"

jq -n --arg ctx "$msg" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
