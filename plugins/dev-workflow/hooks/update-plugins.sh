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
#   箇条書き（`- \`プラグイン名@マーケットプレイス名\``）。この一覧は**既定に足される**:
#   このプラグイン自身（dev-workflow@hayato）は常に更新し、一覧に書かれていてもいなくても同じ。
# - 起動は hooks.json の matcher `startup` で新しい claude プロセスの開始時だけ。
#   同時に走る分（同じコンテナの並行セッション）は flock -n で止める。
# - 結果を待つ意味が無いので setsid で切り離してセッション開始を待たせない。setsid が無ければ起動しない。
# - どこで失敗しても exit 0。プラグインが古くてもセッションは動くべきため。
#
# 環境変数:
#   DEV_WORKFLOW_SKIP_PLUGIN_UPDATE=1     何もしない（利用側が更新を止めたいとき）
#   DEV_WORKFLOW_PLUGIN_UPDATE_LOG        ログ（既定 /tmp/dev-workflow-plugin-update.log。追記）
#   DEV_WORKFLOW_PLUGIN_UPDATE_LOCK       ロックファイル（既定 /tmp/dev-workflow-plugin-update.lock）
# 引数 --run: 背景に出さず、この場で実行する（背景起動の中身。テストも使う）
set -u

SELF_PLUGIN="dev-workflow@hayato"
LOG_FILE="${DEV_WORKFLOW_PLUGIN_UPDATE_LOG:-/tmp/dev-workflow-plugin-update.log}"
LOCK_FILE="${DEV_WORKFLOW_PLUGIN_UPDATE_LOCK:-/tmp/dev-workflow-plugin-update.lock}"

# 更新対象を 1 行 1 件で標準出力に出す。自身が先頭、続いて設定の一覧（重複は除く）。
list_plugins() {
  local config="${CLAUDE_PROJECT_DIR:-$PWD}/docs/agents/plugin-update.md"
  printf '%s\n' "${SELF_PLUGIN}"
  [ -f "${config}" ] || return 0
  awk -v self="${SELF_PLUGIN}" '
    /^## / { in_section = ($0 == "## 更新するプラグイン"); next }
    in_section && /^- `[^`@ ]+@[^`@ ]+`/ {
      s = $0; sub(/^- `/, "", s); sub(/`.*/, "", s)
      if (s != self && !(s in seen)) { seen[s] = 1; print s }
    }
  ' "${config}" 2>/dev/null || true
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

  local plugins plugin marketplace seen=" "
  plugins="$(list_plugins)"

  # 先に marketplace を重複なく全部更新し、そのあとプラグインを更新する。
  # fd 9（ロック）は claude に引き継がない: 孫プロセスが残ってもロックを握り続けないため。
  while IFS= read -r plugin; do
    marketplace="${plugin#*@}"
    case "${seen}" in *" ${marketplace} "*) continue ;; esac
    seen="${seen}${marketplace} "
    claude plugin marketplace update "${marketplace}" 9>&- \
      || echo "WARNING: ${marketplace} の marketplace update に失敗（キャッシュのまま続行）" >&2
  done <<<"${plugins}"
  while IFS= read -r plugin; do
    claude plugin update "${plugin}" 9>&- \
      || echo "WARNING: ${plugin} の update に失敗（導入済みの版のまま）" >&2
  done <<<"${plugins}"
  return 0
}

[ "${DEV_WORKFLOW_SKIP_PLUGIN_UPDATE:-0}" = "1" ] && exit 0
command -v claude >/dev/null 2>&1 || exit 0

if [ "${1:-}" = "--run" ]; then
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
