"""judge_gate_checks.sh の判定検証。

ready_wait_merge.sh がポーリングで取った check-runs JSON をファイルで受け取り、
「マージしてよいか」だけを終了コードで返す継ぎ目を検証する。
ブロッキングジョブ名は環境変数 GATE_BLOCKING_JOBS（空白区切り）で受ける。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "judge_gate_checks.sh"
OK, NG, PENDING, USAGE = 0, 1, 2, 3


def run(*args: str, jobs: str | None = "gate") -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "GATE_BLOCKING_JOBS"}
    if jobs is not None:
        env["GATE_BLOCKING_JOBS"] = jobs
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False, env=env)


def check_run(name: str, *, conclusion: str | None = "success", status: str = "completed", rid: int = 1) -> dict[str, Any]:
    return {"id": rid, "name": name, "status": status, "conclusion": conclusion, "html_url": f"https://example.invalid/{rid}"}


def write(tmp_path: Path, runs: list[dict[str, Any]]) -> Path:
    path = tmp_path / "check-runs.json"
    path.write_text(json.dumps({"check_runs": runs}), encoding="utf-8")
    return path


class TestVerdict:
    def test_success_is_ok(self, tmp_path: Path) -> None:
        assert run(str(write(tmp_path, [check_run("gate")]))).returncode == OK

    def test_failure_is_ng_and_names_the_job(self, tmp_path: Path) -> None:
        proc = run(str(write(tmp_path, [check_run("gate", conclusion="failure", rid=7)])))
        assert proc.returncode == NG
        assert "gate: failure https://example.invalid/7" in proc.stdout

    def test_skipped_is_ng_not_success(self, tmp_path: Path) -> None:
        assert run(str(write(tmp_path, [check_run("gate", conclusion="skipped")]))).returncode == NG

    def test_in_progress_is_pending(self, tmp_path: Path) -> None:
        runs = [check_run("gate", conclusion=None, status="in_progress")]
        assert run(str(write(tmp_path, runs))).returncode == PENDING

    def test_not_yet_appeared_is_pending(self, tmp_path: Path) -> None:
        assert run(str(write(tmp_path, [check_run("unrelated")]))).returncode == PENDING

    def test_unrelated_failure_is_ignored(self, tmp_path: Path) -> None:
        runs = [check_run("gate"), check_run("other", conclusion="failure", rid=2)]
        assert run(str(write(tmp_path, runs))).returncode == OK


class TestJobNamesWithSpaces:
    def test_name_with_spaces_is_one_job(self, tmp_path: Path) -> None:
        runs = [check_run("test (3.13)")]
        assert run(str(write(tmp_path, runs)), jobs="test (3.13)").returncode == OK

    def test_newline_separates_jobs(self, tmp_path: Path) -> None:
        runs = [check_run("test (3.13)", rid=1), check_run("lint", conclusion="failure", rid=2)]
        proc = run(str(write(tmp_path, runs)), jobs="test (3.13)\nlint")
        assert proc.returncode == NG
        assert "lint: failure" in proc.stdout


class TestMultipleBlockingJobs:
    def test_all_must_succeed(self, tmp_path: Path) -> None:
        runs = [check_run("lint", rid=1), check_run("test", rid=2)]
        assert run(str(write(tmp_path, runs)), jobs="lint\ntest").returncode == OK

    def test_ng_wins_over_pending(self, tmp_path: Path) -> None:
        runs = [check_run("lint", conclusion="failure", rid=1), check_run("test", conclusion=None, status="queued", rid=2)]
        assert run(str(write(tmp_path, runs)), jobs="lint\ntest").returncode == NG

    def test_one_pending_one_ok_is_pending(self, tmp_path: Path) -> None:
        runs = [check_run("lint", rid=1), check_run("test", conclusion=None, status="queued", rid=2)]
        assert run(str(write(tmp_path, runs)), jobs="lint\ntest").returncode == PENDING


class TestDuplicateRunsAndBaseline:
    def test_latest_run_wins(self, tmp_path: Path) -> None:
        runs = [check_run("gate", conclusion="skipped", rid=1), check_run("gate", rid=9)]
        assert run(str(write(tmp_path, runs))).returncode == OK

    def test_latest_failure_is_reported_once(self, tmp_path: Path) -> None:
        runs = [check_run("gate", rid=1), check_run("gate", conclusion="failure", rid=9)]
        proc = run(str(write(tmp_path, runs)))
        assert proc.returncode == NG
        assert proc.stdout.count("gate:") == 1

    def test_stale_success_at_or_below_baseline_is_pending(self, tmp_path: Path) -> None:
        assert run(str(write(tmp_path, [check_run("gate", rid=5)])), "5").returncode == PENDING

    def test_run_above_baseline_is_judged(self, tmp_path: Path) -> None:
        assert run(str(write(tmp_path, [check_run("gate", rid=6)])), "5").returncode == OK

    def test_non_numeric_baseline_is_usage_error(self, tmp_path: Path) -> None:
        assert run(str(write(tmp_path, [check_run("gate")])), "abc").returncode == USAGE


class TestUsage:
    def test_missing_blocking_jobs_is_usage_error(self, tmp_path: Path) -> None:
        proc = run(str(write(tmp_path, [check_run("gate")])), jobs=None)
        assert proc.returncode == USAGE
        assert "GATE_BLOCKING_JOBS" in proc.stderr

    def test_no_argument(self) -> None:
        assert run().returncode == USAGE

    def test_missing_file(self, tmp_path: Path) -> None:
        assert run(str(tmp_path / "nope.json")).returncode == USAGE

    def test_malformed_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        assert run(str(bad)).returncode == USAGE

    @pytest.mark.parametrize("body", ['{"message": "Bad credentials"}', '{"check_runs": {"a": 1}}', '{"check_runs": [1, 2]}'])
    def test_api_error_shapes_are_usage_not_ng(self, tmp_path: Path, body: str) -> None:
        # トークン失効のエラー応答を「CI red」と誤読させない。
        path = tmp_path / "x.json"
        path.write_text(body)
        assert run(str(path)).returncode == USAGE
