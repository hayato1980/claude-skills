"""lib/sync-wizard-core.sh: 写しの作成と、ずれの検出。ネットワークは使わない
（WIZARD_CORE_SOURCE_DIR に共有版を見立てたディレクトリを渡す）。"""
import os
import shutil
import subprocess
from pathlib import Path

from conftest import LIB


def sync(dest: Path, *args: str, source: Path = LIB):
    env = {**os.environ, "WIZARD_CORE_SOURCE_DIR": str(source)}
    return subprocess.run(
        ["bash", str(dest / "sync-wizard-core.sh"), *args],
        capture_output=True, text=True, env=env,
    )


def make_consumer(tmp_path: Path) -> Path:
    dest = tmp_path / "consumer" / "scripts" / "lib"
    dest.mkdir(parents=True)
    shutil.copy(LIB / "sync-wizard-core.sh", dest)
    # 利用側の最初の取り込み。2 行目に印が入る。
    r = sync(dest, "update")
    assert r.returncode == 0, r.stderr
    return dest


def test_update_writes_copies_with_origin_marker(tmp_path):
    dest = make_consumer(tmp_path)
    second = (dest / "wizard-core.sh").read_text().splitlines()[1]
    assert second.startswith("# synced-from: hayato1980/claude-skills@")
    assert second.endswith(" lib/wizard-core.sh")


def test_check_passes_right_after_update(tmp_path):
    dest = make_consumer(tmp_path)
    r = sync(dest, "check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_fails_when_one_character_of_core_copy_changes(tmp_path):
    dest = make_consumer(tmp_path)
    core = dest / "wizard-core.sh"
    core.write_text(core.read_text().replace("Stage", "Stagf", 1))
    r = sync(dest, "check")
    assert r.returncode != 0
    assert "Stagf" in r.stdout


def test_check_fails_when_sync_script_copy_changes(tmp_path):
    dest = make_consumer(tmp_path)
    s = dest / "sync-wizard-core.sh"
    s.write_text(s.read_text() + "# drift\n")
    assert sync(dest, "check").returncode != 0


def test_check_fails_without_origin_marker(tmp_path):
    dest = make_consumer(tmp_path)
    core = dest / "wizard-core.sh"
    lines = core.read_text().splitlines(keepends=True)
    del lines[1]
    core.write_text("".join(lines))
    r = sync(dest, "check")
    assert r.returncode != 0
    assert "synced-from" in r.stderr


def test_check_fails_when_shared_source_cannot_be_read(tmp_path):
    dest = make_consumer(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sync(dest, "check", source=empty).returncode != 0


def test_unknown_subcommand_is_usage_error(tmp_path):
    dest = make_consumer(tmp_path)
    assert sync(dest, "bogus").returncode == 2


def test_check_fails_when_sync_script_marker_sha_differs(tmp_path):
    dest = make_consumer(tmp_path)
    s = dest / "sync-wizard-core.sh"
    lines = s.read_text().splitlines(keepends=True)
    lines[1] = lines[1].replace("@", "@deadbeef", 1)
    s.write_text("".join(lines))
    r = sync(dest, "check")
    assert r.returncode != 0
    assert "sync-wizard-core.sh" in r.stderr


def test_check_fails_when_marker_filename_is_rewritten(tmp_path):
    dest = make_consumer(tmp_path)
    core = dest / "wizard-core.sh"
    core.write_text(core.read_text().replace(" lib/wizard-core.sh", " lib/other.sh", 1))
    assert sync(dest, "check").returncode != 0


def test_check_detects_trailing_blank_line_changes(tmp_path):
    dest = make_consumer(tmp_path)
    core = dest / "wizard-core.sh"
    core.write_text(core.read_text() + "\n")
    assert sync(dest, "check").returncode != 0


def test_check_passes_when_shared_version_ends_with_blank_line(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    for n in ("wizard-core.sh", "sync-wizard-core.sh"):
        (shared / n).write_text((LIB / n).read_text() + "\n")
    dest = tmp_path / "consumer"
    dest.mkdir()
    shutil.copy(LIB / "sync-wizard-core.sh", dest)
    assert sync(dest, "update", source=shared).returncode == 0
    assert sync(dest, "check", source=shared).returncode == 0


def test_update_leaves_no_temp_files_on_failure(tmp_path):
    dest = make_consumer(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sync(dest, "update", source=empty).returncode != 0
    assert list(dest.glob("*.tmp")) == []


def test_update_marks_local_source_with_a_valid_looking_sha(tmp_path):
    dest = make_consumer(tmp_path)
    second = (dest / "wizard-core.sh").read_text().splitlines()[1]
    assert __import__("re").search(r"@[0-9a-f]{40} ", second)
