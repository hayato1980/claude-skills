#!/usr/bin/env bash
# 各リポの docs/agents/*.md の「## 見出し」の下の箇条書き ``- `x` `` を、x だけ 1 行 1 個で出す。
# 次の `## ` で終わる。blocking_jobs.sh と local_gate_commands.sh が共有する読み取り規則の実体
# （片方だけ直して食い違わないよう、ここ 1 か所に持つ）。
#
# 終了コード: 0 = 見出しがあった（箇条書きが 0 個でもよい。呼び出し側が空をどう扱うか決める）
#            1 = ファイルが無い / 4 = 見出しが無い / 3 = 用法エラー
#
# 使い方: section_bullets.sh <doc.md> <見出し（'## ' を除いたもの）>
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <doc.md> <heading>" >&2
  exit 3
fi
doc="$1"
heading="$2"
if [ ! -f "$doc" ]; then
  echo "設定ファイルがありません: ${doc}" >&2
  exit 1
fi

awk -v heading="## ${heading}" '
  /^## / { in_section = ($0 == heading); found = found || in_section; next }
  in_section && match($0, /^- `[^`]+`/) {
    print substr($0, RSTART + 3, RLENGTH - 4)
  }
  END { exit found ? 0 : 4 }
' "$doc"
