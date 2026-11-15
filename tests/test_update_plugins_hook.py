"""hooks/update-plugins.sh の検証（SessionStart でプラグイン自身を更新する hook）。

`claude` を stub に差し替え、呼び出しの順序・ロック・fail-soft だけを見る。ネットワークには出ない。
"""

from __future__ import annotations

import json
import os
import shutil
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
    foreground: bool = True, path: str | None = None, stub: str = STUB_CLAUDE, extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    project = tmp_path / "project"
    (project / "docs" / "agents").mkdir(parents=True, exist_ok=True)
    if config is not None:
        (project / "docs" / "agents" / "plugin-update.md").write_text(config, encoding="utf-8")
    log = tmp_path / "calls.log"
    if with_claude:
        stub_path = bindir / "claude"
        stub_path.write_text(stub)
        stub_path.chmod(0o755)
    env = {
        "PATH": path if path is not None else f"{bindir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PROJECT_DIR": str(project),
        "STUB_LOG": str(log),
        "STUB_FAIL_ON": fail_on,
        "DEV_WORKFLOW_PLUGIN_UPDATE_LOCK": str(tmp_path / "update.lock"),
        "DEV_WORKFLOW_PLUGIN_UPDATE_LOG": str(tmp_path / "update.log"),
        **(extra_env or {}),
    }
    proc = subprocess.run(["bash", str(HOOK), *(["--run"] if foreground else [])], input="{}", env=env, capture_output=True, text=True, check=False)
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


def test_config_list_is_added_to_self_with_marketplaces_deduped(tmp_path: Path) -> None:
    config = CONFIG.replace("- `dev-workflow@hayato`", "- `beta-skills@alpha`")
    proc, calls = run(tmp_path, config=config)
    assert proc.returncode == 0
    assert calls == [
        "plugin marketplace update hayato",
        "plugin marketplace update alpha",
        "plugin update dev-workflow@hayato",
        "plugin update alpha-skills@alpha",
        "plugin update beta-skills@alpha",
    ]


def test_self_is_updated_even_when_config_omits_it_and_is_not_repeated(tmp_path: Path) -> None:
    _, calls = run(tmp_path, config=CONFIG)
    assert calls.count("plugin update dev-workflow@hayato") == 1
    assert calls[0] == "plugin marketplace update hayato"


def test_config_without_the_section_updates_self_only(tmp_path: Path) -> None:
    _, calls = run(tmp_path, config="# 設定\n\n## 別の節\n\n- `x@y`\n")
    assert calls == ["plugin marketplace update hayato", "plugin update dev-workflow@hayato"]


def test_marketplace_update_failure_still_updates_the_plugins(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, config=CONFIG, fail_on="plugin marketplace update alpha")
    assert proc.returncode == 0
    assert calls[-2:] == ["plugin update dev-workflow@hayato", "plugin update alpha-skills@alpha"]


def test_update_failure_still_exits_zero_and_continues(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, config=CONFIG, fail_on="plugin update dev-workflow@hayato")
    assert proc.returncode == 0
    assert calls[-1] == "plugin update alpha-skills@alpha"


def test_lock_fd_is_not_inherited_by_claude(tmp_path: Path) -> None:
    # claude の子が残っても flock を握り続けないこと: stub が fd 9 を開けていたら記録する。
    stub = '#!/usr/bin/env bash\n[ -e /proc/$$/fd/9 ] && echo "fd9-open" >> "${STUB_LOG}"\nexit 0\n'
    _, calls = run(tmp_path, stub=stub)
    assert "fd9-open" not in calls


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


def test_without_setsid_nothing_is_started_and_exit_is_zero(tmp_path: Path) -> None:
    # PATH を claude の stub と bash だけにする（setsid の無い環境）。
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("bash", "dirname", "awk"):
        os.symlink(shutil.which(name) or "", bindir / name)
    proc, calls = run(tmp_path, foreground=False, path=str(bindir))
    assert proc.returncode == 0
    assert calls == []
    assert "setsid が無い" in proc.stderr


def test_hooks_json_registers_session_start() -> None:
    hooks = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
    assert [e["matcher"] for e in hooks["SessionStart"]] == ["startup"]
    commands = [h["command"] for entry in hooks["SessionStart"] for h in entry["hooks"]]
    assert commands == ["${CLAUDE_PLUGIN_ROOT}/hooks/update-plugins.sh"]
    assert os.access(HOOK, os.X_OK)
