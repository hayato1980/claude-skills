"""再利用ワークフロー・composite action の結線。公開リポから非公開リポが呼ぶ前提で固定する。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RETURN = WORKFLOWS / "return-to-draft.yml"
CHECK_ACTION = REPO_ROOT / ".github" / "actions" / "check-agent-headings" / "action.yml"
COMMENT_ACTION = REPO_ROOT / ".github" / "actions" / "draft-return-comment" / "action.yml"

SLIM_LIMIT = 15


def load(path: Path) -> dict[Any, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(doc: dict[Any, Any]) -> dict[str, Any]:
    return doc.get("on", doc.get(True))  # PyYAML は `on` を True に読む


def job() -> dict[str, Any]:
    return load(RETURN)["jobs"]["return-to-draft"]


def step(name: str) -> dict[str, Any]:
    return next(s for s in job()["steps"] if s.get("name") == name)


def test_return_to_draft_is_reusable_and_takes_the_token_as_a_named_optional_secret() -> None:
    on = triggers(load(RETURN))
    assert list(on) == ["workflow_call"]
    assert on["workflow_call"]["secrets"]["draft_token"]["required"] is False
    assert not on["workflow_call"]["inputs"]["job-name"].get("required"), "複数ジョブの呼び出し側が job-name を決めなくてよい"


def test_no_workflow_or_action_uses_secrets_inherit() -> None:
    """公開リポのワークフローを非公開リポが呼ぶ。必要なものだけを明示して渡す。"""
    for path in [*WORKFLOWS.glob("*.yml"), CHECK_ACTION, COMMENT_ACTION]:
        assert "inherit" not in path.read_text(encoding="utf-8"), path.name


def test_job_permissions_are_the_minimum() -> None:
    assert job()["permissions"] == {"pull-requests": "write"}


def test_slim_runner_timeout_stays_within_the_slim_cap() -> None:
    """slim は上限超の timeout-minutes を黙って打ち切る。宣言を嘘にしない。"""
    if job()["runs-on"] == "ubuntu-slim":
        assert job()["timeout-minutes"] <= SLIM_LIMIT


def test_conversion_is_attempted_only_with_a_token_and_never_stops_the_comment() -> None:
    """secrets は step の if から読めない。有無は job の env に落として見る。トークン無しで失敗扱いにしない。"""
    convert = step("Convert PR back to draft")
    assert convert["continue-on-error"] is True
    assert "HAS_TOKEN" in convert["if"]
    assert "secrets.draft_token" in job()["env"]["HAS_TOKEN"]
    assert "secrets.draft_token" not in convert["if"]
    assert "secrets.draft_token" in convert["env"]["GH_TOKEN"]
    assert "github.token" not in convert["env"]["GH_TOKEN"], "GITHUB_TOKEN では draft に戻せない"


def test_comment_gets_the_real_conversion_outcome_but_not_the_pat() -> None:
    comment = step("Comment the reason")
    assert comment["if"] == "always()"
    assert comment["with"]["draft-result"] == "${{ steps.convert.outcome }}"
    assert "draft_token" not in str(comment)


def test_job_goes_red_when_not_converted() -> None:
    last = job()["steps"][-1]
    assert "steps.convert.outcome" in last["if"] and "success" in last["if"]


def test_workflow_never_hardcodes_the_converted_claim() -> None:
    assert "draft に戻しました" not in RETURN.read_text(encoding="utf-8")


def test_check_action_is_composite_and_runs_the_script_from_its_own_path() -> None:
    action = load(CHECK_ACTION)
    assert action["runs"]["using"] == "composite"
    text = CHECK_ACTION.read_text(encoding="utf-8")
    assert "github.action_path" in text and "agent-headings.json" in text
    for s in action["runs"]["steps"]:
        assert "${{" not in s.get("run", ""), "入力を run に直接展開しない（env 経由）"


def test_comment_action_is_composite_and_expands_no_input_inside_run() -> None:
    action = load(COMMENT_ACTION)
    assert action["runs"]["using"] == "composite"
    for s in action["runs"]["steps"]:
        assert "${{" not in s.get("run", ""), "入力を run に直接展開しない（env 経由）"


def test_workflow_tells_callers_not_to_pin_it_to_anything_but_main() -> None:
    """中の composite action は @main で呼ぶ。固定した呼び出し側が、action の入力の変更で壊れる。"""
    text = RETURN.read_text(encoding="utf-8")
    assert "@main` で参照すること" in text
    assert "@main" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    inner = [s["uses"] for s in job()["steps"] if "uses" in s]
    assert all(u.endswith("@main") for u in inner), "action の参照先を変えたら、上の注意書きも直す"


def test_workflow_call_descriptions_contain_no_template_expression() -> None:
    """description は式を書ける場所ではない。`${{` を書くと workflow ごと invalid になりうる。"""
    declared = triggers(load(RETURN))["workflow_call"]
    for group in ("inputs", "secrets"):
        for name, spec in declared[group].items():
            assert "${{" not in str(spec.get("description", "")), f"{group}.{name}"
    for path in (CHECK_ACTION, COMMENT_ACTION):
        for name, spec in load(path)["inputs"].items():
            assert "${{" not in str(spec.get("description", "")), f"{path.parent.name}.{name}"
