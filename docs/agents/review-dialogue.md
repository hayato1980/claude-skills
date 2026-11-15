# レビュー往復（review-dialogue）の設定

このリポは共有プラグインの配布元で、main へのマージは有効化している全プロジェクトに届く（`plugin.json` に `version` を書かないため、コミット単位で配られる）。

## オーナーマージの基準表

当たる PR は、レビュー側が `needs-owner-merge` を付けて ready 化し、CI を見届けて止まる（マージはオーナー）。当たらない PR は、CI が green ならレビュー側がマージする。

| 基準 | 当たる | 当たらない |
|---|---|---|
| 判断の新設・変更 | `docs/decisions/` に判断を足す。既存の判断の「決めたこと」を変える・範囲を広げる・取り消す | 誤字・リンク・言い回しの修正、索引（`docs/decisions/README.md`）の追従だけ |
| プラグイン・スキルの追加・削除、利用側との契約の変更 | `.claude-plugin/marketplace.json` にプラグインを足す・消す。`plugins/*/skills/` にスキルを丸ごと足す・消す。README の `docs/agents/*.md` の表にある契約の見出し・中身を変える（利用側の設定が壊れる） | 既存スキルの本文・手順の修正、スクリプトの不具合修正、テストの追加 |

## CI が走る条件

`.github/workflows/ci.yml` は `pull_request` の `opened` / `synchronize` / `reopened` / `ready_for_review` と、main への push で走る。

- **往復中（draft）の push でも CI は走り直す**（`synchronize`）。
- draft → ready の遷移でも走る（`ready_for_review`）。`ready_wait_merge.sh` はこの run を待つ。
- 止めるジョブは `test` だけ（`docs/agents/pr-merge-gate.md`）。

## push 前に流すコマンド

`.github/workflows/ci.yml` の `test` ジョブと同じものを手元で流す（`jq`・`shellcheck`・`pytest` が要る）。

```bash
shellcheck plugins/dev-workflow/scripts/*.sh plugins/dev-workflow/hooks/*.sh plugins/dev-workflow/templates/*.sh
python -m pytest tests -q
claude plugin validate .
```

公開リポの禁止語チェックは、`ci.yml` の「No private names」ステップの `git grep` をそのまま流す（語の一覧はそこにだけ置く）。
