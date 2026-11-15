"""draft_return_comment.sh: 「赤い PR を draft に戻す」ときの PR コメント本文。

本文は draft 化の成否（DRAFT_RESULT）に必ず連動させる。戻せていないのに「戻しました」と
書くと、draft 状態が唯一のマージゲートのリポでは素通りが見えなくなる。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / ".github" / "actions" / "draft-return-comment" / "draft_return_comment.sh"

CONVERTED_CLAIM = "draft に戻しました"
GATE_IS_OPEN_WARNING = "マージゲートが効いていません"

CHECKS = "install=success\nlint tool=success\ntest=failure"


def run(**env: str) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": "/usr/bin:/bin",
        "JOB_NAME": "gate",
        "JOB_RESULT": "failure",
        "CHECKS": CHECKS,
        "RUN_URL": "https://example.invalid/runs/1",
    }
    return subprocess.run(["bash", str(SCRIPT)], env={**base, **env}, capture_output=True, text=True, check=False)


def test_failed_conversion_does_not_claim_success_and_warns_the_gate_is_open() -> None:
    proc = run(DRAFT_RESULT="failure")
    assert proc.returncode == 0, proc.stderr
    assert CONVERTED_CLAIM not in proc.stdout
    assert GATE_IS_OPEN_WARNING in proc.stdout


def test_successful_conversion_claims_it_and_explains_how_to_rerun() -> None:
    proc = run(DRAFT_RESULT="success")
    assert proc.returncode == 0, proc.stderr
    assert CONVERTED_CLAIM in proc.stdout
    assert GATE_IS_OPEN_WARNING not in proc.stdout
    assert "再度 Ready for review" in proc.stdout


def test_skipped_conversion_means_no_token_and_is_not_a_surprise() -> None:
    """トークン未登録で戻す操作自体をしなかったとき。想定内の値なので stderr は静か。"""
    proc = run(DRAFT_RESULT="skipped")
    assert proc.returncode == 0, proc.stderr
    assert CONVERTED_CLAIM not in proc.stdout
    assert GATE_IS_OPEN_WARNING in proc.stdout
    assert "トークン" in proc.stdout
    assert proc.stderr == ""


def test_unknown_result_still_produces_a_body_and_names_the_value() -> None:
    for value in ("", "cancelled"):
        proc = run(DRAFT_RESULT=value)
        assert proc.returncode == 0, proc.stderr
        assert CONVERTED_CLAIM not in proc.stdout
        assert GATE_IS_OPEN_WARNING in proc.stdout
        assert "DRAFT_RESULT" in proc.stderr
        if value:
            assert value in proc.stdout


def test_table_lists_every_check_in_the_given_order_with_the_run_url() -> None:
    for result in ("success", "failure"):
        out = run(DRAFT_RESULT=result).stdout
        rows = [line for line in out.splitlines() if line.startswith("| `")]
        assert rows == ["| `install` | success |", "| `lint tool` | success |", "| `test` | failure |"]
        assert "gate" in out and "https://example.invalid/runs/1" in out


def test_empty_outcome_is_shown_as_not_run() -> None:
    """タイムアウトで打ち切られると未到達ステップの outcome は空になる。理由なしに戻さない。"""
    out = run(DRAFT_RESULT="success", CHECKS="a=success\nb=", JOB_RESULT="cancelled").stdout
    assert "| `a` | success |" in out
    assert "| `b` | 実行されていない |" in out


def test_no_checks_still_produces_a_body() -> None:
    proc = run(DRAFT_RESULT="success", CHECKS="")
    assert proc.returncode == 0, proc.stderr
    assert CONVERTED_CLAIM in proc.stdout
    assert "| `" not in proc.stdout


def test_note_is_appended_and_retry_note_replaces_the_default() -> None:
    out = run(DRAFT_RESULT="success", NOTE="手元で再現: make test", RETRY_NOTE="独自の復帰手順").stdout
    assert "手元で再現: make test" in out
    assert "独自の復帰手順" in out
    assert "再度 Ready for review" not in out


def test_retry_guidance_is_absent_when_the_pr_could_not_be_converted() -> None:
    """すでに ready の PR に「再度 Ready にしろ」と案内すると、ready_for_review が発火しない。"""
    out = run(DRAFT_RESULT="failure").stdout
    assert "再度 Ready for review にすると" not in out


def test_job_and_run_url_are_required() -> None:
    for missing in ("JOB_NAME", "RUN_URL"):
        env = {"PATH": "/usr/bin:/bin", "JOB_NAME": "g", "RUN_URL": "u", "DRAFT_RESULT": "success"}
        del env[missing]
        proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
        assert proc.returncode != 0 and missing in proc.stderr
