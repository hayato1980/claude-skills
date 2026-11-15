"""session-closeout スキルの機械的な部分（対象を束ねて「終わっているか」を判定する）。

`list_sessions` は MCP ツールでしか呼べないので、エージェントはそれを呼んで結果ファイルを渡すだけにし、
archive 済みの除外・自分自身の除外・issue ごとの束ね・役割判定・PR と issue の状態取得・判定表の適用は
ここで行う（→ skills/session-closeout/SKILL.md）。会話を読む手順以降はエージェントに残す。
"""
