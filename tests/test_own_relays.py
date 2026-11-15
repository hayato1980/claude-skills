"""このリポ自身に置いた中継（scripts/ci/*.sh）が、配布する雛形（templates/）と一致しているか。

雛形を直したのにこのリポのコピーが古いまま残ると、自分の PR のマージゲートだけ旧版で走る。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "plugins" / "dev-workflow" / "templates"
RELAYS = sorted((ROOT / "scripts" / "ci").glob("*.sh"))


def test_relays_exist() -> None:
    assert {p.name for p in RELAYS} == {"ready_wait_merge.sh", "session_closeout.sh"}


@pytest.mark.parametrize("relay", RELAYS, ids=lambda p: p.name)
def test_relay_matches_template(relay: Path) -> None:
    assert relay.read_bytes() == (TEMPLATES / relay.name).read_bytes()


@pytest.mark.parametrize("relay", RELAYS, ids=lambda p: p.name)
def test_relay_is_executable(relay: Path) -> None:
    assert os.access(relay, os.X_OK)
