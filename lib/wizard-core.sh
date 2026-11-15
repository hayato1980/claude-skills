# shellcheck shell=bash
# lib/wizard-core.sh
# 対話ウィザードの共通部分（画面表示・入力・確認・env への書き出し）。
# 人が端末で実行する手順スクリプトが、どれも同じ見た目と挙動になるようにする。
#
# **source 専用**（実行権は付けない）。呼び出し側の先頭で:
#     set -euo pipefail
#     . "$(dirname "${BASH_SOURCE[0]}")/wizard-core.sh"
#     TOTAL_STAGES=<段の数>
#
# TOTAL_STAGES と ENV_FILE は source の前後どちらで設定してもよい（既存の値を尊重し、
# 無ければそれぞれ 0 と `.env`）。
#
# **set はここで触らない。** source されるので、呼び出し側のシェルオプションを
# 書き換えることになる。オプションは呼び出し側が宣言する。
#
# 公開する関数:
#   画面 : banner / stage / say / step / note / warn / pause / confirm / open_url
#   値   : ask / ask_secret / write_env / skipped_note / finish / abort
#   （_existing は ask / ask_secret の内部 helper で、公開契約には含めない）
#
# 配り方: この版が正本。利用側は写しを置き、正本とずれたら CI で落とす。
# 利用側の独自の部分は、この core を source した上に積む。

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

# 呼び出し側が段の数を宣言する。
TOTAL_STAGES="${TOTAL_STAGES:-0}"

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"

# 書き出した KEY と、人が手でやり残したこと。**配列ではなく改行区切りの文字列**で
# 持つ。macOS の既定 bash（3.2）は `set -u` の下で空配列の展開を unbound として
# 落とすため、1 つも書かずに finish へ着く経路が壊れる。
WRITTEN_ENV=""
SKIPPED=""

# _clear wipes the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is an action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# abort "reason" states the reason in red and exits. The wizard's only abnormal exit.
# **stderr へ書く。** stdout に書くと、`X="$(f)"` のように command substitution の
# 中で呼ばれた abort の理由が X に吸われ、画面には何も出ないまま exit する。
abort() { printf '\n  %s✗ %s%s\n\n' "$RED" "$1" "$RESET" >&2; exit 1; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
# 開く手段が無い／失敗したときの警告は 1 本（リダイレクトの外）にまとめる。
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else false; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

# confirm "question" is a y/N gate; returns success on yes. EOF counts as no.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any. KEY は固定文字列として照合する
# （正規表現ではない）。最後に現れた行の値を返し、無ければ失敗する。
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  K="$1" awk 'BEGIN { k = ENVIRON["K"] "="; n = length(k) }
    index($0, k) == 1 { v = substr($0, n + 1); f = 1 }
    END { if (!f) exit 1; printf "%s", v }' "$ENV_FILE"
}

# _ask FN KEY PROMPT MODE HIDDEN は ask / ask_secret の本体（HIDDEN=1 で入力を隠す）。
_ask() {
  local fn="$1" key="$2" prompt="$3" mode="$4" hidden="$5" current="" input=""
  if [ -n "$mode" ] && [ "$mode" != "--no-remember" ]; then
    abort "${fn} ${key}: 未知のオプションです: ${mode}（綴りを確認してください）。"
  fi
  if [[ "$mode" != "--no-remember" ]]; then
    current=$(_existing "$key" || true)
  fi
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  # 改行の無い最後の行は read が値を入れたまま 1 を返す。値があるなら EOF とはみなさない。
  # 値が空のまま尽きたときだけ abort する。
  if [[ "$hidden" == 1 ]]; then
    read -rs input || [[ -n "$input" ]] || abort "入力が読めませんでした（対話端末で実行してください）。"
    printf '\n'
  else
    read -r input || [[ -n "$input" ]] || abort "入力が読めませんでした（対話端末で実行してください）。"
  fi
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# ask KEY "Prompt" [--no-remember] reads a value into $KEY. Offers the existing
# ENV_FILE value as a default on re-runs (Enter keeps it). Visible input.
# With --no-remember, never reads or offers the existing value.
#
# **第 3 引数は空か `--no-remember` のどちらかだけ。** 他の値（綴り間違い）は
# abort する。黙って既定側へ倒すと、綴りを間違えても気づけない。
#
# **入力が尽きたら（EOF）その場で abort する。** 握り潰すと、呼び手が while で
# 再入力させている場合に無限ループして CPU を焼く（非対話実行や Ctrl-D）。
ask() { _ask ask "$1" "$2" "${3:-}" 0; }

# ask_secret KEY "Prompt" [--no-remember] is like ask, but input is hidden.
ask_secret() { _ask ask_secret "$1" "$2" "${3:-}" 1; }

# write_env KEY VALUE upserts KEY=VALUE into ENV_FILE (creates it; replaces
# any existing line). Idempotent. KEY は固定文字列として照合する。書き戻しは
# `cat >` なので、既存ファイルの権限とシンボリックリンクを保つ。
# 同じ KEY を何度書いても WRITTEN_ENV には 1 回だけ載る。
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  K="$key" awk 'BEGIN { k = ENVIRON["K"] "=" } index($0, k) != 1' "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  case " ${WRITTEN_ENV} " in
    *" ${key} "*) ;;
    *) WRITTEN_ENV="${WRITTEN_ENV}${WRITTEN_ENV:+ }${key}" ;;
  esac
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# skipped_note "..." records something the wizard could not do, for the closing
# summary. 人が後で手で埋める宿題が黙って消えないようにするための口。
skipped_note() { SKIPPED="${SKIPPED}${1}
"; }

# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  if [ -n "${WRITTEN_ENV}" ]; then
    note "wrote $(printf '%s' "${WRITTEN_ENV}" | wc -w | tr -d ' ') value(s) to $ENV_FILE: ${WRITTEN_ENV}"
  fi
  if [ -n "${SKIPPED}" ]; then
    printf '\n'; warn "still to do by hand:"
    printf '%s' "${SKIPPED}" | while IFS= read -r s; do
      if [ -n "${s}" ]; then note "  - ${s}"; fi
    done
  fi
  printf '\n'
}
