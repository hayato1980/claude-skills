---
name: create-ccw-session
description: "起票済みの GitHub issue を、オーナーが承認したフロー（指定が無ければ親が案を出す）で子の CCW（Claude Code Web）セッションへ払い出す。「この issue を CCW で進めて」「#NNN を tdd で払い出して」「#NNN を review-dialogue に出して」「子セッションを立てて」で発動。"
argument-hint: "#683 [#684 ...] [フロー語 (tdd|review-dialogue|diagnosing-bugs|grill-with-docs|...)]"
allowed-tools: mcp__github__issue_read, mcp__claude-code-remote__create_session, mcp__claude-code-remote__get_session, mcp__claude-code-remote__list_sessions, Bash(grep:*), Bash(jq:*), Bash(ls:*), Bash(find:*), Bash(sort:*), Bash(tail:*), Read
---

Use this skill when: handing an already-filed GitHub issue to a child CCW session, on a flow the owner has approved, instead of doing the work in this session.

対象: $ARGUMENTS

引数が空（issue 番号も無い）なら、番号を指定するようユーザーに聞き返して終わる。

**フローはオーナーの承認が必須。** フロー語が**明示されたらそれに従い**、親は判断しない。**無ければ親が
フロー案を出し**、オーナーが承認表で OK するまで払い出さない（→ [なぜ親がフローを決めないか](#なぜ親がフローを決めないか)、
[判断 0001](https://github.com/hayato1980/claude-skills/blob/main/docs/decisions/0001-review-runs-in-a-separate-session-and-model.md)）。

このスキルは `create_session` を呼べる（`allowed-tools`）。許可の歯止めは**承認表**（手順 5）にある ——
承認表を出してオーナーの OK を得るまで `create_session` を呼ばない。

## このスキルが読む、リポ固有の設定

プロジェクト固有の事情はスキルに書かず、対象リポの `docs/agents/` に置く。**まず次を読む。**

| ファイル | 読む見出し | 中身 |
|---|---|---|
| `docs/agents/ccw-dispatch.md` | `## 払い出しを止めるラベル` | 払い出さない・止めて聞くラベルの一覧（[払い出す前の門](#払い出す前の門)） |
| 同上 | `## タグの決め方` | `create_session` の `tags` 第 3 要素（領域／種別）をどこから取るか |
| 同上 | `## モデル表に足す行` | 共通のモデル表に足す、リポ固有スキルの行 |
| 同上 | `## source_url` | `create_session` に渡すリポジトリの URL |
| `docs/agents/issue-tracker.md` | — | 課題管理先の owner/repo。`issue_read` に渡す |

`ccw-dispatch.md` が無い、または上の見出しが欠けているときは、**推測で進めず、ユーザーに聞いて止まる**
（`source_url` を誤ると別のリポジトリで子が走る）。

## 発動トリガー

- 「#NNN を tdd で払い出して」「#NNN を review-dialogue に出して」「#NNN を grill-with-docs で」
- 「この issue を CCW で進めて」「#NNN のセッションを起動して」「子セッションを立てて」「払い出して」
  → **フロー語が無いので、親が[フロー案](#フロー案の出し方)を出す**
- スラッシュコマンド `/create-ccw-session #NNN [<フロー語>]`（プラグイン名つきの正式名は `/dev-workflow:create-ccw-session`）

---

## 手順

1. **issue を読む。** `mcp__github__issue_read`（`method="get"`, `issue_number=<番号>`）。フロー語が明示された
   ときに使うのは `title` と `labels` だけで、本文は読まなくてよい（子が自分で読む）。
2. **ラベルで払い出してよいか決める**（→ [払い出す前の門](#払い出す前の門)）。フロー案を考えるより先に通す ——
   払い出せない issue の案を出しても承認表が無駄になる。
3. **フロー語を取る。**
   - **引数にフロー語がある**: そのまま使う。親は妥当性を判断しない。
   - **issue 番号しか無い**: 親が[フロー案](#フロー案の出し方)を issue ごとに出す。**既定フローは設けない**
     （案はあくまで案で、手順 5 の承認を経てはじめてフロー語になる）。
4. **フロー語の実在を確認する**（→ [フロー語の実在確認](#フロー語の実在確認)）。オーナー指定の語も親の案も
   **同じ確認を通す**。見つからなければ、指定語は聞き返して止め、親の案は別の語を選び直す。
   **推測で近い語に寄せない**（`review-dialoge` → `review-dialogue` の補正もしない）。
5. **承認を取る**（→ [承認](#承認)）。平文の表を 1 つ出して一括で確認する。
6. **`mcp__claude-code-remote__create_session` を issue 1 件につき 1 回**呼ぶ。引数は
   [下の表](#create_session-の引数)のとおり。
7. 返ってきた `session_id` をユーザーに伝えて終わる。**進捗の監視はしない**（子は自分で draft PR を作り、
   PR 側の仕組みに載る）。

**1 issue = 1 セッション。** 複数 issue を渡されたら件数だけ `create_session` を呼ぶ。

**フロー語を明示したときは 1 回 1 フロー。** その呼び出しのフローを全件に同一適用する。フローを混ぜたい時は
2 回打つ（`#683 #684 tdd` が「両方 tdd」か「684 だけ tdd」か曖昧になるため、混在は受け付けない）。
**これは明示の曖昧さ回避の規則なので、親のフロー案には当てはめない** —— 語が無い呼び出しでは issue ごとに
違うフローになってよい。

## 払い出す前の門

払い出してよいかは、issue のラベルで決まる。**ラベルの語彙と、止めるラベルの一覧はリポ固有**なので
`docs/agents/ccw-dispatch.md` の `## 払い出しを止めるラベル` から読む。共通の規則は次のとおり。

| issue の状態 | どうするか |
|---|---|
| 払い出してよいと判断済みのラベル（`ready-for-agent` 等）が付いている | 払い出す |
| 設定が「払い出さない」とするラベル（`ready-for-human` / `blocked-upstream` / `wontfix` 等）が付いている | **払い出さない。** 理由をユーザーに伝えて終わる |
| 設定が「止めて聞く」とするラベル（`needs-triage` / `needs-info` 等）が付いている、または**ラベルが無い** | 推測で払い出さない。triage を通すか、それでも払い出すかをユーザーに聞いて止まる |

**issue を持たない PR のレビュー払い出し（`#<PR番号>`）では、門は PR のラベルで行う。** PR にラベルが付いていないことが多いが、
これは「ラベルが無い」の「止めて聞く」には**当てない**（PR は既にオーナー自身が作って出した成果物で、triage の対象ではない）。
「払い出さない」「止めて聞く」の一覧に載るラベルが PR に付いているときだけ、上の表どおりに止める。ラベルが無ければ払い出す。

**この門は `review-dialogue` の払い出しにも同じく効く。** 実装が `ready-for-human` で止まった issue は、
レビューを出しても進まない。ただし、往復が決裂・打ち切りで人へ渡されて `ready-for-human` が付いた PR は別で、
そちらは人が裁定する（→ [runbook](../review-dialogue/runbook.md)）。

## フロー語の実在確認

渡された語 `<flow>` について、次のどれかに `SKILL.md` があれば実在とみなす。

```bash
ls .claude/skills/<flow>/SKILL.md 2>/dev/null
find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache" \( -path "*/skills/<flow>/SKILL.md" -o -path "*/skills/*/<flow>/SKILL.md" \) 2>/dev/null
```

プラグイン側はパスに**バージョンとカテゴリ（`engineering` / `productivity` 等）が入る**ので、`*` で受ける
（版を固定で書くと更新で壊れる）。

確認するのは**文字列が実在するか**だけで、そのフローが妥当かは見ない（妥当性はオーナーが指定したか、承認表で
OK したことで担保される）。任意の語を通すと、解決しないスラッシュコマンドを受け取った子が 1 セッション丸ごと
無駄になる。

## フロー案の出し方

フロー語が無いときだけ行う。`ask-matt` は `disable-model-invocation: true` で Skill ツールからは呼べないが、
**`SKILL.md` をファイルとして読むことは妨げない**（**回避策＝発動禁止の設定の書き換え等は取らない**）。

1. **`ask-matt` を glob で読む。** 版とカテゴリは `*` で受け、複数ヒットしたら最新版だけを読む。

   ```bash
   find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache" -path "*/skills/*/ask-matt/SKILL.md" | sort -V | tail -1
   ```

   出てきたパスを `Read` する。ヒットが無ければ聞き返して止める（フロー案の根拠が無いまま推測しない）。
2. **対象 issue の本文・コメント・ラベルを読む。** `mcp__github__issue_read` を `method="get"`（本文・ラベル・
   `title`）と `method="get_comments"` で呼ぶ。grilling の結論がコメントに残っていることが多く、それで妥当な
   フローが変わるため、コメントも読む。
3. **リポ固有スキルと、他のプラグインのスキルも候補に入れる。** `ls .claude/skills/*/SKILL.md` で列挙する。
   導入済みプラグインのスキル（`dev-workflow` の `issue-inventory` 等）も同様に候補になる。
4. **案を選ぶ。** `ask-matt` の分岐表と issue の中身から、issue ごとに第一案を 1 つ決める。
   - **除外する語**: `implement` / `implement-spec` / `handoff` / `grill-me` / `retro` / `teach` /
     `wait-what` / `setup-matt-pocock-skills`。除外リスト方式にするのは、許可リストだとスキルが増えるたびに
     列挙の保守が要るため（→ [モデル割り当て](#モデル割り当て)と同じ理由）。
   - **1 つに絞れないとき**（`grill-with-docs` か `tdd` か割れる等）: 聞き返して止めず、**第一案を載せ、
     次点とその理由を理由列に書く**。
   - 案にも[フロー語の実在確認](#フロー語の実在確認)をそのまま通す。

## 承認

`create_session` を呼ぶ前に、平文の表を 1 つ出して一括で確認を取る。選択肢ダイアログは使わない（件数が増えると
入り切らない）。承認は**省かない**。

**フロー語を明示された場合**は**理由列を付けない** —— 判断したのはオーナー自身なので、親が理由を書く材料が無い。

```
| issue | タイトル | フロー | model |
|---|---|---|---|
| #683 | feat(skill): issue を CCW セッションへ払い出すスキルを作る | /mattpocock-skills:tdd | claude-sonnet-5-5 |
```

**親がフロー案を出した場合に限り、1 行の理由列を足す。** オーナーはそのまま OK するか、行ごとにフロー語を
書き換えて返す。`model` は確定したフロー語から[モデル割り当て](#モデル割り当て)で引く（案でも変えない）。

```
| issue | タイトル | フロー | model | 理由 |
|---|---|---|---|---|
| #683 | feat(skill): issue を CCW セッションへ払い出すスキルを作る | /mattpocock-skills:tdd | claude-sonnet-5-5 | 仕様が本文で確定済み |
| #684 | feat(x): 方針が未確定の機能 | /mattpocock-skills:grill-with-docs | claude-opus-5-5 | 次点 tdd。範囲が未確定 |
```

**オーナーが行を書き換えて返したら**、書き換えた語について[実在確認](#フロー語の実在確認)とモデルの引き直しを行い、
**書き換えがあったときだけ**表を出し直してもう一度 OK をもらう。書き換えなしの OK ならそのまま払い出す。

## `create_session` の引数

| 引数 | 値 | 備考 |
|---|---|---|
| `title` | `#<番号> [<フロー語>] <issue タイトル逐語>` | **要約しない・切り詰めない。** GitHub と文字列一致で逆引きできる。角括弧のフロー語は**一覧でどのフローか見分けるため** —— `tags` の第 1 要素にも入っているがセッション一覧では**タグが見えない**。実装とレビューが同じ issue 番号・同じタイトルで並走するので、これが無いと一覧が完全に同名の 2 行になる。issue タイトルが `[area] ...` 形式のときは `#927 [tdd] [area] ...` と角括弧が 2 連するが、**前がフロー・後ろが領域**と位置で決まるのでそのままでよい |
| `tags` | `["<フロー語>", "issue-<番号>", "<領域または種別>"]` | 第 3 要素は `docs/agents/ccw-dispatch.md` の `## タグの決め方` に従って機械的に取る。取れなければ**タグを付けず 2 要素にする** |
| `prompt` | ``issue #<番号> に取り組む。Skill ツールで `<プラグイン名>:<フロー語>` を引数 `#<番号>` で発動する。`` | **この 1 文だけ。** `/` で始めない（`create_session` が拒む）。下記「prompt に足さないもの」。リポ固有スキル（`.claude/skills/` 由来）は接頭辞なしの `<フロー語>` |
| `model` | 下記「モデル割り当て」で解決した model ID | **必ず渡す**（既定 `claude-opus-5-5`）。省略すると親の model を継承してしまい、割り当てが効かない |
| `source_url` | `docs/agents/ccw-dispatch.md` の `## source_url` の値 | 必ず渡す（下記「`source_url`」） |
| `outcome_branch` | `"claude/issue-<番号>"` | 必ず渡す（下記「`outcome_branch`」）。渡さないとセッション一覧で "Other" に落ちる |
| `source_revision` | 渡さない（**`review-dialogue` フローのときだけ `"claude/issue-<番号>"`**） | 既定でデフォルトブランチ。レビューは実装済みブランチを起点にする（→ [レビューの払い出し](#レビューの払い出し)） |
| `environment_id` | 渡さない | 親セッションの環境を継承する |

プレフィックスの付け方: プラグイン配布のスキルは Skill ツールの名前が `<プラグイン名>:<フロー語>`（例: `mattpocock-skills:tdd`、
`dev-workflow:review-dialogue`）。短縮形（`tdd`）は解決しない。**`prompt` を `/` や `<system-reminder>` タグで始めない**
—— `create_session` が拒む。文章で始め、スキルは「Skill ツールで発動する」と言葉で指す。

### モデル割り当て

**既定は `claude-opus-5-5`。下の例外表に載っている語だけが `claude-sonnet-5-5` になる。**

| フロー語 | `model` | sonnet 側に置く理由 |
|---|---|---|
| `tdd` | `claude-sonnet-5-5` | 仕様は issue にあり、赤→緑の手を動かす比率が高い |
| `wizard` | `claude-sonnet-5-5` | 人が踏む手順のスクリプト化。判断は人側 |
| `research` | `claude-sonnet-5-5` | 一次情報の収集と転記が主 |
| `prototype` | `claude-sonnet-5-5` | 捨てる前提の試作 |
| `resolving-merge-conflicts` | `claude-sonnet-5-5` | 機械的な突合が主 |
| `triage` | `claude-sonnet-5-5` | ラベル付けと分類 |
| 上記以外すべて | `claude-opus-5-5` | —— |

**リポ固有スキルの行は `docs/agents/ccw-dispatch.md` の `## モデル表に足す行` で足す**（実験を回すだけのスキルを
sonnet にする等）。足していないリポ固有スキルは、既定の opus になる。

方針は **「判断の質がそのまま成果になる作業は opus、手を動かす比率が高い作業は sonnet」**。opus 側は既定なので
**表に載せない** —— 列挙式（表に載っている語だけ払い出せる）にすると、スキルが増えるたびに表の保守が要る
（→ [判断 0005](https://github.com/hayato1980/claude-skills/blob/main/docs/decisions/0005-model-follows-whether-errors-surface-immediately.md)）。
opus に残る語の例: `review-dialogue` / `grilling` / `grill-with-docs` / `diagnosing-bugs` / `domain-modeling` /
`issue-inventory` / `codebase-design`。

**`review-dialogue` は opus から動かさない。** 実装と**別モデル**で差分を読み直すことが
[判断 0001](https://github.com/hayato1980/claude-skills/blob/main/docs/decisions/0001-review-runs-in-a-separate-session-and-model.md)
の核心そのものなので、コスト削減の対象にしない。**`tdd` を sonnet に落とせるのは、その差分を必ず opus の
レビューが読み直すから**で、レビューの払い出しをやめるなら `tdd` の行も opus に戻すこと。

**表を編集する人へ: sonnet 側に Haiku を置かない。** CCW の子は auto mode で走り、auto mode は Haiku に
対応していないので、指定すると子が Manual に落ちて許可待ちで止まる。使える幅は opus ↔ sonnet だけ。

**モデル名の直指定（`sonnet` / `opus` / `haiku`）は受け付けない。** 受け付けると固定割り当てが抜け道つきになり、
さらに悪いことに**割り当て表が実態に合わなくなってもその場で回避できてしまうので、表の劣化に気づけない**。
表が実態に合っていないと思ったら、回避せず表を直す。

**割り当ての単位はセッションの入口フローであって、中で走るスキルではない。** `model` は `create_session` の
引数、つまりセッション全体への一括指定である。したがって `tdd` で払い出した子は、内部で何を呼ぼうとセッション
全体が `claude-sonnet-5-5` で走り続ける。「実装は安い側、レビューは opus」を成立させるには**セッションを分ける**
しかない（→ [レビューの払い出し](#レビューの払い出し)）。CCW ではスキル frontmatter の `model:` は効かない
（`create_session` の `model` はセッション作成時にモデルを決める別の口）。

モデル ID は数ヶ月単位で差し替わりうる。`create_session` がエラーを返したら現行の ID をシステムプロンプトの
モデル一覧で確認し、この表を更新する。

### prompt に足さないもの

上の表の `prompt` の形（1 文）で完結する。issue 本文の要約・`gh` CLI が使えない旨・作業ブランチの
起点・draft PR の作り方は、いずれも**子セッション側で `CLAUDE.md` とハーネスが供給する**ので、prompt に重ねて
書くと無効な指示が残るだけになる。

### 呼び出し例

実装を払い出す（`/create-ccw-session #683 tdd`）:

```
create_session(
  title:          "#683 [tdd] feat(skill): issue を CCW セッションへ払い出すスキルを作る",
  tags:           ["tdd", "issue-683", "skill"],
  prompt:         "issue #683 に取り組む。Skill ツールで `mattpocock-skills:tdd` を引数 `#683` で発動する。",
  model:          "claude-sonnet-5-5",  // tdd は例外表の sonnet 側
  source_url:     "<ccw-dispatch.md の source_url>",
  outcome_branch: "claude/issue-683",
)
```

そのレビューを払い出す（`/create-ccw-session #683 review-dialogue`）:

```
create_session(
  title:           "#683 [review-dialogue] feat(skill): issue を CCW セッションへ払い出すスキルを作る",
  tags:            ["review-dialogue", "issue-683", "skill"],
  prompt:          "issue #683 に取り組む。Skill ツールで `dev-workflow:review-dialogue` を引数 `#683` で発動する。",
  model:           "claude-opus-5-5",
  source_url:      "<ccw-dispatch.md の source_url>",
  source_revision: "claude/issue-683",
  outcome_branch:  "claude/issue-683",
)
```

---

## レビューの払い出し

放っておくと、レビューは**実装したセッションの自己レビュー 1 本**しか無い —— 差分を読むのが実装したのと同じ
セッション・同じコンテキスト・同じモデルになり、第三者性が構造的に無い。**レビューを別セッションに払い出すのは、
この第三者性を CI の枠を使わずに手に入れるため**（→ [判断 0001](https://github.com/hayato1980/claude-skills/blob/main/docs/decisions/0001-review-runs-in-a-separate-session-and-model.md)）。

そのため、**払い出された実装セッションは自分では `/code-review` を回さない。** 止めないと安いモデルの自己レビューが
先に走り、その指摘を反映した状態で commit されてしまい、「レビューは opus」が半分しか効かない。これを hook で
止めないのは、**同じリポジトリの hook をレビュー用の子も読むので、レビューのために払い出した子まで止まる**ため。

**止めているのは上流 `/mattpocock-skills:code-review` であって、それを包む `/review-dialogue` を自分で呼んでも
同じ自己レビューが成立してしまう。** `review-dialogue` の器は中身に上流をそのまま呼ぶので、どちらの語で呼んでも
読むのは同じセッション・同じモデルになる。

**`claude/issue-<番号>` ブランチで PR を作った実装セッション（払い出された子）は、PR を作ったらレビューの払い出し
（＝別セッションの `create_session` 呼び出し）を自分自身で行う。** フロー語は `tdd` に限らない（`diagnosing-bugs` /
`grill-with-docs` 等も同じ）。禁止しているのは自己レビュー（`/review-dialogue` を自分の会話内で実行すること）
であって、**レビューを行う別セッションを起動すること**は別の操作なので区別する。`claude/issue-<番号>` 以外のブランチで PR を作る
セッション（ふつうの直接作業）は、引き続きオーナーが `/create-ccw-session #NNN review-dialogue` で手動払い出しする。

レビュー払い出しの要点:

- **フロー語は `review-dialogue`。** `prompt` は上の表の形で、スキル名は `dev-workflow:review-dialogue`（呼び出し例を参照）。
  `code-review` という語は**上流スキルの名前としてのみ残る**（器がその上流を内側で呼ぶ）。
- `source_revision` に `claude/issue-<番号>` を渡す（実装済みブランチを起点にする）。**これを渡すのは
  `review-dialogue` フローだけ**で、`revision` は、同じ issue のセッションが複数あるときにレビュー側を見分けるのに使う（候補の取り方は `issue-<番号>` タグ + 自分の除外。→ [runbook](../review-dialogue/runbook.md)「ラウンドの閉じ方」手順 1）。
- `outcome_branch` も同じ `claude/issue-<番号>`。
- **レビュー側は push しない。** 指摘は PR 上のスレッドとして投稿し、**直すのは修正側**（＝その PR を作ったセッション）。
  両者は全スレッドが解決するまで往復する（→ [runbook](../review-dialogue/runbook.md)）。読むだけのレビューにしないのは、
  人が指摘を転記する手間がかかり「誰が直すのか」が宙に浮くため。往復では**指摘の妥当性に査読者がつく**
  （レビュー側が自分で直すと、その指摘が正しいかを誰も見ないまま commit される）。
- 差分の基準点は**毎回 merge-base**。「前回レビュー以降」は追わない（前回どこまで読んだかはリポジトリのどこにも書かれていない）。

**親は払い出した子の往復を監視しない。** [手順 7](#手順) の「進捗の監視はしない」が禁じているのはそれであって、
**自分が作った PR への応答ではない**。オーナーがこのセッションで直接実装して PR を作り、レビューだけを払い出した
場合、**修正側はこのセッション自身**になる（役割はセッションの出自ではなく PR に対する立場に宿る）。

### issue を持たない PR のレビュー払い出し

オーナーが直接作業で作った PR（head がハーネスの乱数のブランチ名で `claude/issue-<番号>` 型でない）は、
[自動払い出し](#pr-作成後の自動レビュー払い出し)の対象外なので、オーナーが `#<PR番号>` を渡して手で払い出す。
引数が issue か PR かは、`mcp__github__issue_read` の結果に `pull_request` があるかで決める（GitHub は PR も同じ番号で issue として返す）。
PR のときの `create_session` の引数は次のとおり。ほかは上の表と同じ。

| 引数 | 値 |
|---|---|
| `title` | `PR #<番号> [review-dialogue] <PR タイトル逐語>` |
| `tags` | `["review-dialogue", "pr-<PR番号>", "<第 3 要素>"]`（第 3 要素は上の表と同じ決め方） |
| `prompt` | ``PR #<PR番号> に取り組む。Skill ツールで `dev-workflow:review-dialogue` を引数 `#<PR番号>` で発動する。`` — 読み替えの指示は書かない |
| `source_revision` / `outcome_branch` | PR の **head ブランチ名**そのもの（`pull_request_read` で読む） |

**修正側は、その PR を作ったセッション。** `issue-<番号>` タグを持たないので、往復の「相手を引く」は `pr-<PR番号>` タグで引く
（→ [runbook](../review-dialogue/runbook.md)「ラウンドの閉じ方」手順 1）。`pr-<PR番号>` タグは `session-closeout` の束ねの対象にもなる。

### PR 作成後の自動レビュー払い出し

**head が `claude/issue-<番号>` の PR を作ったセッション**（払い出された子は `outcome_branch` でこのブランチに push
するので必ず該当する）は、`claude/issue-<番号>` への push と draft PR 作成を終えたら、オーナーの指示を
待たずに**自分自身で** review-dialogue セッションを払い出す。

1. `list_sessions(mine=true, limit=100)` を引き、[runbook](../review-dialogue/runbook.md)「ラウンドの閉じ方」手順 1 の
   **「相手を引く」と同じ読み方**（保存ファイルに書き、`grep | jq` で、アーカイブ済みを除いて読む）で、既存の
   review-dialogue セッションが無いか確認する。**`tags` のフロー語では判定しない。**
   `tags` に `issue-<番号>` を含み、アーカイブ済みでなく、**自分自身
   （除き方は [runbook](../review-dialogue/runbook.md)「ラウンドの閉じ方」手順 1。環境変数と行の `id` は接頭辞が違う）
   を除いた**行を候補とする。自分（修正側）も同じ `issue-<番号>` タグを持つので、自分を除かないと自分自身を
   「既に走っている」と誤判定して払い出しをスキップしてしまう。
   候補が 0 行なら払い出す（手順 2 へ）。1 行以上なら、候補ごとに `get_session(session_id)` で
   `session_context.sources[0].git_repository.revision` を読む（`list_sessions` の行では欠けるが `get_session`
   では読める）。
   - `claude/issue-<番号>` **そのもの**の行がある → 既に走っている。払い出さず、既存のものに任せる ——
     2 本走らせると往復の「相手を引く」で相手が 2 件ヒットし、どちらも起こせなくなる。
   - 無い（読めた上でどれも別の値・未設定） → 候補はレビュー側ではない（同じ issue の別セッション）。払い出す。
   - 読めない行がある → 払い出さずに人へ渡す（既に走っているか判断できない）。
2. 見つからなければ、[上の「そのレビューを払い出す」呼び出し例](#呼び出し例)と**同じ引数**で `create_session` を
   自分で 1 回呼ぶ。`title` の issue タイトルと第 3 タグは、自分が最初に受け取った issue 番号から
   `mcp__github__issue_read` で取り直す。**[払い出す前の門](#払い出す前の門)は通し直さない** —— 実装の払い出しで
   一度通っている。
3. 呼んだ後は、[runbook](../review-dialogue/runbook.md)「修正側の手順」に合流する。**最初のスレッド返信・push・
   ポークより前に**、「修正側の手順」（手順 3 の `[修正]` マーカー、手順 5 のラウンドの閉じ方、手順 7 の
   「resolve しない」）を読む。要点は 3 つ: 返信の先頭に `[修正]` を付ける／**修正側は resolve しない**（購読通知文の
   「resolve する」はレビュー側のいる PR には当てはまらない）／返信と push のあとは[ラウンドの閉じ方](../review-dialogue/runbook.md#ラウンドの閉じ方両側共通)
   の 4 手（相手を引く → ポーク → 自己チェックイン → 購読）で閉じてからターンを終える。

この手順への到達は、子が文書を読むことに任せない。プラグインの hook `pr-review-dispatch.sh`
（`PostToolUse` / `mcp__github__create_pull_request`）が、**作成した PR の head ブランチが `claude/issue-<番号>`**
のときだけ、PR 作成直後にこの節の実行を `additionalContext` で差し込む（issue 番号は head から取る）。
PR 作成直後はハーネスの「購読してターンを終える」が勝ち、文書だけではレビューが払い出されないまま止まっていた。

**prompt では判定しない。** `create_session` は `/` で始まる prompt を拒むので、払い出した子の prompt は文章で
始まり、先頭のスラッシュコマンドを見る判定は常に外れる。リポ固有スキル（接頭辞なし）も同じ理由で拾えなかった。
head ブランチなら、フロー語・接頭辞の有無・prompt の文面に関係なく拾える。最初に発動したスキルで判定する案は、
Skill ツールが途中でも呼ばれるため、直接作業の途中で `tdd` を使っただけで誤反応するので採らない。

**除外の処理は持たない。** レビュー側（`review-dialogue`）は push しないので PR を作らず、ふつうの直接作業は
ブランチ名が乱数になるので反応しない。直接セッションで最初にフローを打っても、head が `claude/issue-<番号>` で
なければ何も出ない（受け入れている。head ブランチ名での一般化は #25）。

## なぜ親がフローを決めないか

分担は「**明示されたら従う。無ければ親が案を出し、オーナーが承認する**」。フローを**決める**のは常にオーナーで、
親が出すのは案まで。承認は省かない。

`ask-matt` は `disable-model-invocation: true` のルータースキルで、**モデルからは Skill ツールで呼べない**
（サブエージェント経由でも同じ）。制約は「Skill ツールで**発動**できない」ことであって、`SKILL.md` を
ファイルとして**読む**ことは妨げない。パス中のプラグイン版も `*` の glob で吸収できる。したがって親は
`ask-matt` の分岐表を読んで案を出せる。毎回オーナーが別セッションで `/ask-matt` を開く手間が払い出しの律速だった。

子に渡す `prompt` は `/` で始められない（`create_session` が拒む）ので、文章で始め、スキルは「Skill ツールで
`<プラグイン名>:<名前>` を発動する」と言葉で指す。プラグイン配布のスキルは接頭辞込みの名前が正しい名前である。

## `source_url`

`source_url` を省略しても、`environment_id` の継承で親の環境が持つソース定義ごと引き継がれ、リポジトリは正しく
クローンされる。**それでも明示的に渡す**（意図がセッションの記録に残るため）。

**クローンされていないと疑ったとき、セッションを破棄する前に必ず `mcp__claude-code-remote__get_session` を呼び、
`session_context.sources` にリポジトリの URL が入っているか確かめる。** `source_url` 未指定を理由に「リポジトリを
対象にしていないのでは」と疑って起動し直しかけたが、`get_session` で確認したところ正しくクローンされて既に
着手済みだった、という実例がある。確認せず破棄していれば、進んでいた作業をそのまま捨てていた。

## `outcome_branch`

セッション一覧のグルーピングキーは `session_context.sources`（クローン元）ではなく
**`session_context.outcomes`**（成果物の置き場）で、これが空のセッションは紐づけ先が無く **"Other"** に落ちる。
`outcomes` は**セッション作成時に `outcome_branch` からのみ埋まる**ので、渡さずに払い出した子は、ブランチを push して
PR をマージしても "Other" のまま変わらない。

ブランチ名は issue 番号から機械的に `claude/issue-<番号>` とする。`outcome_branch` を指定するとハーネスの自動
サフィックス（ランダム 6 文字）が付かず、この名前にそのまま push される。

**裏返せば、同じブランチへ同時に 2 つ push する子を走らせるとブランチを取り合う。** 取り合いになるのは
**両方が push する**ときであって、同時に走っていること自体ではない。**レビューの払い出しは取り合いにならない。
レビュー側が push しないため**（→ [レビューの払い出し](#レビューの払い出し)）。往復では修正側のセッションが
払い出し後も生きたままレビュー側と**並走**し、指摘の修正を同じ `claude/issue-<番号>` へ push する —— これは往復の
前提であって、禁止事項ではない。禁じられるのは、**同じ issue に push する子を 2 つ同時に走らせること**
（例: `tdd` で払い出した子が走っている最中に、もう一度 `tdd` で払い出す）。

## 払い出したあと

必要になったときに使うツール。定期的に見に行く運用はしない。

| やること | ツール |
|---|---|
| 進捗を見る | `mcp__claude-code-remote__get_session`（`task_summary`） |
| 追加指示を送る | `mcp__claude-code-remote__send_message` |
| 止める | `mcp__claude-code-remote__interrupt_session` |
| 終わったセッションを片付ける | `mcp__claude-code-remote__archive_session`（知見の着地と後続の払い出しを済ませてから） |
| 払い出し済み・往復の相手を引く | `mcp__claude-code-remote__list_sessions`。**`mine=true`, `limit=100` で引き、保存されたファイルを `grep \| jq` で読み、返ってきた各行の `tags` を自分で突き合わせる。** 作法の正準は [runbook](../review-dialogue/runbook.md)「ラウンドの閉じ方」手順 1 |

**`list_sessions` の `tags` 引数では絞り込めない。** この引数は OAuth caller 専用で、セッションの中から呼ぶとエラーに
なる。**払い出し時に `tags` を付けているのはこのスキルなので、引く側が何を頼りにするかはここの責任範囲にある。**
突き合わせの作法そのもの（`limit`・ページ送り・アーカイブ済みの除外・複数ヒットの決め方）は runbook が正準で、
ここには書き写さない —— 往復の両側が毎ラウンド相手を引く以上、規則が 2 箇所にあると割れる。

払い出した issue は子に任せ、**親はこのセッションで別の作業に移る**。同じ issue の修正を親でも進めると、子の変更と
衝突する。同じ領域の issue を同時に払い出すと、2 つの子が同じファイルを別々に直して衝突しうる。同時払い出しは
領域をばらす。
