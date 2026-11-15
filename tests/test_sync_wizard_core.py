"""lib/sync-wizard-core.sh: 写しの作成と、ずれの検出。ネットワークは使わない
（WIZARD_CORE_SOURCE_DIR に共有版を見立てたディレクトリを渡す）。"""
import os
import shutil
import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"


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
