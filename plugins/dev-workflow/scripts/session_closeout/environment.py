"""呼び出し環境から読む既定値（自分の session id・対象リポ）。"""

from __future__ import annotations

import os
import subprocess

from .bundles import repo_from_remote_url


def default_self_id() -> str | None:
    # CCR の環境変数は cse_<id>、list_sessions の id は session_<id>（接尾辞が同じ）。
    raw = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID")
    return "session_" + raw.removeprefix("cse_") if raw else None


def default_repo() -> str:
    # 中継が SESSION_CLOSEOUT_REPO_ROOT で対象リポを渡す（cwd は変えない: 結果ファイルの相対パスを保つため）。
    root = os.environ.get("SESSION_CLOSEOUT_REPO_ROOT")
    cmd = ["git", *(["-C", root] if root else []), "remote", "get-url", "origin"]
    try:
        url = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise ValueError(f"git remote origin を読めない（--repo owner/repo で渡す）: {e}") from e
    return repo_from_remote_url(url)
