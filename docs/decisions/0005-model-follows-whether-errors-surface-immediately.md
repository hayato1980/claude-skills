# 0005: 払い出しのモデルは「誤りが即座に可視化されるか」で選ぶ

## 決めたこと

- **判断の質がそのまま成果になる作業は opus、手を動かす比率が高く、誤りが即座に可視化される作業は sonnet。**
- 既定は opus。**例外（sonnet）の表にだけ載せる**。列挙式（表に載っている語だけ払い出せる）にすると、スキルが増えるたびに
  表の保守が要る。共通の例外は `tdd` / `wizard` / `research` / `prototype` / `resolving-merge-conflicts` / `triage`。
  リポ固有スキルの行は対象リポの `docs/agents/ccw-dispatch.md` で足す。
- `tdd` を sonnet に落とせるのは、**その差分を必ず別セッションの opus が読み直す**から（[0001](./0001-review-runs-in-a-separate-session-and-model.md)）。
  レビューの払い出しをやめるなら `tdd` の行も opus に戻す。`review-dialogue` は opus から動かさない。
- **sonnet 側に Haiku を置かない。** CCW の子は auto mode で走り、auto mode は Haiku に対応していない。
  指定すると子が Manual に落ちて許可待ちで止まる。使える幅は opus ↔ sonnet だけ。
- **割り当ての単位はセッションの入口フロー。** `create_session` の `model` はセッション全体への一括指定で、
  中で呼ぶスキルごとには変えられない（スキル frontmatter の `model:` は CCW では効かない）。「実装は安く、レビューは opus」は
  セッションを分けてしか成立しない。
