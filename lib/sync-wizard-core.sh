#!/usr/bin/env bash
# lib/sync-wizard-core.sh — 共有版 wizard-core.sh の写しを同期する／ずれを検出する。
#
# 実行は `bash <このファイル> ...` で足りる。実行権を付けるかどうかは利用側の規約に従う
# （同期は書き込み時に既存ファイルの権限を変えない）。
#
# 利用側のリポは、このファイルと wizard-core.sh を同じディレクトリに「写し」として
# 置く。各写しの 2 行目に、どの共有コミットから写したかを書く:
#     # synced-from: hayato1980/claude-skills@<コミット SHA> lib/<ファイル名>
#
#   sync-wizard-core.sh check          写しが、2 行目に書いたコミットの共有版と一致するか確かめる。
#                                       ずれていれば差分を出して 1 で終わる（CI で使う）。
#   sync-wizard-core.sh update [REF]   共有リポの REF（既定 main）の版で写しを作り直す。
#
# 突き合わせるのは「写しに書いたコミット」。main ではない。共有側が先へ進んだだけでは
# 利用側の CI は赤くならず、写しを 1 文字でも直す（または印のコミットと違う中身にする）と
# 赤くなる。追従は update を実行して、その差分をレビューして取り込む。
#
# 環境変数:
#   WIZARD_CORE_SOURCE_DIR  共有版を置いたローカルのディレクトリ（テスト用。設定すると
#                           ネットワークを使わない）。
set -euo pipefail

REPO="hayato1980/claude-skills"
FILES=(wizard-core.sh sync-wizard-core.sh)
# CDPATH が設定された端末で `cd` が別の場所へ飛ばないよう、空にして組み込みの cd を使う。
DEST_DIR="$(CDPATH='' \command cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# テスト用の「共有版」ディレクトリで update したときに印へ入れる SHA（40 桁の 0）。
# ネットワークの check では解決できない。
LOCAL_SHA="0000000000000000000000000000000000000000"

# 一時的な失敗（5xx・接続拒否）では再試行する。CI が 1 回の揺らぎで赤くならないように。
CURL_OPTS=(-fsSL --retry 8 --retry-max-time 180 --retry-connrefused)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# fetch SHA FILE OUT — 共有版を OUT に 1 回だけ取得する。失敗は非 0。
fetch() {
  local sha="$1" file="$2" out="$3"
  if [[ -n "${WIZARD_CORE_SOURCE_DIR:-}" ]]; then
    cat "$WIZARD_CORE_SOURCE_DIR/$file" > "$out"
  else
    curl "${CURL_OPTS[@]}" "https://raw.githubusercontent.com/$REPO/$sha/lib/$file" -o "$out"
  fi
}

# check の対象は「手で作った写し」なので、印は期待する形と完全一致で比べる。
marker_line() { sed -n '2p' "$DEST_DIR/$1"; }

cmd_check() {
  local rc=0 f line sha shas=() common="" got
  for f in "${FILES[@]}"; do
    line="$(marker_line "$f")"
    if [[ ! "$line" =~ ^"# synced-from: ${REPO}@"([0-9a-f]{40})" lib/${f}"$ ]]; then
      echo "${f}: 2 行目が '# synced-from: ${REPO}@<40 桁の sha> lib/${f}' ではありません: ${line}" >&2
      exit 1
    fi
    shas+=("${BASH_REMATCH[1]}")
  done
  common="${shas[0]}"
  for sha in "${shas[@]}"; do
    if [[ "$sha" != "$common" ]]; then
      echo "写しの印の sha が食い違っています: ${shas[*]}" >&2
      exit 1
    fi
  done
  for f in "${FILES[@]}"; do
    got="$WORK/shared.$f"
    if ! fetch "$common" "$f" "$got"; then
      echo "${f}: 共有版を取得できませんでした（${REPO}@${common}）。" >&2
      rc=1; continue
    fi
    sed '2d' "$DEST_DIR/$f" > "$WORK/copy.$f"
    if ! diff -u "$got" "$WORK/copy.$f" --label "shared:$f@$common" --label "copy:$f"; then
      echo "${f}: 写しが共有版（${REPO}@${common}）とずれています。" >&2
      rc=1
    fi
  done
  [[ $rc -eq 0 ]] && echo "ok: 写しは ${REPO}@${common} と一致しています。"
  exit "$rc"
}

cmd_update() {
  local ref="${1:-main}" sha f
  if [[ -n "${WIZARD_CORE_SOURCE_DIR:-}" ]]; then
    sha="$LOCAL_SHA"
    echo "warning: ローカルの共有版から作りました。印の sha はダミーで、ネットワークの check では解決できません。" >&2
  else
    sha="$(curl "${CURL_OPTS[@]}" -H 'Accept: application/vnd.github.sha' \
      "https://api.github.com/repos/$REPO/commits/$ref")"
  fi
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "REF '${ref}' を 40 桁の sha に解決できませんでした: ${sha}" >&2
    exit 1
  fi
  # すべて取得できてから書く（途中で失敗しても写しを半端に変えない）。
  for f in "${FILES[@]}"; do
    fetch "$sha" "$f" "$WORK/in.$f" || { echo "${f}: 共有版を取得できませんでした（${REPO}@${sha}）。" >&2; exit 1; }
    {
      sed -n '1p' "$WORK/in.$f"
      printf '# synced-from: %s@%s lib/%s\n' "$REPO" "$sha" "$f"
      sed -n '2,$p' "$WORK/in.$f"
    } > "$WORK/out.$f"
  done
  # cat > で書き戻し、既存ファイルの権限とシンボリックリンクを保つ。
  for f in "${FILES[@]}"; do
    cat "$WORK/out.$f" > "$DEST_DIR/$f"
  done
  echo "updated: ${REPO}@${sha}"
}

main() {
  case "${1:-}" in
    check)  cmd_check ;;
    update) shift; cmd_update "$@" ;;
    *) echo "usage: $(basename "$0") check | update [REF]" >&2; exit 2 ;;
  esac
}

# ⚠️ update はこのファイル自身（の写し）も書き換える。bash はスクリプトを読みながら実行するので、
# 実行中に自分を上書きすると壊れる。末尾の 1 行で main を呼んで exit し、以降を読ませない。
main "$@"; exit $?
