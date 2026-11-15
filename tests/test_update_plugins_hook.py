"""hooks/update-plugins.sh の検証（SessionStart でプラグイン自身を更新する hook）。

`claude` を stub に差し替え、呼び出しの順序・ロック・fail-soft だけを見る。ネットワークには出ない。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from conftest import HOOKS

HOOK = HOOKS / "update-plugins.sh"

STUB_CLAUDE = """\
#!/usr/bin/env bash
echo "$*" >> "${STUB_LOG}"
if [ -n "${STUB_FAIL_ON:-}" ] && [ "$*" = "${STUB_FAIL_ON}" ]; then
  exit 1
fi
exit 0
"""


def run(
    tmp_path: Path, *, with_claude: bool = True, fail_on: str = "", config: str | None = None,
    foreground: bool = True, extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    project = tmp_path / "project"
    (project / "docs" / "agents").mkdir(parents=True, exist_ok=True)
    if config is not None:
        (project / "docs" / "agents" / "plugin-update.md").write_text(config, encoding="utf-8")
    log = tmp_path / "calls.log"
    if with_claude:
        stub = bindir / "claude"
        stub.write_text(STUB_CLAUDE)
        stub.chmod(0o755)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PROJECT_DIR": str(project),
        "STUB_LOG": str(log),
        "STUB_FAIL_ON": fail_on,
        "DEV_WORKFLOW_PLUGIN_UPDATE_LOCK": str(tmp_path / "update.lock"),
        "DEV_WORKFLOW_PLUGIN_UPDATE_LOG": str(tmp_path / "update.log"),
        **({"DEV_WORKFLOW_PLUGIN_UPDATE_FOREGROUND": "1"} if foreground else {}),
        **(extra_env or {}),
    }
    proc = subprocess.run(["bash", str(HOOK)], input="{}", env=env, capture_output=True, text=True, check=False)
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


CONFIG = """\
# 設定

## 更新するプラグイン

- `alpha-skills@alpha`
- `dev-workflow@hayato`

## 別の節

- `ignored@ignored`
"""


def test_default_updates_only_this_plugin_and_never_adds_or_installs(tmp_path: Path) -> None:
    proc, calls = run(tmp_path)
    assert proc.returncode == 0
    assert calls == ["plugin marketplace update hayato", "plugin update dev-workflow@hayato"]


def test_targets_come_from_the_consumer_config_in_order(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, config=CONFIG)
    assert proc.returncode == 0
    assert calls == [
        "plugin marketplace update alpha",
        "plugin update alpha-skills@alpha",
        "plugin marketplace update hayato",
        "plugin update dev-workflow@hayato",
    ]


def test_config_without_the_section_falls_back_to_default(tmp_path: Path) -> None:
    _, calls = run(tmp_path, config="# 設定\n\n## 別の節\n\n- `x@y`\n")
    assert calls == ["plugin marketplace update hayato", "plugin update dev-workflow@hayato"]


def test_marketplace_update_failure_still_updates_the_plugin(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, config=CONFIG, fail_on="plugin marketplace update alpha")
    assert proc.returncode == 0
    assert "plugin update alpha-skills@alpha" in calls
    assert calls[-1] == "plugin update dev-workflow@hayato"


def test_update_failure_still_exits_zero_and_continues(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, config=CONFIG, fail_on="plugin update alpha-skills@alpha")
    assert proc.returncode == 0
    assert calls[-1] == "plugin update dev-workflow@hayato"


def test_no_claude_cli_is_a_noop(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, with_claude=False)
    assert proc.returncode == 0
    assert calls == []


def test_skip_env_is_a_noop(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, extra_env={"DEV_WORKFLOW_SKIP_PLUGIN_UPDATE": "1"})
    assert proc.returncode == 0
    assert calls == []


def test_second_run_is_skipped_while_lock_is_held(tmp_path: Path) -> None:
    lock = tmp_path / "update.lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "5"])
    try:
        deadline = time.monotonic() + 5
        while not lock.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.2)
        proc, calls = run(tmp_path)
    finally:
        holder.kill()
        holder.wait()
    assert proc.returncode == 0
    assert calls == []


def test_default_mode_detaches_to_background_and_logs(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, foreground=False)
    assert proc.returncode == 0
    log = tmp_path / "calls.log"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and len(log.read_text().splitlines() if log.exists() else []) < 2:
        time.sleep(0.05)
    assert log.read_text().splitlines() == ["plugin marketplace update hayato", "plugin update dev-workflow@hayato"]
    assert "背景で起動" in proc.stderr


def test_hooks_json_registers_session_start() -> None:
    hooks = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
    commands = [h["command"] for entry in hooks["SessionStart"] for h in entry["hooks"]]
    assert commands == ["${CLAUDE_PLUGIN_ROOT}/hooks/update-plugins.sh"]
    assert os.access(HOOK, os.X_OK)
