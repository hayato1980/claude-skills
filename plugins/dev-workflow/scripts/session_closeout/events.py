"""`events`: list_events の保存ファイルから assistant の文と result（ターンの終わり方）を時系列に出す。

`[result <subtype> is_error=<真偽>] <最終テキスト>` の 1 行が result。保存ファイルのラッパー行は読み飛ばす（行番号に頼らない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_KEY = "internal_anthropic_catchall"


def _payload(text: str) -> Any:
    for line in text.splitlines():
        if line.lstrip().startswith('{"ccr"'):
            return json.loads(line)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"list_events の結果として読めない: JSON 行が見つからない ({e})") from e


def render(text: str) -> list[str]:
    body = _payload(text).get("ccr")
    if not isinstance(body, dict) or "data" not in body:
        raise ValueError("list_events の結果として読めない: ccr.data が無い")
    lines: list[str] = []
    for ev in body["data"]:
        message = ((ev.get("assistant") or {}).get(_KEY) or {}).get("message") or {}
        content = message.get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "text":
                lines.append(part["text"])
        result = (ev.get("result") or {}).get(_KEY)
        if result:
            lines.append(f"[result {result.get('subtype')} is_error={str(result.get('is_error')).lower()}] {result.get('result')}")
    return lines


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="session_closeout.sh events", description=__doc__)
    ap.add_argument("dump", type=Path, help="list_events の保存ファイル")
    args = ap.parse_args(argv)
    try:
        lines = render(args.dump.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"{args.dump}: {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0
