# CCW 払い出し（create-ccw-session）の設定

このリポは共有プラグインの配布元。issue はほぼすべてオーナーが書き、受け入れ基準まで本文にある。

## 払い出しを止めるラベル

| ラベル | 扱い | 理由 |
|---|---|---|
| `ready-for-human` | 払い出さない | 人の判断・操作が要る |
| `wontfix` | 払い出さない | 対応しないと決めた |
| `deferred` | 払い出さない | 棚卸しで「今はやらない」と判断した（ラベルは未作成） |
| `duplicate` | 払い出さない | 統合先の issue で進める |
| `question` | 止めて聞く | 決まっていないことが残っている |

ラベルが無い issue は、共通の規則どおり止めて聞く。

## タグの決め方

`tags` の第 3 要素は、issue タイトルから次の順で最初に取れたものにする。

1. タイトルが `type(scope): ...` の形なら `scope`（例: `feat(decisions): ...` → `decisions`）。
2. タイトルにリポ内のパスがあれば、その先頭のディレクトリ名。`plugins/<name>/...` は `<name>`（例: `lib/sync-wizard-core.sh` → `lib`）。
3. どちらも取れなければ付けない（2 要素にする）。

## モデル表に足す行

なし（このリポに `.claude/skills/` のリポ固有スキルは無い）。

## source_url

`https://github.com/hayato1980/claude-skills`
