# claude-skills

複数プロジェクトで共有する Claude Code のスキルを配るプラグインマーケットプレイス。
ここを直せば、有効化している全プロジェクトに効く。

## 収録プラグイン

| プラグイン | 中身 |
|---|---|
| `dev-workflow` | プロジェクト非依存の開発ワークフロー。スキル 6 本（`issue-inventory` / `review-dialogue` / `create-ccw-session` / `ready-merge` / `session-closeout` / `retro-closeout`）と hook 3 本（`pr-review-dispatch` / `deny-mattpocock-implement` / `update-plugins`）、マージゲートのスクリプト（`ready_wait_merge.sh` / `judge_gate_checks.sh`） |

## 導入する

ユーザー設定（`~/.claude/settings.json`）に追記する（mattpocock/skills と並べて書ける）。

```jsonc
{
  "extraKnownMarketplaces": {
    "hayato": { "source": { "source": "github", "repo": "hayato1980/claude-skills" } }
  },
  "enabledPlugins": {
    "dev-workflow@hayato": true
  }
}
```

- **リポの `.claude/settings.json` に書くだけでは入らない**（追跡下の設定ではプラグインが有効化されない）。各自のユーザー設定に書くか、下記のクラウド環境の Setup script で入れる。
- クラウド（Claude Code on the web）は、環境の **Setup script** 欄に次を足す。

  ```bash
  claude plugin marketplace add hayato1980/claude-skills || true
  claude plugin install dev-workflow@hayato || true
  ```

  Setup script は環境のスナップショットを作るときにしか走らないので、**このリポジトリへの変更はすぐには届かない**（Setup script・許可ホストの変更か、約7日の期限切れでスナップショットが作り直されたとき）。早く届けるため、プラグイン自身が SessionStart hook（`update-plugins`）で `marketplace update` → `plugin update` を背景で走らせる（反映は次の claude プロセスから。ログは `/tmp/dev-workflow-plugin-update.log`）。起動は新しい claude プロセスの開始時（`startup`）だけ。`marketplace add` / `install` はしないので、初回の導入は上の Setup script が担う。利用側が止めたいときは環境変数 `DEV_WORKFLOW_SKIP_PLUGIN_UPDATE=1`。
- ローカルは `/plugin marketplace update hayato` で更新する。
- `plugin.json` に `version` をあえて書かない（書くと版を上げ忘れた変更が配られない。無ければコミット単位で更新される）。

## プロジェクト固有の情報の置き場

スキル本文にはプロジェクト固有の情報（リポジトリ名・パス・ホスト名・業務ドメインの語）を書かない。
**このリポジトリは公開**なので、秘密・内部ホスト名・**非公開リポジトリの名前**も書かない。ファイルだけでなく、コミットメッセージ・プルリクの本文・コメントも同じ。

固有の情報は各プロジェクトの `docs/agents/*.md` に置き、スキルは実行時にそれを読む
（mattpocock/skills と同じ規約）。

スキル 1 つにつき 1 ファイル。**見出しは共有スキルとの契約**で、スキルは実行時にその見出しを読む（見出しを変えると壊れる）。

| ファイル | 読むスキル | 契約する見出しと中身 |
|---|---|---|
| `docs/agents/issue-tracker.md` | 全般 | 課題管理先（GitHub の owner/repo、使うツール）、tracker に書くコメントの署名・定型 |
| `docs/agents/triage-labels.md` | `issue-inventory` | triage ラベルの対応表。棚卸しで除外するラベル・子セッションへ払い出せないラベル・評価の補正 |
| `docs/agents/review-dialogue.md` | `review-dialogue` | `## オーナーマージの基準表`（基準・当たる・当たらない）／`## CI が走る条件`／`## push 前に流すコマンド` |
| `docs/agents/pr-merge-gate.md` | `ready-merge`・`ready_wait_merge.sh` | `## CI で止めるジョブ`（`- \`ジョブ名\`` の箇条書き。**無い・空ならマージしない**）<br>任意: `## ready 前に実行するコマンド`（`- \`コマンド\`` の箇条書き。draft → ready 化の前に書いた順に実行し、失敗したら ready にしない。**見出しが無ければ何もしない・見出しがあって空ならエラー**） |
| `docs/agents/ccw-dispatch.md` | `create-ccw-session` | `## 払い出しを止めるラベル`／`## タグの決め方`／`## モデル表に足す行`／`## source_url` |
| `docs/agents/dev-workflow.md` | `deny-mattpocock-implement` hook | `## /implement` の下に `止める: はい`（または `いいえ`）。無ければ止めない |
| `docs/agents/plugin-update.md` | `update-plugins` hook | `## 更新するプラグイン` の下に `- \`プラグイン名@マーケットプレイス名\`` の箇条書き。**`dev-workflow@hayato` 自身は常に更新し、書いた一覧はそこに足される**（他のプラグインを更新したいときだけ書く。無ければ自身だけ） |

**表の「任意」の 2 種類（`plugins/dev-workflow/agent-headings.json` のキー）**: 見出しチェックは、表の見出しをすべて「あること」として求める。例外は 2 つで、混同しないこと。

- `optional: true`（ファイル単位）: **ファイル自体が無くてよい**。ファイルがあるなら、その `headings` はすべて要る。
- `optional_headings`（見出し単位）: **ファイルはあるが、その見出しは無くてよい**。後から足した見出しで、まだ書いていない利用側リポの CI を落とさないため。無ければスキルは何もしない（例: `pr-merge-gate.md` の `## ready 前に実行するコマンド`）。

### 各リポの CI から呼ぶもの

| 何を | どう呼ぶか |
|---|---|
| `docs/agents/*.md` の見出しチェック | 既存のジョブの 1 ステップとして `uses: hayato1980/claude-skills/.github/actions/check-agent-headings@main`（先に checkout しておく。ジョブを増やさないので分単位の切り上げが増えない）。使っていないスキルのファイルは `with: ignore: docs/agents/xxx.md` で外す |
| 赤い PR を draft に戻して表でコメント | ジョブごと `uses: hayato1980/claude-skills/.github/workflows/return-to-draft.yml@main`。`with:` に `job-name` / `job-result` / `checks`（`名前=結果` を 1 行 1 件）、`secrets:` に `draft_token`（PR を draft 化できる PAT / App のトークン）だけを名指しで渡す。呼び出し側のジョブに `permissions: pull-requests: write` が要る。トークン未登録なら戻す操作はせず、コメントで「戻せていない」と伝えてジョブを赤にする |

**`return-to-draft.yml` は `@main` で参照すること**（sha やタグで固定しない）。中で呼ぶ composite action も `@main` なので、workflow だけを古い ref に固定すると、main での action の入力・本文の変更で壊れる、または挙動が黙って変わる。

見出しの照合は**行の完全一致**（行末の空白・CR は不一致）。スキル側が行の完全一致で読むのと同じ規則にしてある。

必須の見出しの一覧は [`plugins/dev-workflow/agent-headings.json`](./plugins/dev-workflow/agent-headings.json) の 1 か所だけ。スキルを足したり見出しを変えたりしたら一覧も直す（`scripts/ci/check_heading_references.py` が、CI のステップで一覧・この README の表・スキル本文の食い違いを落とす）。

### 各リポに置く中継スクリプト

`scripts/ci/ready_wait_merge.sh` を、プラグインの [`templates/ready_wait_merge.sh`](./plugins/dev-workflow/templates/ready_wait_merge.sh) のままコピーして置く（実行権限つき）。
プラグイン本体の場所を `~/.claude/plugins/installed_plugins.json` から探して呼ぶだけで、ロジックは持たない。
許可ルール `Bash(scripts/ci/ready_wait_merge.sh*)` が固定のパスを指す必要があるため、中継を残している。
`session-closeout` も同じ形で、[`templates/session_closeout.sh`](./plugins/dev-workflow/templates/session_closeout.sh) を `scripts/ci/session_closeout.sh` に置き、許可ルール `Bash(scripts/ci/session_closeout.sh*)` を足す。対象リポは `git remote origin` から読む（設定ファイルは要らない）。
許可ルールは `bash` を前置しない形で書く（auto mode では `bash …*` の許可ルールが無効になる）。

無ければ、スキルは `git remote -v` などから推測するか、ユーザーに聞いて止まる。

## 判断の記録

手順として今も効いている判断は [`docs/decisions/`](./docs/decisions/)。

## 検証

```bash
claude plugin validate .
python -m pytest tests -q   # jq が必要
```
