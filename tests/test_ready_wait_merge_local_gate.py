"""ready_wait_merge.sh の「ready 前に実行する手元ゲート」の契約。

GitHub には触れない: READY_MERGE_GH_API で向き先を手元の偽 API サーバ（http.server）に差し替え、
受けたリクエストを記録して「ready 化・マージ・コメントが呼ばれたか」で検査する。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "ready_wait_merge.sh"
PR = 7
GATE_DOC_WITH_COMMANDS = "## CI で止めるジョブ\n\n- `gate`\n\n## ready 前に実行するコマンド\n\n{commands}\n"
GATE_DOC_WITHOUT_COMMANDS = "## CI で止めるジョブ\n\n- `gate`\n"


@dataclass
class FakeGitHub:
    """偽の GitHub API。受けたリクエストを `requests` に (method, path, body) で残す。"""

    head_sha: str
    draft: bool = True
    comment_status: int = 201
    conclusion: str = "success"
    requests: list[tuple[str, str, str]] = field(default_factory=list)
    _check_runs_calls: int = 0

    def calls(self, method: str, suffix: str) -> list[str]:
        return [body for m, path, body in self.requests if m == method and path.endswith(suffix)]

    @property
    def ready_calls(self) -> int:
        return len(self.calls("POST", "/graphql"))

    @property
    def merge_calls(self) -> int:
        return len(self.calls("PUT", f"/pulls/{PR}/merge"))

    @property
    def comments(self) -> list[str]:
        return [json.loads(body)["body"] for body in self.calls("POST", f"/issues/{PR}/comments")]

    def respond(self, method: str, path: str) -> tuple[int, object]:
        if method == "GET" and path == f"/repos/acme/widgets/pulls/{PR}":
            return 200, {"state": "open", "merged": False, "draft": self.draft, "node_id": "N", "head": {"sha": self.head_sha}}
        if method == "GET" and path.startswith(f"/repos/acme/widgets/commits/{self.head_sha}/check-runs"):
            self._check_runs_calls += 1
            # draft の最初の 1 回は baseline 取得（run 無し）。以後は baseline より新しい成功 run を返す。
            if self.draft and self._check_runs_calls == 1:
                return 200, {"check_runs": []}
            run = {"id": 5, "name": "gate", "status": "completed", "conclusion": self.conclusion, "html_url": "u"}
            return 200, {"check_runs": [run]}
        if method == "POST" and path == "/graphql":
            return 200, {"data": {"markPullRequestReadyForReview": {"pullRequest": {"number": PR, "isDraft": False}}}}
        if method == "POST" and path == f"/repos/acme/widgets/issues/{PR}/comments":
            return self.comment_status, {"id": 1}
        if method == "PUT" and path == f"/repos/acme/widgets/pulls/{PR}/merge":
            return 200, {"merged": True}
        return 404, {"message": "unexpected"}


@pytest.fixture
def fake_github(repo: Path) -> Iterator[tuple[FakeGitHub, str]]:
    state = FakeGitHub(head_sha=local_head(repo))

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else ""
            state.requests.append((self.command, self.path, body))
            status, payload = state.respond(self.command, self.path.split("?")[0])
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = _handle

        def log_message(self, *_args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def local_head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """GATE_DOC を未設定で持つ、コミット済みの偽の利用側リポジトリ。"""
    path = tmp_path / "repo"
    (path / "docs" / "agents").mkdir(parents=True)
    git(path.parent, "init", "-q", str(path))
    git(path, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    set_gate_doc(path, GATE_DOC_WITHOUT_COMMANDS)
    return path


def set_gate_doc(repo: Path, body: str) -> None:
    (repo / "docs" / "agents" / "pr-merge-gate.md").write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "gate doc", "--allow-empty")


def run_script(repo: Path, api: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GH_TOKEN": "t", "READY_MERGE_REPO_ROOT": str(repo), "READY_MERGE_GH_API": api}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False, env=env, cwd=repo)


def sync_fake_head_to_local(repo: Path, fake: FakeGitHub) -> None:
    """偽 API が返す PR の head を、手元の HEAD に合わせる（= PR のブランチをチェックアウト済みの状態）。"""
    fake.head_sha = local_head(repo)


class TestLocalGate:
    def test_failing_command_stops_before_ready(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `exit 3`"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR))

        assert proc.returncode != 0
        assert fake.ready_calls == 0
        assert fake.merge_calls == 0

    def test_repo_without_local_gate_config_is_ready_and_merged_as_before(
        self, repo: Path, fake_github: tuple[FakeGitHub, str]
    ) -> None:
        fake, api = fake_github

        proc = run_script(repo, api, str(PR))

        assert proc.returncode == 0, proc.stderr
        assert (fake.ready_calls, fake.merge_calls) == (1, 1)

    def test_passing_commands_run_in_repo_root_in_written_order_then_ready(
        self, repo: Path, fake_github: tuple[FakeGitHub, str]
    ) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `echo one >> ran.log`\n- `echo two >> ran.log`"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR))

        assert proc.returncode == 0, proc.stderr
        assert (repo / "ran.log").read_text().split() == ["one", "two"]
        assert fake.ready_calls == 1

    def test_stops_at_first_failure_and_reports_command_and_exit_code(
        self, repo: Path, fake_github: tuple[FakeGitHub, str]
    ) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `echo first >> ran.log`\n- `exit 42`\n- `echo third >> ran.log`"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR))

        assert proc.returncode != 0
        assert (repo / "ran.log").read_text().split() == ["first"]
        assert "exit 42" in proc.stderr
        assert "42" in proc.stderr

    def test_command_reading_stdin_does_not_swallow_the_commands_after_it(
        self, repo: Path, fake_github: tuple[FakeGitHub, str]
    ) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `cat > /dev/null`\n- `exit 5`"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR))

        assert proc.returncode != 0
        assert fake.ready_calls == 0
        assert "exit 5" in proc.stderr

    def test_head_mismatch_blocks_ready_and_shows_both_shas(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `echo ran >> ran.log`"))
        local_sha = local_head(repo)
        fake.head_sha = "f" * 40  # PR の head は手元と違う

        proc = run_script(repo, api, str(PR))

        assert proc.returncode != 0
        assert fake.ready_calls == 0
        assert not (repo / "ran.log").exists()  # 別のコードを検査して通ることのないよう、コマンドも走らせない
        assert local_sha in proc.stderr and "f" * 40 in proc.stderr
        assert "チェックアウト" in proc.stderr

    def test_uncommitted_changes_block_ready(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `echo ran >> ran.log`"))
        sync_fake_head_to_local(repo, fake)
        (repo / "scratch.txt").write_text("手元だけの変更")

        proc = run_script(repo, api, str(PR))

        assert proc.returncode != 0
        assert fake.ready_calls == 0
        assert not (repo / "ran.log").exists()

    def test_already_ready_pr_does_not_run_the_gate(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        fake.draft = False
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `exit 3`"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR))

        assert proc.returncode == 0, proc.stderr
        assert fake.ready_calls == 0
        assert fake.merge_calls == 1

    def test_heading_without_bullets_blocks_ready(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="書き損じ"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR))

        assert proc.returncode != 0
        assert fake.ready_calls == 0


class TestSkipLocalGate:
    COMMANDS = GATE_DOC_WITH_COMMANDS.format(commands="- `echo ran >> ran.log`")

    @pytest.mark.parametrize("reason_args", [[], [""], ["   "], ["--force"], ["--"]], ids=["absent", "empty", "blank", "dashdash-opt", "dashdash"])
    def test_missing_reason_is_refused_before_any_api_call(
        self, repo: Path, fake_github: tuple[FakeGitHub, str], reason_args: list[str]
    ) -> None:
        fake, api = fake_github
        set_gate_doc(repo, self.COMMANDS)
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR), "--skip-local-gate", *reason_args)

        assert proc.returncode != 0
        assert "--skip-local-gate" in proc.stderr
        assert fake.requests == []
        assert not (repo / "ran.log").exists()

    @pytest.mark.parametrize("order", ["option-first", "pr-first"])
    def test_reason_is_commented_before_ready_and_gate_is_skipped(
        self, repo: Path, fake_github: tuple[FakeGitHub, str], order: str
    ) -> None:
        fake, api = fake_github
        set_gate_doc(repo, self.COMMANDS)
        sync_fake_head_to_local(repo, fake)
        args = ["--skip-local-gate", "別 PR で検査済み", str(PR)] if order == "option-first" else [str(PR), "--skip-local-gate", "別 PR で検査済み"]

        proc = run_script(repo, api, *args)

        assert proc.returncode == 0, proc.stderr
        assert fake.comments == ["[ready-merge] 手元ゲートを省略しました: 別 PR で検査済み"]
        assert not (repo / "ran.log").exists()
        paths = [(m, p.split("?")[0]) for m, p, _ in fake.requests]
        assert paths.index(("POST", f"/repos/acme/widgets/issues/{PR}/comments")) < paths.index(("POST", "/graphql"))

    def test_comment_failure_blocks_ready(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        fake.comment_status = 403
        set_gate_doc(repo, self.COMMANDS)
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR), "--skip-local-gate", "理由")

        assert proc.returncode != 0
        assert fake.ready_calls == 0
        assert "403" in proc.stderr

    def test_already_ready_pr_ignores_the_skip_visibly_and_posts_no_comment(
        self, repo: Path, fake_github: tuple[FakeGitHub, str]
    ) -> None:
        fake, api = fake_github
        fake.draft = False
        set_gate_doc(repo, self.COMMANDS)
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, str(PR), "--skip-local-gate", "理由")

        assert proc.returncode == 0, proc.stderr
        assert fake.comments == []
        assert "--skip-local-gate" in proc.stdout and "無視" in proc.stdout

    def test_repo_without_config_posts_no_comment_and_continues(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github

        proc = run_script(repo, api, str(PR), "--skip-local-gate", "理由")

        assert proc.returncode == 0, proc.stderr
        assert fake.comments == []
        assert "省略するもの" in proc.stdout
        assert (fake.ready_calls, fake.merge_calls) == (1, 1)


class TestNoMerge:
    """--no-merge: ready 化して CI を見届け、green でもマージせずに止める（review-dialogue 7-2a 用）。"""

    def test_green_without_local_gate_config_readies_and_stops_without_merging(
        self, repo: Path, fake_github: tuple[FakeGitHub, str]
    ) -> None:
        # `repo` フィクスチャは手元ゲートの設定（`## ready 前に実行するコマンド`）を持たない = 7-2a が今までと変わらない前提。
        fake, api = fake_github

        proc = run_script(repo, api, "--no-merge", str(PR))

        assert proc.returncode == 0, proc.stderr
        assert (fake.ready_calls, fake.merge_calls) == (1, 0)
        assert "マージせずに止めます" in proc.stdout
        assert "手元ゲート" not in proc.stdout

    def test_red_reports_like_before_and_does_not_merge(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        fake.conclusion = "failure"

        proc = run_script(repo, api, "--no-merge", str(PR))

        assert proc.returncode == 1
        assert "CI red。マージしません。" in proc.stderr
        assert (fake.ready_calls, fake.merge_calls) == (1, 0)

    def test_failing_local_gate_still_stops_before_ready(self, repo: Path, fake_github: tuple[FakeGitHub, str]) -> None:
        fake, api = fake_github
        set_gate_doc(repo, GATE_DOC_WITH_COMMANDS.format(commands="- `exit 3`"))
        sync_fake_head_to_local(repo, fake)

        proc = run_script(repo, api, "--no-merge", str(PR))

        assert proc.returncode != 0
        assert (fake.ready_calls, fake.merge_calls) == (0, 0)
