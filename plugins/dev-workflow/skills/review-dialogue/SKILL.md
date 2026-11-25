---
name: review-dialogue
description: "払い出された `mattpocock-skills:code-review`（Standards / Spec の 2 軸レビュー）を包み、その所見を PR 上のスレッドへ着地させて修正側との往復を成立させるレビュー側の器。create-ccw-session のレビュー払い出しが、prompt で Skill ツールにこのスキルを引数 `#NNN` で発動させる。「#NNN のレビューを走らせて」でも発動。"
argument-hint: "#NNN"
---

Use this skill when: acting as the review side of a payout for issue #NNN. The upstream `mattpocock-skills:code-review` skill only reads the diff and reports Standards / Spec findings back into the conversation — it has no notion of GitHub, PRs, or the requirement that every finding become its own resolvable review thread. This skill is the layer between that upstream output and the PR: it pins the fixed point so the upstream skill never has to ask, then turns the aggregated report into one GitHub review thread per finding.

対象: $ARGUMENTS

## 発動トリガー

- Skill ツールで `dev-workflow:review-dialogue` を引数 `#NNN` で発動（`create-ccw-session` がレビュー払い出しの prompt で「Skill ツールで発動する」と指示する。`create_session` は `/` で始まる prompt を拒むので、スラッシュ形では呼ばれない → [`create-ccw-session`](../create-ccw-session/SKILL.md)「レビューの払い出し」）
- 「#NNN を review-dialogue に出して」「#NNN のレビューを走らせて」

このスキルは**レビュー側**として動く。往復の作法（ラウンドの閉じ方・相手が来ないとき・resolve と ready 化・マージがレビュー側の専権であること等）はすべて [`runbook.md`](./runbook.md) が正準。本 SKILL.md はそこへ二重に書かない。

リポ固有の設定（オーナーマージの基準表・CI が走る条件・push 前に流すコマンド）は、対象リポの
`docs/agents/review-dialogue.md` に置く。runbook は実行時にそれを読む。**無ければ、基準表を推測せず、マージに進む前に止まってユーザーに聞く。**

## 前提

対象の実装ブランチ（issue なら `claude/issue-<番号>`、issue を持たない PR ならその head ブランチ名）が `source_revision` としてチェックアウド済み（→ `create-ccw-session` の「レビューの払い出し」）。このブランチを `head` とする open PR が対象。

## 手順

### 1. merge-base を確定する

```bash
git fetch origin main
git merge-base HEAD origin/main
```

差分の基準点は**毎回この merge-base**（→ [判断 0001](https://github.com/hayato1980/claude-skills/blob/main/docs/decisions/0001-review-runs-in-a-separate-session-and-model.md)）。「前回レビュー以降」は追わない —— 前回どこまで読んだかはリポジトリのどこにも書かれていない。デフォルトブランチが `main` でないリポでは、そのブランチ名に読み替える。

### 2. 対象 PR を特定する

引数 `#<番号>` は issue 番号と PR 番号のどちらでもよい。`mcp__github__issue_read` で引き、結果に `pull_request` があれば**その番号が PR**（head ブランチ名は `pull_request_read` で読む）。無ければ issue なので、`head` が `claude/issue-<番号>` の open PR を GitHub 側で探す（`mcp__github__list_pull_requests`）。

### 3. 上流 `mattpocock-skills:code-review` を呼ぶ

```
Skill(skill="mattpocock-skills:code-review", args="<手順 1 の merge-base SHA>。Standards の基準文書として <standards.md の絶対パス> も読むこと")
```

**`<standards.md の絶対パス>` は、このスキルを読み込んだときに示される base directory に `standards.md` を足して組み立てる。** このスキルはプラグインのキャッシュから読み込まれ、利用側のリポには `standards.md` が無い。上流が「リポを探す」手順では見つからず、SKILL.md からの相対パス（`./standards.md`）も利用側の作業ディレクトリからは解決できないので、**絶対パスで渡す**。渡し口は args の 1 つだけ。パスだけを args に足すと上流は spec の候補と取り違えるため、**「Standards の基準文書として」と役割を文に書く**。中身は上流にも SKILL.md にも写さない。

**手順 1 で確定した基準点を渡した状態で呼ぶ。** 上流の Process 手順 1 は「基準点の指定が無ければユーザーに聞く」だが、人のいない子セッションはここで止まりうる。基準点を渡すことで、その分岐に一度も入らせない。

**上流の手順をこの SKILL.md にコピーしない。** Standards / Spec の 2 軸の判定基準・Fowler smell baseline・sub-agent の起動は上流が持つ唯一の正本で、コピーは上流が更新されても静かに旧版のまま走る。

### 4. 所見を `.scratch/` へ構造化ファイルとして書き出す

上流が `## Standards` / `## Spec` で返した所見を、**1 指摘 = 1 項目**の構造化ファイルへ変換して書く。

```
.scratch/review-issue-<番号>.md
```

各項目に最低限次を持たせる —— 手順 5 でそのまま 1 thread の投稿に写せる粒度にする。

- `axis`: `Standards` か `Spec`
- `file`: 該当ファイルパス
- `line`: 行に紐づく指摘のみ持たせる（紐づかなければ省略し、手順 5 で `subjectType=FILE` として扱う）
- `body`: 投稿本文。先頭に役割マーカー `[レビュー]` を含める（→ [役割マーカー](./runbook.md#3-本文の先頭に役割マーカーを置く)）

**このファイルの書き出しを、投稿より先の完了条件にする。** 書き出しを終えるまで手順 5 へ進まない —— 投稿が途中で失敗しても、同じセッションがこのファイルを読み直して続きから投稿し直せるようにするため。投稿という副作用の前に完了条件を 1 つ置く効果もある。`.scratch/` は `.gitignore` に入れておく（レビュー側は push しないのでこのファイル自体が commit されることはないが、念のため）。

### 5. ファイルを読み、1 指摘 = 1 thread で投稿する

手順 4 のファイルを読み、指摘ごとに 1 thread を作る。

```
mcp__github__pull_request_review_write(method="create", ...)      # pending review を作る
mcp__github__add_comment_to_pending_review(...)                   # 指摘ごとに 1 回
mcp__github__pull_request_review_write(method="submit_pending", event="COMMENT", ...)
```

具体の作法（`subjectType` の使い分け・`event` は `COMMENT` のみである理由・PR 本体コメントを指摘に使わない理由）は [`runbook.md`](./runbook.md)「レビュー側の手順」2〜3 が正準。

### 6. 購読と自己チェックインを張る

投稿を終えたら、**両側共通の**[「ラウンドの閉じ方」](./runbook.md#ラウンドの閉じ方両側共通)（相手を引く → ポーク → 自己チェックインを張り直す → 購読する）をそのまま実行してターンを終える。以降の往復（修正側の返信への応答・resolve・ready 化・決裂 / 打ち切り）もすべて同じ runbook の「レビュー側の手順」に従う。

### 7. 合意したらマージまで進める（`needs-owner-merge` は除く）

全スレッドが resolved になったら、runbook の[「7. 合意 —— マージまで進める」](./runbook.md#7-合意--マージまで進める)を実行する。分岐の要点だけ書く（基準表・失敗時の扱いの正本は runbook）。

- **マージ前に毎回、差分を見てオーナーマージ対象かを判定する。** 触ったファイルではなく、マージで本番の振る舞いや決定が変わるかで判定し、`docs/agents/review-dialogue.md` の基準表の行と差分の該当箇所を**名指しできるときだけ** `needs-owner-merge` を付ける（「迷ったら付ける」はしない。前例もたどらない）。外すことはしない（外せるのはオーナーだけ）。
- **表に無い中身の判断待ち**（issue がオーナー判断とした差分・受け入れ条件の未達など）はラベルにせず、draft のまま `[レビュー] オーナー判断待ち` と `ready-for-human` で人へ渡す（runbook 7-1）。
- **`needs-owner-merge` 付き** → `scripts/ci/ready_wait_merge.sh --no-merge <PR番号>`（バックグラウンド・単独）で ready 化し、**CI の結果を見届けて**マージせずに止まる。赤なら draft に戻して往復へ（runbook 7-2a）。
- **それ以外** → ready 化の前に `mergeable_state` を見て、`dirty` なら ready にせず下の CI 赤と同じく修正側へ返す。そうでなければ `scripts/ci/ready_wait_merge.sh <PR番号>` を**バックグラウンドで**、**先頭に `bash` を付けず、ほかのコマンドと `&&` でつながず単独で**起動し（許可ルールに一致させるため）、green ならマージまで。auto mode の権限判定で拒否されたら迂回せず、runbook 7-2b の表どおり人へ渡す。CI が赤、またはマージ時にコンフリクト（`405 not mergeable`）なら**自分で draft に戻し**、失敗を指摘スレッドとして投稿して往復に戻る。**原因の判断と修正は修正側の仕事**（→ runbook [修正側の手順 4](./runbook.md#4-ci-赤マージコンフリクトを自分で直す)）なので、レビュー側は直さない。
- 購読とチェックインを落とすのは、マージ（または ready 化後の CI green）を確認してから。
