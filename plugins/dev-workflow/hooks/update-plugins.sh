#!/bin/bash
#
# SessionStart hook: 共有プラグイン自身を最新にする（背景・fail-soft）。
#
# クラウド環境の Setup script は、スナップショットを作るときにしか走らない。そのため
# このリポへの変更は、スナップショットの作り直しまで届かない。セッション開始のたびに
# `marketplace update` → `plugin update` を走らせて、同じコンテナで次に起動する claude
# プロセスから新しい版になるようにする。今動いているプロセスの探索には効かない。
#
# - 更新だけを行う。`marketplace add` / `install` はしない（入っているから hook が動いている）。
# - 更新対象は、対象リポの docs/agents/plugin-update.md の見出し `## 更新するプラグイン` の下の
#   箇条書き（`- \`プラグイン名@マーケットプレイス名\``）。ファイルや見出しが無いときは
#   このプラグイン自身（dev-workflow@hayato）だけを更新する。
# - 二重起動（resume / compact での再発火、同じコンテナの並行セッション）は flock -n で止める。
# - 結果を待つ意味が無いので setsid で切り離してセッション開始を待たせない。setsid が無ければ起動しない。
# - どこで失敗しても exit 0。プラグインが古くてもセッションは動くべきため。
#
# 環境変数:
#   DEV_WORKFLOW_SKIP_PLUGIN_UPDATE=1     何もしない
#   DEV_WORKFLOW_PLUGIN_UPDATE_LOG        ログ（既定 /tmp/dev-workflow-plugin-update.log。追記）
#   DEV_WORKFLOW_PLUGIN_UPDATE_LOCK       ロックファイル（既定 /tmp/dev-workflow-plugin-update.lock）
#   DEV_WORKFLOW_PLUGIN_UPDATE_FOREGROUND=1  背景に出さず、この場で実行する（テスト用）
set -u

DEFAULT_PLUGIN="dev-workflow@hayato"
LOG_FILE="${DEV_WORKFLOW_PLUGIN_UPDATE_LOG:-/tmp/dev-workflow-plugin-update.log}"
LOCK_FILE="${DEV_WORKFLOW_PLUGIN_UPDATE_LOCK:-/tmp/dev-workflow-plugin-update.lock}"

# 更新対象を 1 行 1 件で標準出力に出す。
list_plugins() {
  local config="${CLAUDE_PROJECT_DIR:-$PWD}/docs/agents/plugin-update.md" found=""
  if [ -f "${config}" ]; then
    found="$(awk '
      /^## / { in_section = ($0 == "## 更新するプラグイン"); next }
      in_section && /^- `[^`@ ]+@[^`@ ]+`/ { s = $0; sub(/^- `/, "", s); sub(/`.*/, "", s); print s }
    ' "${config}" 2>/dev/null || true)"
  fi
  if [ -n "${found}" ]; then
    printf '%s\n' "${found}"
  else
    printf '%s\n' "${DEFAULT_PLUGIN}"
  fi
}

run_update() {
  command -v claude >/dev/null 2>&1 || return 0

  # 同じコンテナで 2 本同時に走らせない（~/.claude/plugins を同時に書き換えないため）。
  # flock が無い環境ではロックせずに続行する。
  if command -v flock >/dev/null 2>&1; then
    exec 9>"${LOCK_FILE}" || return 0
    if ! flock -n 9; then
      echo "plugin-update: 別の更新が実行中のため今回は何もしない" >&2
      return 0
    fi
  fi

  local plugin marketplace
  while IFS= read -r plugin; do
    [ -n "${plugin}" ] || continue
    marketplace="${plugin#*@}"
    claude plugin marketplace update "${marketplace}" \
      || echo "WARNING: ${marketplace} の marketplace update に失敗（キャッシュのまま続行）" >&2
    claude plugin update "${plugin}" \
      || echo "WARNING: ${plugin} の update に失敗（導入済みの版のまま）" >&2
  done < <(list_plugins)
  return 0
}

[ "${DEV_WORKFLOW_SKIP_PLUGIN_UPDATE:-0}" = "1" ] && exit 0
command -v claude >/dev/null 2>&1 || exit 0

if [ "${1:-}" = "--run" ] || [ "${DEV_WORKFLOW_PLUGIN_UPDATE_FOREGROUND:-0}" = "1" ]; then
  run_update
  exit 0
fi

# hook の stdin (JSON) は使わない。切り離して背景に出す。
if command -v setsid >/dev/null 2>&1; then
  setsid bash "$0" --run </dev/null >>"${LOG_FILE}" 2>&1 &
  echo "plugin-update: プラグイン更新を背景で起動 (log: ${LOG_FILE})" >&2
else
  echo "WARNING: setsid が無いため、プラグイン更新を起動しません（セッションは続行）。" >&2
fi
exit 0
