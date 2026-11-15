# claude-skills

複数プロジェクトで共有する Claude Code のスキルを配るプラグインマーケットプレイス。
ここを直せば、有効化している全プロジェクトに効く。

## 収録プラグイン

| プラグイン | 中身 |
|---|---|
| `dev-workflow` | プロジェクト非依存の開発ワークフロー（`issue-inventory` ほか、順次移行中） |

## プロジェクトで有効化する

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

  Setup script は環境のスナップショットを作るときにしか走らないので、**このリポジトリへの変更はすぐには届かない**（Setup script・許可ホストの変更か、約7日の期限切れでスナップショットが作り直されたとき）。早く届けたいなら、利用側の SessionStart フックで `claude plugin marketplace update hayato` と `claude plugin update dev-workflow@hayato` を走らせる（反映は次の claude プロセスから）。
- ローカルは `/plugin marketplace update hayato` で更新する。
- `plugin.json` に `version` をあえて書かない（書くと版を上げ忘れた変更が配られない。無ければコミット単位で更新される）。

## プロジェクト固有の情報の置き場

スキル本文にはプロジェクト固有の情報（リポジトリ名・パス・ホスト名・業務ドメインの語）を書かない。
**このリポジトリは公開**なので、秘密・内部ホスト名・**非公開リポジトリの名前**も書かない。ファイルだけでなく、コミットメッセージ・プルリクの本文・コメントも同じ。

固有の情報は各プロジェクトの `docs/agents/*.md` に置き、スキルは実行時にそれを読む
（mattpocock/skills と同じ規約）。

| ファイル | 中身 |
|---|---|
| `docs/agents/issue-tracker.md` | 課題管理先（GitHub の owner/repo、使うツール） |
| `docs/agents/triage-labels.md` | triage ラベルの対応表 |

無ければ、スキルは `git remote -v` などから推測するか、ユーザーに聞いて止まる。

## 検証

```bash
claude plugin validate .
```
