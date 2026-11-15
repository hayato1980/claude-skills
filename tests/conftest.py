"""共有テストの定数と補助。ネットワークにも GitHub にも触れない。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "lib"
PLUGIN = REPO_ROOT / "plugins" / "dev-workflow"
SCRIPTS = PLUGIN / "scripts"
HOOKS = PLUGIN / "hooks"
TEMPLATES = PLUGIN / "templates"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # jq が無い環境で黙って緑にしない: 全件 skip ではなく明示的に失敗させる。
    if shutil.which("jq") is None:
        raise pytest.UsageError("jq が必要です（スクリプトも hook も jq に依存する）")
