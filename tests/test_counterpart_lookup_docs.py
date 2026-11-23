"""#30: 往復の相手・既存レビュー側は issue タグで引き、自分を除く（revision は絞り込み専用）。"""
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "plugins" / "dev-workflow" / "skills"

# 手順を書いた節だけを切り出す（他の節の言及に影響されないように）
SECTIONS = {
    "review-dialogue/runbook.md": ("### 1. 相手を引く", "### 2. 相手を起こす"),
    "create-ccw-session/SKILL.md": ("### PR 作成後の自動レビュー払い出し", "この手順への到達"),
    "retro-closeout/SKILL.md": ("**レビュー側の会話も読む。**", "- retro の手順 4"),
}


def section(rel: str) -> str:
    start, end = SECTIONS[rel]
    text = (SKILLS / rel).read_text(encoding="utf-8")
    i = text.index(start)
    return text[i : text.index(end, i)]


def test_lookup_excludes_self_by_session_id_env() -> None:
    for rel in SECTIONS:
        assert "CLAUDE_CODE_REMOTE_SESSION_ID" in section(rel), rel


def test_lookup_does_not_require_revision_as_primary_criterion() -> None:
    # revision は list_sessions の行で欠けるため、「すべて満たす」条件に入れない
    for rel in SECTIONS:
        s = section(rel)
        assert "絞り込み" in s, rel
        assert "欠け" in s or "未設定" in s, rel
