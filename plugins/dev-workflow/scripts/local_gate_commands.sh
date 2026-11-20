#!/usr/bin/env bash
# 各リポの docs/agents/pr-merge-gate.md から「ready 前に実行するコマンド」を 1 行 1 コマンドで出す。
#
# 契約: 見出し `## ready 前に実行するコマンド` の下の箇条書き ``- `コマンド` ``。次の `## ` で終わる。
# - 見出しが無い: 何も出さず 0 で終わる（設定の無いリポは従来どおり何もしない）。
# - 見出しはあるのに箇条書きが空: 非ゼロ（書き損じを黙って素通りさせない。blocking_jobs.sh と同じ考え方）。
#
# 使い方: local_gate_commands.sh <pr-merge-gate.md>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <pr-merge-gate.md>" >&2
  exit 3
fi
doc="$1"
if [ ! -f "$doc" ]; then
  echo "設定ファイルがありません: ${doc}" >&2
  exit 1
fi

readonly HEADING="## ready 前に実行するコマンド"

if ! grep -qxF -- "$HEADING" "$doc"; then
  exit 0
fi

commands_found="$(awk -v heading="$HEADING" '
  /^## / { in_section = ($0 == heading); next }
  in_section && match($0, /^- `[^`]+`/) {
    print substr($0, RSTART + 3, RLENGTH - 4)
  }
' "$doc")"

if [ -z "$commands_found" ]; then
  echo "${doc} に『${HEADING}』の見出しはありますが、箇条書き（- \`コマンド\`）がありません" >&2
  exit 1
fi
printf '%s\n' "$commands_found"
