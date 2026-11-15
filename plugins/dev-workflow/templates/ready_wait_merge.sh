#!/usr/bin/env bash
# 共有プラグイン dev-workflow の ready_wait_merge.sh への中継。
#
# 本体のロジックはプラグイン側にある。このファイルは各リポの scripts/ci/ready_wait_merge.sh に
# そのまま置く。許可ルール `Bash(scripts/ci/ready_wait_merge.sh*)` が固定のパスを指す必要が
# あるため、中継を残している（先頭に bash を付けると auto mode で許可ルールが無効になる）。
#
# プラグイン本体の場所は ~/.claude/plugins/installed_plugins.json から探す。
# 使い方: scripts/ci/ready_wait_merge.sh [PR番号]
set -euo pipefail

readonly PLUGIN_KEY="dev-workflow@hayato"
REPO_ROOT="$(CDPATH='' \command cd -- "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly REPO_ROOT
readonly INSTALLED_JSON="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/plugins/installed_plugins.json"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq が見つかりません。プラグインの場所を解決できないため中断します。" >&2
  exit 1
fi
if [ ! -f "$INSTALLED_JSON" ]; then
  echo "${INSTALLED_JSON} がありません。プラグイン ${PLUGIN_KEY} が入っていません。" >&2
  echo "導入: claude plugin marketplace add hayato1980/claude-skills && claude plugin install ${PLUGIN_KEY}" >&2
  exit 1
fi

# このリポ向けの導入（project スコープ）を優先し、無ければ user スコープ、それも無ければ先頭。
plugin_root="$(jq -r --arg key "$PLUGIN_KEY" --arg root "$REPO_ROOT" '
  (.plugins[$key] // [])
  | ( map(select(.projectPath == $root)) + map(select(.scope == "user")) + . )
  | .[0].installPath // empty
' "$INSTALLED_JSON")"

if [ -z "$plugin_root" ] || [ ! -x "${plugin_root}/scripts/ready_wait_merge.sh" ]; then
  echo "プラグイン ${PLUGIN_KEY} の ready_wait_merge.sh が見つかりません（installPath: '${plugin_root}'）。" >&2
  echo "導入・更新: claude plugin marketplace update hayato && claude plugin install ${PLUGIN_KEY}" >&2
  exit 1
fi

READY_MERGE_REPO_ROOT="$REPO_ROOT" exec "${plugin_root}/scripts/ready_wait_merge.sh" "$@"
