#!/usr/bin/env bash
# PR ready化 → CI 完了待ち → 判定 → （成功時のみ）マージ。
#
# 判定ロジックは同じディレクトリの judge_gate_checks.sh に切り出してあり、そちらは pytest で
# テスト済み。本スクリプトは GitHub REST/GraphQL API を実際に呼ぶグルーコードで、CI 待ち〜マージは
# ネットワーク依存のため ready-merge スキルの手動確認手順で検証する。ただし手元ゲート
# （ready 前に実行するコマンド・--skip-local-gate）は READY_MERGE_GH_API で偽 API に向けて pytest で検査する。
# 設定の読み取りは local_gate_commands.sh（pytest 済み）。
#
# CI で止めるジョブ名は、対象リポの docs/agents/pr-merge-gate.md（見出し
# 「## CI で止めるジョブ」）から blocking_jobs.sh で読む。
#
# 認証は環境の GH_TOKEN（無ければ GITHUB_TOKEN）を使う。gh CLI には依存しない
# （マージゲートは API を直接叩く → docs/decisions/0004）。
#
# 対象リポ: 環境変数 READY_MERGE_REPO_ROOT、無ければカレントの git 作業ツリー。
# 各リポの scripts/ci/ready_wait_merge.sh（中継）が READY_MERGE_REPO_ROOT を渡す。
#
# 使い方: ready_wait_merge.sh [--no-merge] [--skip-local-gate "<理由>"] [PR番号]
#   --no-merge: ready 化して CI を見届け、green でもマージせずに終了コード 0 で止める
#   （review-dialogue の 7-2a = needs-owner-merge の PR 用。マージはオーナーが行う）。
#   PR番号 省略時は現在の git ブランチに対応する open PR を自動解決する。
set -euo pipefail

# `cd` は `CDPATH` の export や関数/エイリアス上書きで解決先を印字したり別所へ飛んだりする。
# 隣のスクリプトを確実に指すため、この形で解決する。
SCRIPT_DIR="$(CDPATH='' \command cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly JUDGE_SCRIPT="${SCRIPT_DIR}/judge_gate_checks.sh"
readonly BLOCKING_JOBS_SCRIPT="${SCRIPT_DIR}/blocking_jobs.sh"
readonly LOCAL_GATE_SCRIPT="${SCRIPT_DIR}/local_gate_commands.sh"

if [ -n "${READY_MERGE_REPO_ROOT:-}" ]; then
  REPO_ROOT="$READY_MERGE_REPO_ROOT"
else
  REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT" ]; then
  echo "対象リポジトリを解決できません（git 作業ツリーの中で実行するか、READY_MERGE_REPO_ROOT を指定してください）" >&2
  exit 1
fi
readonly REPO_ROOT

# CI で止めるジョブ（空・見出し無しは blocking_jobs.sh が非ゼロで止める = fail-closed）。
GATE_BLOCKING_JOBS="$(bash "$BLOCKING_JOBS_SCRIPT" "${REPO_ROOT}/docs/agents/pr-merge-gate.md" | tr '\n' ' ')"
GATE_BLOCKING_JOBS="${GATE_BLOCKING_JOBS% }"
export GATE_BLOCKING_JOBS

readonly POLL_INTERVAL_SECONDS=30
readonly TIMEOUT_SECONDS=$((40 * 60))

# 向き先は READY_MERGE_GH_API で差し替えられる（未設定なら本物の GitHub）。テストが手元の偽 API
# サーバへ向けて、ready 化・マージ・コメントが呼ばれたかを検査するための口。
readonly GH_API="${READY_MERGE_GH_API:-https://api.github.com}"
readonly GH_GRAPHQL_API="${GH_API}/graphql"

readonly TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo "GH_TOKEN（または GITHUB_TOKEN）が未設定です。" >&2
  exit 1
fi

remote_url=$(git -C "$REPO_ROOT" remote get-url origin)
owner_repo=$(printf '%s\n' "$remote_url" | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##')
readonly OWNER="${owner_repo%%/*}"
readonly REPO="${owner_repo##*/}"

# 認証ヘッダ・Accept・ステータス付与という共通部分だけをここに持つ。残りは呼び出し側の
# 追加引数（$@）で渡す。
#
# トークンは argv に載せず、無名パイプ（プロセス置換）でヘッダファイルとして渡す —
# 同一ホスト上の `ps` から見えないようにするため（値をログや標準出力に一切出さない、
# という docs/decisions/0004 と同趣旨）。`-H @<(...)` は bash の process substitution で、
# ダブルクォートで囲むと展開されない（bash の仕様）ため意図的に無引用。
# ⚠️ この process substitution は事前に配列へ組み立てて後から curl に渡すと動かない
# （実測: fd が curl 実行前に閉じる）。同一コマンド行に書く必要がある。
_auth_curl() {
  curl -sS -w '\n%{http_code}' \
    -H @<(printf 'Authorization: Bearer %s\n' "$TOKEN") \
    -H "Accept: application/vnd.github+json" \
    "$@"
}

# GitHub REST/GraphQL を叩く共通ヘルパ。レスポンスは本文の末尾に改行区切りで HTTP
# ステータスが付く形で返る（_api_body / _api_status で分離する）。
# $1: HTTP method, $2: 完全な URL, $3: リクエストボディ（省略可、JSON文字列）
_api() {
  local method="$1" url="$2" data="${3:-}"
  if [ -n "$data" ]; then
    _auth_curl -X "$method" -H "Content-Type: application/json" -d "$data" "$url"
  else
    _auth_curl -X "$method" "$url"
  fi
}

_api_body() { printf '%s' "$1" | sed '$d'; }
_api_status() { printf '%s' "$1" | tail -n1; }

# _api を呼び、200 以外ならラベル付きメッセージを stderr に出して即終了する。
# 200 ならボディを stdout に返す。「$(_api_status ...) != 200 なら echo して exit 1」
# という同型のブロックが何箇所にも分かれていたのをここへ集約した。
# $1: HTTP method, $2: 完全な URL, $3: 失敗時のラベル, $4: リクエストボディ（省略可）
_api_or_die() {
  local method="$1" url="$2" label="$3" data="${4:-}"
  local resp status
  resp=$(_api "$method" "$url" "$data")
  status=$(_api_status "$resp")
  if [ "$status" != "200" ]; then
    echo "${label}（HTTP ${status}）: $(_api_body "$resp")" >&2
    exit 1
  fi
  _api_body "$resp"
}

# 手元ゲート。draft → ready 化する経路から呼ぶ。失敗したら exit 1 で ready 化に進ませない。
# 設定の読み取りは local_gate_commands.sh（見出しが無ければ何も出さない = 従来どおり。
# 見出しだけで箇条書きが空なら非ゼロ = ここで止まる）。
run_local_gate() {
  local local_gate_commands comment_payload comment_resp comment_status
  local local_head_sha gate_command gate_exit
  # 設定の読み取りは local_gate_commands.sh（見出しが無ければ何も出さない = 従来どおり。
  # 見出しだけで箇条書きが空なら非ゼロ = ここで止まる）。
  local_gate_commands="$(bash "$LOCAL_GATE_SCRIPT" "${REPO_ROOT}/docs/agents/pr-merge-gate.md")"
  if [ -n "$SKIP_LOCAL_GATE_REASON" ] && [ -z "$local_gate_commands" ]; then
    echo "手元ゲートの設定が無いリポなので、省略するものがありません。--skip-local-gate は無視して続けます（コメントも残しません）。"
  elif [ -n "$SKIP_LOCAL_GATE_REASON" ]; then
    # 抜け道を使った理由は、ready 化の **前** に PR へ残す。残せないまま通さない（失敗したら ready にしない）。
    comment_payload=$(jq -n --arg body "[ready-merge] 手元ゲートを省略しました: ${SKIP_LOCAL_GATE_REASON}" '{body: $body}')
    comment_resp=$(_api POST "${GH_API}/repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments" "$comment_payload")
    comment_status=$(_api_status "$comment_resp")
    if [ "$comment_status" != "201" ]; then
      echo "手元ゲートを省略した理由の PR コメントに失敗しました（HTTP ${comment_status}）: $(_api_body "$comment_resp")" >&2
      echo "理由を残せないまま省略できないので、ready にしません。" >&2
      exit 1
    fi
    echo "手元ゲートを省略します（理由を PR #${PR_NUMBER} にコメントしました）: ${SKIP_LOCAL_GATE_REASON}"
  elif [ -n "$local_gate_commands" ]; then
    # 呼ぶのはオーナーだけでなく review-dialogue のレビュー側も含む。PR のブランチがチェック
    # アウトされているとは限らず、別のコードを検査して通ってしまう恐れがあるので、実行前に
    # 手元の HEAD が PR の head と一致し、未コミットの変更が無いことを確かめる。
    local_head_sha="$(git -C "$REPO_ROOT" rev-parse HEAD)"
    if [ "$local_head_sha" != "$pr_head_sha" ]; then
      echo "手元の HEAD が PR #${PR_NUMBER} の head と一致しません。ready にしません。" >&2
      echo "  手元の HEAD: ${local_head_sha}" >&2
      echo "  PR の head : ${pr_head_sha}" >&2
      echo "PR のブランチをチェックアウトして最新にしてから再実行してください。" >&2
      exit 1
    fi
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
      echo "作業ツリーに未コミットの変更があります。手元だけにある変更で通ってしまうため、ready にしません。" >&2
      echo "コミットするか退避してから再実行してください。" >&2
      exit 1
    fi
    while IFS= read -r gate_command; do
      echo "手元ゲート: ${gate_command}"
      set +e
      # stdin を閉じる: ループの here-string を `bash -c` が継ぐと、stdin を読むコマンド（cat・ssh・
      # docker run -i など）が後続の行を飲み込み、後ろの失敗するコマンドが走らずにゲートが素通りする。
      (CDPATH='' \command cd -- "$REPO_ROOT" && bash -c "$gate_command" < /dev/null)
      gate_exit=$?
      set -e
      if [ "$gate_exit" -ne 0 ]; then
        echo "手元ゲートが失敗しました（終了コード ${gate_exit}）: ${gate_command}" >&2
        echo "ready にしません。" >&2
        exit 1
      fi
    done <<< "$local_gate_commands"
  fi
}

# ---- 引数の解釈 ----
# 形: ready_wait_merge.sh [--skip-local-gate "<理由>"] [PR番号]（順不同）。
# 抜け道なので、理由なしは API を 1 つも呼ぶ前に拒否する（直後が無い・空・空白だけ・`--` 始まり）。
PR_NUMBER=""
SKIP_LOCAL_GATE_REASON=""
NO_MERGE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --no-merge)
      NO_MERGE=true
      shift
      ;;
    --skip-local-gate)
      if [ $# -lt 2 ] || [ -z "${2//[[:space:]]/}" ] || [[ "$2" == --* ]]; then
        echo "--skip-local-gate には理由が必須です（例: --skip-local-gate \"別 PR で検査済み\"）。理由なしでは手元ゲートを省略できません。" >&2
        exit 1
      fi
      SKIP_LOCAL_GATE_REASON="$2"
      shift 2
      ;;
    -*)
      echo "未知のオプションです: '$1'（使い方: ready_wait_merge.sh [--no-merge] [--skip-local-gate \"<理由>\"] [PR番号]）" >&2
      exit 1
      ;;
    *)
      if [ -n "$PR_NUMBER" ]; then
        echo "PR番号は 1 つだけ指定してください: '${PR_NUMBER}' '$1'" >&2
        exit 1
      fi
      PR_NUMBER="$1"
      shift
      ;;
  esac
done
readonly SKIP_LOCAL_GATE_REASON NO_MERGE

# ---- PR 番号の解決 ----
if [ -n "$PR_NUMBER" ]; then
  if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
    echo "PR番号は数字で指定してください: '${PR_NUMBER}'" >&2
    exit 1
  fi
else
  branch=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)
  body=$(_api_or_die GET "${GH_API}/repos/${OWNER}/${REPO}/pulls?head=${OWNER}:${branch}&state=open" "PR検索に失敗しました")
  PR_NUMBER=$(printf '%s' "$body" | jq -r '.[0].number // empty')
  if [ -z "$PR_NUMBER" ]; then
    echo "ブランチ '${branch}' に対応する open PR が見つかりません。PR番号を引数で指定してください。" >&2
    exit 1
  fi
fi
readonly PR_NUMBER

echo "対象PR: #${PR_NUMBER}"

# ---- PR 状態の取得 ----
pr_body=$(_api_or_die GET "${GH_API}/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}" "PR #${PR_NUMBER} の取得に失敗しました")

pr_state=$(printf '%s' "$pr_body" | jq -r '.state')
pr_merged=$(printf '%s' "$pr_body" | jq -r '.merged')
pr_draft=$(printf '%s' "$pr_body" | jq -r '.draft')
pr_node_id=$(printf '%s' "$pr_body" | jq -r '.node_id')
pr_head_sha=$(printf '%s' "$pr_body" | jq -r '.head.sha')
readonly CHECK_RUNS_URL="${GH_API}/repos/${OWNER}/${REPO}/commits/${pr_head_sha}/check-runs?per_page=100"

if [ "$pr_merged" = "true" ]; then
  echo "PR #${PR_NUMBER} は既に merged です。" >&2
  exit 1
fi
if [ "$pr_state" = "closed" ]; then
  echo "PR #${PR_NUMBER} は既に closed です。" >&2
  exit 1
fi

# ---- ready化（既に ready ならスキップ。冪等性） ----
if [ "$pr_draft" = "true" ]; then
  # 手元ゲート（draft → ready 化する経路でだけ。ready 化前に手元で落ちるものを落とす）。
  run_local_gate

  # ready化 **前** に、この head SHA の現在の最大 check run id を控える。
  # 本リポの正規のリカバリ運用（draft に戻して push 無しで再度 ready にする）では、
  # 同一 SHA に前サイクルの check run が残ったまま次のサイクルが始まる。これを控えず
  # 待機に入ると、新しい run がまだ現れていない間は前サイクルの結果（stale の
  # success/failure）を今回の結果として読んでしまう。
  # judge_gate_checks.sh にこの id を渡し、これより新しい run だけを見させる。
  # ここで失敗を 0 にフォールバックすると S-6 対策が無言で無効化され、stale な green を
  # 今回の結果として読んでマージしうる。他の API 失敗と同じく
  # _api_or_die で exit 1 に倒す（fail-open ではなく fail-closed）。
  baseline_body=$(_api_or_die GET "$CHECK_RUNS_URL" "baseline 取得に失敗しました")
  BASELINE_ID=$(printf '%s' "$baseline_body" | jq -r '[.check_runs[].id] | max // 0')
  readonly BASELINE_ID

  echo "PR #${PR_NUMBER} を ready for review にします。"
  # markPullRequestReadyForReview は GraphQL にしか無い（convertPullRequestToDraft と対称。
  # CI 側の「失敗時に draft へ戻す」ジョブと同じ理由）。
  #
  # ただし Claude Code セッション経由（本リポのリモート実行環境等）では、outbound の
  # agent proxy が生の /graphql エンドポイントを 403 で止め、代わりに
  # `POST /repos/{owner}/{repo}/pulls/{n}/ccr/ready_for_review` という REST shim へ
  # 誘導する（実測。プロキシの無い素の GitHub API では存在しないルート）。
  # まず GraphQL を試し、この既知のブロックのときだけ shim へフォールバックする —
  # そうすればプロキシの有無どちらでも動く。
  # shellcheck disable=SC2016 # 意図的な単引用: $id は GraphQL の変数で、シェルではなく
  # GitHub 側が下の variables から解決する。展開させると空文字になりクエリが壊れる。
  mutation='mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { pullRequest { number isDraft } } }'
  gql_payload=$(jq -n --arg query "$mutation" --arg id "$pr_node_id" '{query: $query, variables: {id: $id}}')
  gql_resp=$(_api POST "$GH_GRAPHQL_API" "$gql_payload")
  gql_status=$(_api_status "$gql_resp")
  gql_body=$(_api_body "$gql_resp")

  if [ "$gql_status" = "403" ] && printf '%s' "$gql_body" | jq -e '.message | test("Claude Code sessions"; "i")' >/dev/null 2>&1; then
    echo "agent proxy が GraphQL をブロックしました。REST shim (ccr/ready_for_review) にフォールバックします。"
    _api_or_die POST "${GH_API}/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/ccr/ready_for_review" "ready化に失敗しました（shim）" >/dev/null
  elif [ "$gql_status" != "200" ] || printf '%s' "$gql_body" | jq -e '.errors' >/dev/null 2>&1; then
    echo "ready化に失敗しました（HTTP ${gql_status}）: ${gql_body}" >&2
    exit 1
  fi
else
  echo "PR #${PR_NUMBER} は既に ready です。ready化はスキップします。"
  if [ -n "$SKIP_LOCAL_GATE_REASON" ]; then
    echo "すでに ready の PR では手元ゲートを実行しないので、--skip-local-gate は無視して続けます（コメントも残しません）。"
  fi
  # ready化 自体をスキップするので、前サイクルの結果を混同する余地は無い
  # （baseline_id は 0 のまま。既存の run をそのまま今回の結果として見てよい）。
  readonly BASELINE_ID=0

  # ready 化後の push では CI が再実行されない（synchronize を意図的に持たない。
  # 対象リポの『CI が走る条件』を参照）。つまり「既に ready」な PR に新しい commit を
  # 積んだ直後にこのスクリプトを呼ぶと、その head SHA に対する check run が永遠に現れず、下の待機ループが
  # タイムアウトまで 40 分ハングする。ready 化をスキップする経路でだけ、
  # この head SHA にブロッキングジョブの run が1件もないことを早期に検知して
  # 即座に終える（total_count だと無関係な check run の存在で素通りしてしまうため、
  # ジョブ名で絞る。この名前は judge_gate_checks.sh に渡す GATE_BLOCKING_JOBS と
  # 同じ変数から取るので、集合がずれることはない）。
  # PR が最初から非 draft で開かれた直後は、opened イベントの check run 登録が
  # 数秒〜数十秒遅れることがある。1回だけ猶予を置いて再確認し、
  # 「本当に CI が無い」と「まだ登録されていないだけ」を誤診しないようにする。
  for _attempt in 1 2; do
    precheck_body=$(_api_or_die GET "$CHECK_RUNS_URL" "check-runs 取得に失敗しました")
    precheck_count=$(printf '%s' "$precheck_body" | jq -r --arg jobs "$GATE_BLOCKING_JOBS" '
      ($jobs | split(" ")) as $jobs
      | [.check_runs[] | select(.name as $n | $jobs | index($n))] | length
    ')
    if [ "$precheck_count" -gt 0 ]; then
      break
    fi
    if [ "$_attempt" -eq 1 ]; then
      sleep 5
    fi
  done
  if [ "$precheck_count" -eq 0 ]; then
    echo "この head SHA (${pr_head_sha}) に対する CI run がありません。" >&2
    echo "ready化後の push では CI は再実行されません（対象リポの『CI が走る条件』を参照）。draft に戻してから再度 ready にしてください。" >&2
    exit 1
  fi
fi

# ---- CI 完了待ち ----
# タイムアウトの起算点はここ（ready化 API 呼び出し / スキップの直後）に統一する。
echo "CI 完了待ち（最大 $((TIMEOUT_SECONDS / 60)) 分、${POLL_INTERVAL_SECONDS} 秒間隔）..."
start_ts=$(date +%s)
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT
runs_file="${tmp_dir}/check-runs.json"

while :; do
  elapsed=$(( $(date +%s) - start_ts ))
  if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
    echo "タイムアウトしました（${TIMEOUT_SECONDS}秒）。判定不能のためマージしません。" >&2
    echo "確認: https://github.com/${OWNER}/${REPO}/pull/${PR_NUMBER}/checks" >&2
    exit 1
  fi

  checks_body=$(_api_or_die GET "$CHECK_RUNS_URL" "check-runs 取得に失敗しました")
  printf '%s' "$checks_body" > "$runs_file"

  set +e
  judge_output=$(bash "$JUDGE_SCRIPT" "$runs_file" "$BASELINE_ID")
  judge_exit=$?
  set -e

  case "$judge_exit" in
    0)
      echo "$judge_output"
      if [ "$NO_MERGE" = "true" ]; then
        echo "CI green。マージせずに止めます。"
        exit 0
      fi
      echo "CI green。マージします。"
      break
      ;;
    1)
      echo "CI red。マージしません。" >&2
      echo "$judge_output" >&2
      exit 1
      ;;
    2)
      sleep "$POLL_INTERVAL_SECONDS"
      ;;
    *)
      echo "判定スクリプトの用法エラー（終了コード ${judge_exit}）: ${judge_output}" >&2
      exit 1
      ;;
  esac
done

# ---- マージ（squash。ブランチ削除はリポ設定の自動削除に任せる） ----
# `sha` を指定し、CI green を確認した head（pr_head_sha）以外へは絶対にマージしない。
# 40分の待機中に push が入ると head は変わるが CI は再実行されない（対象リポの『CI が走る条件』を参照）ため、
# sha を指定しないと「判定した SHA」と「実際にマージする SHA」がずれ、CI が一度も
# 走っていない新しい head を素通りでマージしうる（本ゲートの目的そのものに関わる）。ずれていれば GitHub 側が 409 を返すので、それを検出する。
merge_payload=$(jq -n --arg sha "$pr_head_sha" '{merge_method: "squash", sha: $sha}')
_api_or_die PUT "${GH_API}/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/merge" "マージに失敗しました" "$merge_payload" >/dev/null

echo "PR #${PR_NUMBER} をマージしました。"
