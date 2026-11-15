"""lib/wizard-core.sh（対話ウィザード共通部）の振る舞いを、実際に bash で走らせて確かめる。

綴りの grep ではなく、標準入力を与えて出力と戻り値を観測する。端末ではない
（パイプ）状態で走らせるので、色と画面クリアは出ない。
"""
import subprocess
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "lib" / "wizard-core.sh"


def run(script: str, stdin: str = "", cwd: Path | None = None):
    """core を source した bash に script を渡す。"""
    prog = f'set -euo pipefail\n. "{CORE}"\n{script}\n'
    return subprocess.run(
        ["bash", "-c", prog], input=stdin, capture_output=True, text=True, cwd=cwd
    )


# ── confirm ──────────────────────────────────────────────────────────────

def test_confirm_yes_returns_success():
    assert run('confirm "go?"', "y\n").returncode == 0
    assert run('confirm "go?"', "Yes\n").returncode == 0


def test_confirm_default_is_no():
    assert run('confirm "go?"', "\n").returncode != 0
    assert run('confirm "go?"', "n\n").returncode != 0


def test_confirm_non_interactive_eof_is_no():
    # 入力が尽きたら「いいえ」。落ちずに戻り値で返す。
    r = run('if confirm "go?"; then echo YES; else echo NO; fi', "")
    assert r.returncode == 0
    assert "NO" in r.stdout


# ── ask ──────────────────────────────────────────────────────────────────

def test_ask_reads_value_into_key():
    r = run('ask NAME "name?"; echo "got=$NAME"', "alice\n")
    assert "got=alice" in r.stdout


def test_ask_enter_keeps_existing_env_value(tmp_path):
    (tmp_path / ".env").write_text("NAME=bob\n")
    r = run('ask NAME "name?"; echo "got=$NAME"', "\n", cwd=tmp_path)
    assert "got=bob" in r.stdout
    assert "[Enter keeps current]" in r.stdout


def test_ask_typed_value_overrides_existing(tmp_path):
    (tmp_path / ".env").write_text("NAME=bob\n")
    r = run('ask NAME "name?"; echo "got=$NAME"', "carol\n", cwd=tmp_path)
    assert "got=carol" in r.stdout


def test_ask_no_remember_ignores_existing(tmp_path):
    (tmp_path / ".env").write_text("NAME=bob\n")
    r = run('ask NAME "name?" --no-remember; echo "got=[$NAME]"', "\n", cwd=tmp_path)
    assert "got=[]" in r.stdout
    assert "Enter keeps" not in r.stdout


def test_ask_unknown_option_aborts():
    r = run('ask NAME "name?" --no-remeber', "x\n")
    assert r.returncode != 0
    assert "--no-remeber" in r.stderr


def test_ask_eof_aborts_instead_of_looping():
    r = run('ask NAME "name?"', "")
    assert r.returncode != 0


def test_ask_secret_reads_value_and_keeps_existing(tmp_path):
    r = run('ask_secret TOKEN "token?"; echo "got=$TOKEN"', "s3cret\n")
    assert "got=s3cret" in r.stdout
    (tmp_path / ".env").write_text("TOKEN=old\n")
    r = run('ask_secret TOKEN "token?"; echo "got=$TOKEN"', "\n", cwd=tmp_path)
    assert "got=old" in r.stdout


def test_ask_secret_does_not_echo_prompt_value_to_stdout():
    r = run('ask_secret TOKEN "token?"', "s3cret\n")
    assert "s3cret" not in r.stdout


# ── write_env / finish / skipped_note ────────────────────────────────────

def test_write_env_upserts_and_is_idempotent(tmp_path):
    (tmp_path / ".env").write_text("A=1\nB=2\n")
    run('write_env B 3; write_env B 4; write_env C 5', cwd=tmp_path)
    assert (tmp_path / ".env").read_text().splitlines() == ["A=1", "B=4", "C=5"]


def test_write_env_creates_file(tmp_path):
    run('write_env K v', cwd=tmp_path)
    assert (tmp_path / ".env").read_text() == "K=v\n"


def test_env_file_override_via_environment(tmp_path):
    target = tmp_path / "custom.env"
    prog = f'ENV_FILE="{target}"\n. "{CORE}"\nwrite_env K v'
    subprocess.run(["bash", "-c", prog], check=True, capture_output=True, cwd=tmp_path)
    assert target.read_text() == "K=v\n"


def test_finish_with_nothing_written_does_not_fail_under_nounset():
    # 1 つも書かずに finish へ着いても落ちない（空の状態を unbound にしない）。
    r = run("finish")
    assert r.returncode == 0
    assert "Setup complete" in r.stdout
    assert "wrote" not in r.stdout


def test_finish_lists_written_keys_and_skipped_items(tmp_path):
    r = run('write_env A 1; write_env B 2; skipped_note "do X"; skipped_note "do Y"; finish',
            cwd=tmp_path)
    assert "wrote 2 value(s)" in r.stdout
    assert "A B" in r.stdout
    assert "still to do by hand" in r.stdout
    assert "- do X" in r.stdout and "- do Y" in r.stdout


# ── stage / banner / abort ───────────────────────────────────────────────

def test_stage_counts_up_against_total():
    r = run('TOTAL_STAGES=3; stage "one"; stage "two"')
    assert "Stage 1/3 · one" in r.stdout
    assert "Stage 2/3 · two" in r.stdout


def test_banner_shows_title_and_stage_count_then_waits():
    r = run('TOTAL_STAGES=4; banner "My Setup"', "\n")
    assert "My Setup" in r.stdout
    assert "4 stages" in r.stdout
    assert "Ready to start?" in r.stdout


def test_abort_writes_reason_to_stderr_and_exits_nonzero():
    r = run('abort "boom"')
    assert r.returncode == 1
    assert "boom" in r.stderr
    assert "boom" not in r.stdout


def test_non_terminal_output_has_no_escape_sequences():
    r = run('stage "s"; say hi; step a; note b; warn c')
    assert "\x1b" not in r.stdout


def test_core_does_not_change_caller_shell_options():
    prog = f'set +e +u\n. "{CORE}"\n[[ $- != *e* && $- != *u* ]] && echo UNCHANGED'
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True)
    assert "UNCHANGED" in r.stdout
