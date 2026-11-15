"""中継スクリプト（templates/ready_wait_merge.sh）と ready_wait_merge.sh の結線の契約。

GitHub には触れない: curl を偽物に差し替え、URL とメソッドで応答を返す。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import PLUGIN, TEMPLATES

PR_HEAD = "abc123"


def make_repo(tmp_path: Path, *, gate_doc: str | None = "## CI で止めるジョブ\n\n- `gate`\n") -> Path:
    """中継を scripts/ci/ に置いた偽の利用側リポジトリを作る。"""
    repo = tmp_path / "repo"
    (repo / "scripts" / "ci").mkdir(parents=True)
    shutil.copy(TEMPLATES / "ready_wait_merge.sh", repo / "scripts" / "ci" / "ready_wait_merge.sh")
    (repo / "docs" / "agents").mkdir(parents=True)
    if gate_doc is not None:
        (repo / "docs" / "agents" / "pr-merge-gate.md").write_text(gate_doc, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/widgets.git"], check=True)
    return repo


def make_config_dir(tmp_path: Path, repo: Path, install_path: Path | None) -> Path:
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    plugins: dict[str, list[dict[str, str]]] = {}
    if install_path is not None:
        plugins["dev-workflow@hayato"] = [
            {"scope": "user", "installPath": "/nonexistent"},
            {"scope": "project", "projectPath": str(repo), "installPath": str(install_path)},
        ]
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": plugins}))
    return cfg


def fake_curl(tmp_path: Path, *, check_conclusion: str = "success", draft: bool = False, merge_status: int = 200) -> Path:
    """URL ごとに応答を返す偽 curl。呼ばれたメソッドと URL を calls.log に残す。"""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    pr = {"state": "open", "merged": False, "draft": draft, "node_id": "N", "head": {"sha": PR_HEAD}}
    runs = {"check_runs": [{"id": 5, "name": "gate", "status": "completed", "conclusion": check_conclusion, "html_url": "u"}]}
    script = f"""#!/usr/bin/env bash
method=GET; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -H|-d|-w) shift 2 ;;
    -sS) shift ;;
    *) url="$1"; shift ;;
  esac
done
echo "$method $url" >> "{tmp_path}/calls.log"
case "$method $url" in
  "GET https://api.github.com/repos/acme/widgets/pulls/7") printf '%s\\n200' '{json.dumps(pr)}' ;;
  "GET https://api.github.com/repos/acme/widgets/commits/{PR_HEAD}/check-runs?per_page=100") printf '%s\\n200' '{json.dumps(runs)}' ;;
  "PUT https://api.github.com/repos/acme/widgets/pulls/7/merge") printf '%s\\n{merge_status}' '{{"message":"x"}}' ;;
  *) printf '%s\\n404' '{{"message":"unexpected"}}' ;;
esac
"""
    curl = bindir / "curl"
    curl.write_text(script)
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    return bindir


def run_relay(repo: Path, cfg: Path, tmp_path: Path, *args: str, bindir: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg), "GH_TOKEN": "t", "HOME": str(tmp_path)}
    if bindir:
        env["PATH"] = f"{bindir}:{env['PATH']}"
    return subprocess.run(
        [str(repo / "scripts" / "ci" / "ready_wait_merge.sh"), *args], capture_output=True, text=True, check=False, env=env, cwd=repo
    )


def calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


class TestRelayResolution:
    def test_plugin_not_installed_fails_with_install_hint(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        proc = run_relay(repo, make_config_dir(tmp_path, repo, None), tmp_path, "7")
        assert proc.returncode == 1
        assert "claude plugin install dev-workflow@hayato" in proc.stderr

    def test_missing_installed_json_fails(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        proc = run_relay(repo, tmp_path / "no-such-config", tmp_path, "7")
        assert proc.returncode == 1
        assert "installed_plugins.json" in proc.stderr

    def test_stale_install_path_fails(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        proc = run_relay(repo, make_config_dir(tmp_path, repo, tmp_path / "gone"), tmp_path, "7")
        assert proc.returncode == 1
        assert "見つかりません" in proc.stderr

    def test_project_scope_install_is_preferred_over_user_scope(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        cfg = make_config_dir(tmp_path, repo, PLUGIN)  # user スコープは存在しないパス
        bindir = fake_curl(tmp_path)
        proc = run_relay(repo, cfg, tmp_path, "7", bindir=bindir)
        assert proc.returncode == 0, proc.stderr
        assert "マージしました" in proc.stdout


class TestOrchestrator:
    def test_ready_pr_with_green_gate_is_merged_at_the_judged_sha(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        proc = run_relay(repo, make_config_dir(tmp_path, repo, PLUGIN), tmp_path, "7", bindir=fake_curl(tmp_path))
        assert proc.returncode == 0, proc.stderr
        assert "PUT https://api.github.com/repos/acme/widgets/pulls/7/merge" in calls(tmp_path)

    def test_red_gate_does_not_merge(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        bindir = fake_curl(tmp_path, check_conclusion="failure")
        proc = run_relay(repo, make_config_dir(tmp_path, repo, PLUGIN), tmp_path, "7", bindir=bindir)
        assert proc.returncode == 1
        assert "CI red" in proc.stderr
        assert not any(c.startswith("PUT ") for c in calls(tmp_path))

    def test_merge_conflict_405_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        bindir = fake_curl(tmp_path, merge_status=405)
        proc = run_relay(repo, make_config_dir(tmp_path, repo, PLUGIN), tmp_path, "7", bindir=bindir)
        assert proc.returncode == 1
        assert "405" in proc.stderr

    @pytest.mark.parametrize("doc", [None, "## 使い方\n- `gate`\n"])
    def test_missing_gate_config_refuses_to_merge(self, tmp_path: Path, doc: str | None) -> None:
        # 設定が無いのに「ジョブ 0 個 = 常に green」でマージしてはならない。
        repo = make_repo(tmp_path, gate_doc=doc)
        bindir = fake_curl(tmp_path)
        proc = run_relay(repo, make_config_dir(tmp_path, repo, PLUGIN), tmp_path, "7", bindir=bindir)
        assert proc.returncode != 0
        assert not any(c.startswith("PUT ") for c in calls(tmp_path))

    def test_gate_job_name_comes_from_the_repo_config(self, tmp_path: Path) -> None:
        # check run の名前が設定と違えば、green があっても判定できずタイムアウト側（= マージしない）。
        repo = make_repo(tmp_path, gate_doc="## CI で止めるジョブ\n- `other-job`\n")
        pr_ready = fake_curl(tmp_path)
        # 実時間待ちを避けるため、precheck 経路（ready 済み PR で対象 run が無い）で検証する。
        proc = run_relay(repo, make_config_dir(tmp_path, repo, PLUGIN), tmp_path, "7", bindir=pr_ready)
        assert proc.returncode == 1
        assert "CI run がありません" in proc.stderr
        assert not any(c.startswith("PUT ") for c in calls(tmp_path))
