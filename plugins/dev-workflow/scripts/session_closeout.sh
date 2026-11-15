#!/usr/bin/env bash
# session-closeout の機械的な部分（束ね・判定）の入口。直接ではなく、各リポの中継
# （templates/session_closeout.sh → scripts/ci/session_closeout.sh）から呼ばれる。
# 対象リポ: 環境変数 SESSION_CLOSEOUT_REPO_ROOT（中継が渡す）、無ければカレントの git 作業ツリー。
# 使い方: session_closeout.sh <list_sessions の結果ファイル（取得順）>... [--issue N ...] [--repo owner/repo]
set -euo pipefail

here="$(CDPATH='' \command cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 が見つかりません。session-closeout の判定を実行できないため中断します。" >&2
  exit 1
fi
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m session_closeout "$@"
