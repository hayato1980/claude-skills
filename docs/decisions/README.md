# 判断の記録

`dev-workflow` の手順として今も効いている判断。1 判断 1 ファイル。経緯の細部は書かず、**何を決め、なぜか**だけを残す。

| 番号 | 判断 |
|---|---|
| [0001](./0001-review-runs-in-a-separate-session-and-model.md) | レビューは実装と別セッション・別モデルで行う |
| [0002](./0002-review-rounds-wake-the-counterpart-directly.md) | レビュー往復の起床は相手を直接起こし、ポーリングは保証として残す |
| [0003](./0003-findings-land-through-a-wrapper-skill.md) | 指摘は、上流 code-review を包むスキル経由で 1 件 1 スレッドに着地させる |
| [0004](./0004-merge-gate-calls-the-github-api-directly.md) | マージゲートは GitHub API を直接叩く（`session-closeout` の読み取りも同じ方式） |
| [0005](./0005-model-follows-whether-errors-surface-immediately.md) | 払い出しのモデルは「誤りが即座に可視化されるか」で選ぶ |
| [0006](./0006-config-tests-evaluate-with-the-tool.md) | 設定・IaC のテストは、ソースを正規表現で読まず、ツール自身に評価させた値で確かめる（0007 で全テストに拡大） |
| [0007](./0007-tests-do-not-read-file-contents-with-regex.md) | テストコードは、ファイルの中身を grep・正規表現で読んで確かめない |
| [0008](./0008-counterpart-rule-lives-in-one-script.md) | 相手引きの規則はスクリプトの 1 か所だけ。中継が無ければ人へ渡し、文書の写しは残さない |
