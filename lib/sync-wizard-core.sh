#!/usr/bin/env bash
# lib/sync-wizard-core.sh — 共有版 wizard-core.sh の写しを同期する／ずれを検出する。
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
DEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKER_RE='^# synced-from: '

fetch() { # fetch SHA FILE → stdout
  local sha="$1" file="$2"
  if [[ -n "${WIZARD_CORE_SOURCE_DIR:-}" ]]; then
    cat "$WIZARD_CORE_SOURCE_DIR/$file"
  else
    curl -fsSL "https://raw.githubusercontent.com/$REPO/$sha/lib/$file"
  fi
}

marker_sha() { # 写しの 2 行目から SHA を読む
  sed -n '2p' "$DEST_DIR/wizard-core.sh" | sed -n "s|${MARKER_RE}${REPO}@\([^ ]*\) .*|\1|p"
}

strip_marker() { sed "2{/${MARKER_RE}/d;}" "$1"; }

cmd_check() {
  local sha rc=0 f expected
  sha="$(marker_sha)"
  if [[ -z "$sha" ]]; then
    echo "wizard-core.sh の 2 行目に '# synced-from: $REPO@<sha> ...' がありません。" >&2
    exit 1
  fi
  for f in "${FILES[@]}"; do
    if ! expected="$(fetch "$sha" "$f")"; then
      echo "$f: 共有版を取得できませんでした（$REPO@$sha）。" >&2
      rc=1; continue
    fi
    if ! diff -u <(printf '%s\n' "$expected") <(strip_marker "$DEST_DIR/$f") \
        --label "shared:$f@$sha" --label "copy:$f"; then
      echo "$f: 写しが共有版（$REPO@$sha）とずれています。" >&2
      rc=1
    fi
  done
  [[ $rc -eq 0 ]] && echo "ok: 写しは $REPO@$sha と一致しています。"
  exit "$rc"
}

cmd_update() {
  local ref="${1:-main}" sha f
  if [[ -n "${WIZARD_CORE_SOURCE_DIR:-}" ]]; then
    sha="local"
  else
    sha="$(curl -fsSL -H 'Accept: application/vnd.github.sha' \
      "https://api.github.com/repos/$REPO/commits/$ref")"
  fi
  for f in "${FILES[@]}"; do
    {
      fetch "$sha" "$f" | sed -n '1p'
      printf '# synced-from: %s@%s lib/%s\n' "$REPO" "$sha" "$f"
      fetch "$sha" "$f" | sed -n '2,$p'
    } > "$DEST_DIR/$f.tmp"
    mv "$DEST_DIR/$f.tmp" "$DEST_DIR/$f"
  done
  chmod +x "$DEST_DIR/sync-wizard-core.sh"
  echo "updated: $REPO@$sha"
}

case "${1:-}" in
  check)  cmd_check ;;
  update) shift; cmd_update "$@" ;;
  *) echo "usage: $(basename "$0") check | update [REF]" >&2; exit 2 ;;
esac
