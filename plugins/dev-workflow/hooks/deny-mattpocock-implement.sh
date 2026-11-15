#!/bin/bash
#
# UserPromptSubmit hook: `/mattpocock-skills:implement`（短縮形 `/implement`）の手動起動をブロックする。
#
# 効くのは、対象リポの docs/agents/dev-workflow.md が見出し `## /implement` の下で
# `止める: はい` と書いているときだけ。無い・`いいえ`・読めないときは何もしない
# （このフローを使わないリポに押し付けない）。
#
# 背景: `skillOverrides` はプラグイン由来スキルの解決経路では読まれず no-op だったため、
# 手動のスラッシュ起動は UserPromptSubmit hook でしか塞げない（実測）。
# モデルからの自動発火は上流 SKILL.md の `disable-model-invocation: true` で既に塞がっている。
#
# stdin: UserPromptSubmit hook の JSON ({"hook_event_name":"UserPromptSubmit","prompt":"...",...})。
# ブロックする場合は exit 2 + stderr メッセージ（stderr がブロック理由として表示される）。
set -euo pipefail

INPUT="$(cat)"
PROMPT="$(printf '%s' "${INPUT}" | jq -r '.prompt // empty' 2>/dev/null || true)"

# 壊れた入力・jq 不在は誤検知よりフェイルソフトを優先して素通しする。
if [ -z "${PROMPT}" ]; then
  exit 0
fi

# 判定対象: `/mattpocock-skills:implement` と短縮名 `/implement`。
#   - スラッシュコマンドはプロンプト先頭でしか解決しないため先頭にアンカーする
#     （文中の言及はブロックしない）。
#   - 先頭の空白は許容し、引数付きも検出する。大文字小文字は無視する。
#   - 直後は空白・改行・文字列終端のみ（`/mattpocock-skills:implement-spec` は巻き込まない）。
if ! printf '%s' "${PROMPT}" | grep -qiE '^[[:space:]]*/(mattpocock-skills:)?implement([[:space:]]|$)'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
CONFIG="${PROJECT_DIR}/docs/agents/dev-workflow.md"
[ -f "${CONFIG}" ] || exit 0

enabled="$(awk '
  /^## / { in_section = ($0 == "## /implement"); next }
  in_section && /^止める: / { sub(/^止める: */, ""); sub(/[[:space:]]+$/, ""); print; exit }
' "${CONFIG}")"
[ "${enabled}" = "はい" ] || exit 0

cat >&2 << 'EOF2'
`/mattpocock-skills:implement`（短縮形 `/implement` も）は、このリポジトリでは使用禁止です
（docs/agents/dev-workflow.md の「/implement」で止める設定になっています）。

代替: `/mattpocock-skills:tdd` で red-green-refactor を回し、最後に `/mattpocock-skills:code-review`
で締めてください。
EOF2
exit 2
