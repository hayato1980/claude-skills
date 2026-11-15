"""session_closeout の中継（templates/session_closeout.sh）と本体の結線の契約。GitHub には触れない。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from conftest import PLUGIN, TEMPLATES


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "ci").mkdir(parents=True)
    shutil.copy(TEMPLATES / "session_closeout.sh", repo / "scripts" / "ci" / "session_closeout.sh")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/widgets"], check=True)
    return repo


def _cfg(tmp_path: Path, install: Path | None) -> Path:
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    plugins = {"dev-workflow@hayato": [{"scope": "user", "installPath": str(install)}]} if install else {}
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": plugins}))
    return cfg


def _run(repo: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg), "GH_TOKEN": "t"}
    return subprocess.run([str(repo / "scripts/ci/session_closeout.sh"), *args], capture_output=True, text=True, env=env, cwd=repo)


def test_plugin_not_installed_fails_with_install_hint(tmp_path: Path) -> None:
    proc = _run(_repo(tmp_path), _cfg(tmp_path, None))
    assert proc.returncode == 1
    assert "claude plugin install dev-workflow@hayato" in proc.stderr


def test_relay_runs_the_plugin_script_against_the_calling_repo(tmp_path: Path) -> None:
    page = tmp_path / "page.json"
    page.write_text(json.dumps({"ccr": {"data": [
        {"id": "s1", "session_status": "SESSION_STATUS_IDLE", "status_bucket": "SESSION_STATUS_BUCKET_COMPLETED",
         "tags": ["issue-4"], "title": "t",
         "session_context": {"sources": [{"git_repository": {"url": "https://github.com/acme/other"}}]}},
    ], "has_more": False, "last_id": "s1"}}))
    proc = _run(_repo(tmp_path), _cfg(tmp_path, PLUGIN), str(page), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    # git remote origin が acme/widgets なので、別リポ acme/other のセッションは対象外になる。
    assert json.loads(proc.stdout)["excluded"][0]["reason"] == "別リポ（https://github.com/acme/other）のセッション"


def test_relay_keeps_cwd_so_relative_result_paths_resolve(tmp_path: Path) -> None:
    # 呼び出し側の cwd がリポの外でも、相対パスの結果ファイルを読め、対象リポは中継が渡す。
    repo = _repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "page.json").write_text(json.dumps({"ccr": {"data": [], "has_more": False, "last_id": None}}))
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(_cfg(tmp_path, PLUGIN)), "GH_TOKEN": "t"}
    proc = subprocess.run(
        [str(repo / "scripts/ci/session_closeout.sh"), "page.json", "--format", "json"],
        capture_output=True, text=True, env=env, cwd=elsewhere,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["bundles"] == []
