#!/usr/bin/env bash
# 各リポの docs/agents/pr-merge-gate.md から「ready 前に実行するコマンド」を 1 行 1 コマンドで出す。
#
# 契約: 見出し `## ready 前に実行するコマンド` の下の箇条書き ``- `コマンド` ``。次の `## ` で終わる。
# - 見出しが無い: 何も出さず 0 で終わる（設定の無いリポは従来どおり何もしない）。
# - 見出しはあるのに箇条書きが空: 非ゼロ（書き損じを黙って素通りさせない。blocking_jobs.sh と同じ考え方）。
# 節の読み取り規則は section_bullets.sh と共有（blocking_jobs.sh と同じ規則）。
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

readonly HEADING="ready 前に実行するコマンド"
SCRIPT_DIR="$(CDPATH='' \command cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set +e
commands_found="$(bash "${SCRIPT_DIR}/section_bullets.sh" "$doc" "$HEADING")"
reader_exit=$?
set -e

case "$reader_exit" in
  0) ;;
  4) exit 0 ;; # 見出しが無い = 設定の無いリポ。何もしない
  *) exit 1 ;;
esac

if [ -z "$commands_found" ]; then
  echo "${doc} に『## ${HEADING}』の見出しはありますが、箇条書き（- \`コマンド\`）がありません" >&2
  exit 1
fi
printf '%s\n' "$commands_found"
