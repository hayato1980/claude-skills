#!/bin/bash
#
# PostToolUse hook (matcher: Skill):
# 払い出された修正側が `mattpocock-skills:tdd` を発動したとき、上流の「シームをユーザーと合意する」を
# 置き換える手順（create-ccw-session の「払い出された tdd のシーム」）を思い出させる。
#
# 背景（判断 0009）: 払い出された修正側の会話にはオーナーがいない。合意を求めて止まる・根拠が会話にしか
# 残らない・レビュー基準に反するシームを選ぶ、が起きていた。修正側は create-ccw-session を発動しないので、
# 文書に書くだけでは届かない。tdd を発動した時点で additionalContext を差し込む。
#
# 判定:
#   - `tool_input.skill` が `mattpocock-skills:tdd`（先頭の `/` は許す）のときだけ。
#   - 現在のブランチが `claude/issue-<N>`（対象ブランチ）のときだけ。prompt では判定しない（#35）。
#     ブランチは入力の `cwd`（無ければ CLAUDE_PROJECT_DIR、さらに無ければ $PWD）で git に聞く。
#     直接作業のセッションはブランチ名が乱数なので反応しない（上流どおりオーナーと合意する）。
# 手順の本文は SKILL.md の 1 か所にだけあり（判断 0009）、ここには写さない。差し込むのは、上流の合意手順を
# 置き換えることと、読む先（節と standards.md の絶対パス）だけ。
# 上流 tdd の本文とこの差し込みのどちらが先に読まれるかは文書化されていないので、文面はどちらの順でも
# 上流の合意手順を置き換えるように書く。
# jq 不在は黙って成功にしない: stderr に出して exit 1（non-blocking）。入力が読めない・判定対象外は exit 0。
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "tdd-seam-policy: jq が見つからないため判定できません。claude/issue-<N> で tdd を実行しているなら、create-ccw-session スキルの「払い出された tdd のシーム」を読んでください。" >&2
  exit 1
fi

input="$(cat)"
skill="$(printf '%s' "$input" | jq -r '.tool_input.skill? // empty' 2>/dev/null)"
skill="${skill#/}"
[ "$skill" = "mattpocock-skills:tdd" ] || exit 0

dir="$(printf '%s' "$input" | jq -r '.cwd? // empty' 2>/dev/null)"
dir="${dir:-${CLAUDE_PROJECT_DIR:-$PWD}}"
branch="$(git -C "$dir" symbolic-ref --short -q HEAD 2>/dev/null || true)"
[[ "$branch" =~ ^claude/issue-([0-9]+)$ ]] || exit 0
issue="${BASH_REMATCH[1]}"

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
section="${root}/skills/create-ccw-session/SKILL.md"
standards="${root}/skills/review-dialogue/standards.md"

msg="あなたは claude/issue-${issue} で mattpocock-skills:tdd を実行する、払い出された修正側である。会話にオーナーはいない。"
msg+="上流 tdd の「シームを書き出してユーザーと合意する」は、この指示で置き換える（上流の本文がこの後に読まれても同じ）。"
msg+="AskUserQuestion を出さない。返事を待たない。"
msg+="最初のテストを書く前に ${section} の「払い出された tdd のシーム」を読み、その手順に従う。"
msg+="Standards の基準文書 standards.md は ${standards} にある。"

jq -n --arg ctx "$msg" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
