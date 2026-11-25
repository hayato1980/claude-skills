---
name: ready-merge
description: "draft PR を ready 化 → CI 完了待ち → 判定 → （成功時のみ）マージする。オーナーが /ready-merge [PR番号] と打ったときだけ動く。"
argument-hint: "[--no-merge] [--skip-local-gate \"<理由>\"] [PR番号]"
disable-model-invocation: true
allowed-tools: Bash(scripts/ci/ready_wait_merge.sh*)
---

Use this skill when: the owner types `/ready-merge [--no-merge] [--skip-local-gate "<理由>"] [PR番号]` to run the PR merge gate by hand.

対象: $ARGUMENTS

`scripts/ci/ready_wait_merge.sh` を実行する。PR 番号・`--skip-local-gate "<理由>"` が指定されていれば、そのまま引数として渡す（順不同。`--no-merge` も同様）。省略されたら引数なしで呼ぶ
（スクリプトが現在の git ブランチから対応する open PR を自動解決する）。

**先頭に `bash` を付けず、ほかのコマンドと `&&` でつながず、単独で呼ぶ。** 許可ルール
`Bash(scripts/ci/ready_wait_merge.sh*)` に一致するのはこの形だけで、外れると auto mode の分類器に回り
`[Merge Without Review]` として拒否されうる（`bash …*` の許可ルールは「ワイルドカード付きのインタプリタ」と
みなされ、auto mode に入った時点で無効になる）。CI 待ちは最大 40 分で、Bash の前面実行の上限（10 分）を超える。
**必ずバックグラウンドで起動し、終了通知で起きる。**

スクリプトの標準出力・標準エラーをそのままユーザーに見せる。非ゼロ終了なら「マージしていない」ことと、
出力に含まれる失敗ジョブ・ログ URL（あるいはエラー内容）をそのまま伝える。

## このスキルが前提にするもの

| 前提 | 内容 |
|---|---|
| 各リポの `scripts/ci/ready_wait_merge.sh` | プラグイン本体への**中継**。無ければ作る（雛形: プラグインの `templates/ready_wait_merge.sh`） |
| 各リポの `docs/agents/pr-merge-gate.md` | 見出し `## CI で止めるジョブ` の下に、止める対象のジョブ名を `- \`名前\`` で列挙する。**無い・空なら、スクリプトは何もせず非ゼロで終わる**（ジョブ 0 個＝常に green になってしまうため） |
| 各リポの `docs/agents/pr-merge-gate.md`（任意）の `## ready 前に実行するコマンド` | ``- `コマンド` `` の箇条書き（1 行 1 コマンド）。draft → ready 化する前に、書いた順に `REPO_ROOT` で `bash -c` 実行し、最初に失敗したところで止めて ready にしない。**見出しが無ければ何もしない**。見出しがあって箇条書きが空ならエラー |
| 環境変数 `GH_TOKEN`（無ければ `GITHUB_TOKEN`） | `gh` CLI には依存しない。マージゲートは GitHub の API を直接叩く（→ [判断](https://github.com/hayato1980/claude-skills/blob/main/docs/decisions/0004-merge-gate-calls-the-github-api-directly.md)） |

## 何をするか

1. （draft の PR だけ・設定のあるリポだけ）手元ゲートを実行する。手元の HEAD が PR の head と一致し、作業ツリーに未コミットの変更が無いことを先に確かめ、満たさなければコマンドを走らせず ready にしない。いずれかのコマンドが非 0 でも ready にしない。すでに ready の PR では CI が走り済みなので実行しない
2. PR を ready 化する（GraphQL。Claude Code のセッション経由で agent proxy が 403 で止めたときだけ REST shim へフォールバック）
3. 30 秒間隔・最大 40 分で CI の check run を見て、`docs/agents/pr-merge-gate.md` のジョブがすべて success になるのを待つ
4. `--no-merge` が無く green なら、判定した head SHA を指定して squash マージする（待機中に push が入って head が変わっていたら GitHub が 409 を返し、マージしない）

`--no-merge` 付きでは手順 3 の green で「CI green。マージせずに止めます。」と出して終了コード 0 で終わる（マージの API は呼ばない）。赤・タイムアウト等の出力と終了コードは付けないときと同じ。

赤・タイムアウト・判定不能のときはマージしない。draft へ戻すのはスクリプトの仕事ではない（戻すのは CI 側のジョブか、
`review-dialogue` のレビュー側）。

## 手元ゲートの抜け道 `--skip-local-gate "<理由>"`

理由は必須。直後が無い・空・空白だけ・`--` で始まるときは、何もせず非 0 で拒否する。使うと ready 化の**前**に PR へ
`[ready-merge] 手元ゲートを省略しました: <理由>` をコメントし、投稿に失敗したら ready にしない。
設定の無いリポでは省略するものが無いので、コメントは投稿せず、その旨を出して続ける。

## 誰が叩くか

- `review-dialogue` で合意に至ったレビュー側（モデル）が、runbook の手順 7-2a / 7-2b に従って叩く。`needs-owner-merge`
  ラベル付きの PR には `--no-merge` を付けて叩き、ready 化して CI を見届けたところで止める（マージはオーナー）。
- オーナーが手元で `/ready-merge` と打つ。このスキルは `disable-model-invocation: true` なので、
  モデルが自分で `Skill(ready-merge)` を呼ぶことはない（モデルはスクリプトを直接叩く）。

## 手動確認手順

手元ゲートの設定の読み取りと、ready 化・コメントの有無は pytest で検査済み（偽の API サーバへ `READY_MERGE_GH_API` で向ける）。
実際の GitHub との結線は次で確認する。

- draft PR に対して実行し、「ready 化 → CI green → マージ」まで一連通ること
- CI を意図的に失敗させた draft PR に対して実行し、「報告して非ゼロ終了（マージしない）」こと
