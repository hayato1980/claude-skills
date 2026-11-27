# 0008: 相手引きの規則はスクリプトの 1 か所だけ。中継が無ければ人へ渡し、文書の写しは残さない

## 決めたこと

- **往復の「相手 / 既存のレビュー」を引く規則は `session_closeout counterpart` の 1 か所だけに置く。** 候補の絞り込み（アーカイブ済み・自分・対象タグ無し・別リポ）、向き（`--want reviewer|fixer`）、`get_session` での revision の確認、曖昧なときは 1 本を選ばず拒否、はここが持つ。結果は `found <id>` / `none` / `ambiguous <id>,…`。
- runbook・create-ccw-session・retro-closeout・`pr-review-dispatch` hook は「スクリプトを呼ぶ」だけを書き、規則を写さない。MCP を呼んで保存ファイルを渡す手順だけが prose に残る。
- **中継（`scripts/ci/session_closeout.sh`）が無い・失敗したときは「相手を引けなかった」と明示して人へ渡す。** 古い prose の手順（`list_sessions` を `jq` で読む）は逃げ道として残さない。残すと規則が 2 か所になり、また割れる。
- review-dialogue を使うリポも、`scripts/ci/session_closeout.sh` の中継と許可ルール `Bash(scripts/ci/session_closeout.sh*)` が必須になる。
- `list_events` の保存ファイルを読む 1 行も `events` サブコマンドへ出し、fixture で呼んで確かめる。

## なぜか

同じ判定が 3 か所に prose としてあり、テストが無かった。直近の修正（#30 #31 #37 #40 #25）はすべてこの概念に当たっていた。#30（`list_sessions` の行に `session_context` が無く、修正側からだけ相手が 0 件に見えて往復が静かに止まる）は、実測の形の fixture があれば捕まる種類の誤りだった。

## 変えないもの

- [0002](./0002-review-rounds-wake-the-counterpart-directly.md): tags と revision で引き、title では引かない。
- [0004](./0004-merge-gate-calls-the-github-api-directly.md): `session_closeout` の読み取り経路。
