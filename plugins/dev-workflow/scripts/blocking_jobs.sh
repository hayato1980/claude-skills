#!/usr/bin/env bash
# 各リポの docs/agents/pr-merge-gate.md から「CI で止めるジョブ」の名前を 1 行 1 個で出す。
#
# 契約: 見出し `## CI で止めるジョブ` の下の箇条書き ``- `名前` ``。次の `## ` で終わる。
# 見つからない／空のときは、黙って「ジョブ 0 個 = 常に OK」にならないよう非ゼロで終わる。
#
# 使い方: blocking_jobs.sh <pr-merge-gate.md>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <pr-merge-gate.md>" >&2
  exit 3
fi
doc="$1"
if [ ! -f "$doc" ]; then
  echo "設定ファイルがありません: ${doc}（見出し『## CI で止めるジョブ』に CI で止めるジョブ名を書いてください）" >&2
  exit 1
fi

jobs_found="$(awk '
  /^## / { in_section = ($0 == "## CI で止めるジョブ"); next }
  in_section && match($0, /^- `[^`]+`/) {
    name = substr($0, RSTART + 3, RLENGTH - 4)
    print name
  }
' "$doc")"

if [ -z "$jobs_found" ]; then
  echo "${doc} に『## CI で止めるジョブ』の箇条書き（- \`ジョブ名\`）がありません" >&2
  exit 1
fi
printf '%s\n' "$jobs_found"
