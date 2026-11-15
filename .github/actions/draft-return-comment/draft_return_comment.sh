#!/usr/bin/env bash
# 「赤い PR を draft に戻した」ときに PR へ残すコメント本文を組み立てる。本文は stdout。GitHub へは触らない。
#
# ⚠️ 本文は draft 化の成否（DRAFT_RESULT）に必ず連動させる。戻せていないのに「戻しました」と書くと、
# draft 状態が唯一のマージゲートのリポでは、素通りしていることが見えなくなる。
#
# 入力（すべて環境変数）:
#   DRAFT_RESULT  draft 化ステップの結果。`success` だけが「戻せた」側。`skipped` はトークン未登録で
#                 戻す操作をしなかった。それ以外（`failure` / 空 / 未知の値）はすべて「戻せていない」側に
#                 倒し、本スクリプトは落ちない（落ちるとコメントが 1 件も出ない）
#   JOB_NAME      落ちたジョブの名前（表の見出しに出す。必須）
#   JOB_RESULT    そのジョブの結果
#   CHECKS        `名前=結果` を 1 行 1 件。結果が空なら「実行されていない」と表に書く
#   RUN_URL       この run の URL（必須）
#   NOTE          成否によらず末尾に足す文（任意。手元での再現方法など）
#   RETRY_NOTE    戻せたときだけ書く復帰手順（任意。既定は再度 Ready for review の案内）
set -euo pipefail

: "${JOB_NAME:?JOB_NAME is required}"
: "${RUN_URL:?RUN_URL is required}"
NOT_RUN="実行されていない"
result="${DRAFT_RESULT:-}"

if [ "$result" = "success" ]; then
  echo "🔴 ゲートが失敗したため、この PR を draft に戻しました。"
else
  cat <<EOF2
🚨 ゲートが失敗しましたが、**この PR を draft に戻せませんでした**。マージゲートが効いていません。

**この PR は ready のままで、いまマージできてしまいます。** マージする前に手で draft へ戻すか、
ゲートが赤い原因を直してください。
EOF2
  case "$result" in
    skipped)
      echo
      echo "draft に戻すトークンが未登録のため、戻す操作自体をしていません（PR を draft に戻せる権限のトークンを登録してください）。"
      ;;
    failure)
      echo
      echo "draft 化が失敗した理由は下の run ログの「Convert PR back to draft」ステップに出ています。"
      ;;
    *)
      echo "Unexpected DRAFT_RESULT: '${result}' (success / failure / skipped のいずれかを期待)" >&2
      echo
      echo "⚠️ draft 化ステップの結果が \`${result:-（空）}\` でした（\`success\` / \`failure\` / \`skipped\` のいずれかを期待）。ステップ自体が走らなかった可能性があります。"
      ;;
  esac
fi

echo
echo "| 検査（\`${JOB_NAME}\` ジョブ: ${JOB_RESULT:-$NOT_RUN}） | 結果 |"
echo "| --- | --- |"
while IFS= read -r line; do
  [ -n "$line" ] || continue
  name="${line%%=*}"
  value="${line#*=}"
  [ "$value" != "$line" ] || value=""
  echo "| \`${name}\` | ${value:-$NOT_RUN} |"
done <<<"${CHECKS:-}"
echo
echo "ログ: ${RUN_URL}"

if [ -n "${NOTE:-}" ]; then
  echo
  echo "$NOTE"
fi

# 復帰導線は draft 化に成功したときだけ成り立つ。失敗時に書くと、すでに ready の PR に
# 「再度 Ready にしろ」と案内することになり、ready_for_review が発火せず CI が 1 本も立たない。
if [ "$result" = "success" ]; then
  echo
  echo "${RETRY_NOTE:-修正を push したあと、**再度 Ready for review にすると再実行されます**（push だけでは再実行されません）。}"
fi
