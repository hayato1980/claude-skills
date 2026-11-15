#!/usr/bin/env bash
# PR マージゲートの判定。
#
# ready_wait_merge.sh がポーリングで取得した check-runs レスポンス（GitHub REST
# `GET /repos/{owner}/{repo}/commits/{ref}/check-runs`）をファイルで受け取り、
# マージしてよいかだけを判定する。ネットワークには一切アクセスしない。
#
# ブロッキングジョブ名は環境変数 GATE_BLOCKING_JOBS（空白区切り）で受ける。各リポの
# docs/agents/pr-merge-gate.md から ready_wait_merge.sh が読んで渡す（blocking_jobs.sh）。
# すべてが conclusion=success なら OK。
#
# 使い方: GATE_BLOCKING_JOBS="gate" judge_gate_checks.sh <check-runs.json> [baseline_id]
#   baseline_id（省略時 0）: この id 以下の check run は無視する。ready 化の直前に
#   控えた「その時点の最大 id」を渡すと、同一 head SHA で再 ready したときに前サイクルの
#   結果（stale）を今回の結果として読まない。
#
# 終了コード: 0=OK / 1=NG（マージしない）/ 2=PENDING（まだ判定できない）/ 3=用法エラー
set -euo pipefail

readonly EXIT_OK=0
readonly EXIT_NG=1
readonly EXIT_PENDING=2
readonly EXIT_USAGE=3

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "usage: GATE_BLOCKING_JOBS=\"<job> ...\" $0 <check-runs.json> [baseline_id]" >&2
  exit "$EXIT_USAGE"
fi

# 空のまま走ると「見るジョブが 0 個 = 常に OK」になり、CI を見ずにマージしうる。
# fail-closed で用法エラーにする。
read -r -a BLOCKING_JOBS <<<"${GATE_BLOCKING_JOBS:-}"
if [ "${#BLOCKING_JOBS[@]}" -eq 0 ]; then
  echo "GATE_BLOCKING_JOBS が空です（CI で止めるジョブ名を空白区切りで指定してください）" >&2
  exit "$EXIT_USAGE"
fi

readonly runs_file="$1"
readonly baseline_id="${2:-0}"

if ! [[ "$baseline_id" =~ ^[0-9]+$ ]]; then
  echo "baseline_id は非負整数で指定してください: '${baseline_id}'" >&2
  exit "$EXIT_USAGE"
fi

if [ ! -f "$runs_file" ]; then
  echo "check-runs ファイルがありません: ${runs_file}" >&2
  exit "$EXIT_USAGE"
fi

if ! jq empty "$runs_file" 2>/dev/null; then
  echo "check-runs ファイルを JSON として読めません: ${runs_file}" >&2
  exit "$EXIT_USAGE"
fi

# 構文が正しい JSON でも check-runs の形とは限らない（トークン期限切れの
# `{"message": "..."}` 等）。ここで弾かないと後段の jq が落ち、呼び出し側が終了コード 1 を
# 「CI red」と誤解釈する。
if ! jq -e 'has("check_runs") and (.check_runs | type == "array") and (.check_runs | all(type == "object"))' "$runs_file" >/dev/null 2>&1; then
  echo "check-runs ファイルの形が想定と異なります（check_runs が配列でない、または要素が object でありません）: ${runs_file}" >&2
  exit "$EXIT_USAGE"
fi

ng=false
pending=false
for job in "${BLOCKING_JOBS[@]}"; do
  # 同一 head SHA に同名の check run が複数件残ることがある（draft のまま opened で
  # 一度 skip 実行され、その後 ready 化でもう一本走る等）。id が最大＝最新のものだけを見る。
  # 未出現なら last が null になり (last // {}) で空扱い。実行中は conclusion=null。
  # どちらも空文字に畳み込み「まだ判定できない」として同じ扱いにする。
  #
  # `read` ではなく `mapfile`: conclusion が空文字（先頭フィールド）のとき
  # `IFS=$'\t' read` は先頭の IFS 文字を読み飛ばし、2 フィールド目がずれる。
  mapfile -t _job_fields < <(
    jq -r --arg name "$job" --argjson baseline "$baseline_id" '
      [.check_runs[] | select(.name == $name and .id > $baseline)] | sort_by(.id) | (last // {})
      | (.conclusion // ""), (.html_url // "")
    ' "$runs_file"
  )
  conclusion="${_job_fields[0]}"
  html_url="${_job_fields[1]}"

  if [ "$conclusion" = "success" ]; then
    continue
  elif [ -z "$conclusion" ]; then
    pending=true
  else
    ng=true
    echo "${job}: ${conclusion} ${html_url}"
  fi
done

# NG は PENDING より優先する（片方が既に落ちているなら、もう片方を待つ意味がない）。
if [ "$ng" = true ]; then
  exit "$EXIT_NG"
fi
if [ "$pending" = true ]; then
  exit "$EXIT_PENDING"
fi
exit "$EXIT_OK"
