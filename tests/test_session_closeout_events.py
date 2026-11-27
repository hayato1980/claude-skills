"""`session_closeout events`: list_events の保存ファイルから assistant の文と result を時系列に出す。"""

from __future__ import annotations

import sys

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

from pathlib import Path

import pytest

from session_closeout.__main__ import main

DUMP = Path(__file__).parent / "fixtures" / "list_events_dump.txt"


def test_prints_assistant_text_and_result_in_order(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["events", str(DUMP)]) == 0
    assert capsys.readouterr().out.splitlines() == ["first reply", "second reply", "[result success is_error=false] final text"]


def test_unreadable_file_fails_with_its_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("no json here\n", encoding="utf-8")
    assert main(["events", str(bad)]) == 1
    assert str(bad) in capsys.readouterr().err


def test_plain_json_without_the_saved_file_wrapper_is_read_too(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plain = tmp_path / "plain.json"
    plain.write_text('{"ccr":{"data":[{"result":{"internal_anthropic_catchall":{"subtype":"success","is_error":true,"result":"x"}}}]}}',
                     encoding="utf-8")
    assert main(["events", str(plain)]) == 0
    assert capsys.readouterr().out.strip() == "[result success is_error=true] x"
