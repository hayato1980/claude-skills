# 0004: マージゲートは GitHub API を直接叩く

## 背景

CCW には `gh` CLI が無い。draft PR を ready 化し、CI を待ち、green ならマージする一連を 1 コマンドにしたい。

## 決めたこと

1. **`ready_wait_merge.sh` に限り、`GH_TOKEN`（無ければ `GITHUB_TOKEN`）で GitHub の REST / GraphQL を `curl` で直接叩く。**
   `gh` には依存しない。トークンは argv に載せず無名パイプでヘッダとして渡し、値をログにも標準出力にも出さない。
2. **ready 化は GraphQL（`markPullRequestReadyForReview`）を先に試す。** Claude Code セッションの agent proxy が
   GraphQL を 403 で止めたとき（メッセージに "Claude Code sessions" を含む）だけ、REST shim
   （`POST /pulls/{n}/ccr/ready_for_review`）へフォールバックする。プロキシの有無どちらでも動く。
3. **判定は純粋関数に切り出す。** `judge_gate_checks.sh` は取得済みの check-runs JSON を受けて終了コード
   （0 OK / 1 NG / 2 PENDING / 3 用法）だけを返し、ネットワークに触れない。pytest で検証できる。
4. **fail-closed。** 止めるジョブの設定が無い・空なら、ジョブ 0 個 = 常に green にならないよう非ゼロで止まる。
   check-runs の形が想定外（トークン失効のエラー応答等）なら用法エラーで、「CI red」と誤読させない。
   ready 化前に最大 check run id を控え、同一 SHA の前サイクルの結果（stale）を今回の結果として読まない。
   マージは判定した head SHA を指定し、待機中に push が入って head が変わっていたら GitHub の 409 で止める。
5. **プロジェクト固有の設定は対象リポの `docs/agents/pr-merge-gate.md`（`## CI で止めるジョブ`）から読む。**
   各リポの `scripts/ci/ready_wait_merge.sh` は、プラグイン本体を `~/.claude/plugins/installed_plugins.json` から
   探して呼ぶだけの中継。許可ルール `Bash(scripts/ci/ready_wait_merge.sh*)` が固定のパスを指す必要があるため、中継を残す。
   先頭に `bash` を付けた許可ルールは auto mode では無効になるため、スクリプトは単独で直接呼ぶ。

## 結果

ネットワーク部分（グルー）は手動確認、判定と結線（中継・設定の読み込み・fail-closed）は偽 curl を使ったテストで固定する。
