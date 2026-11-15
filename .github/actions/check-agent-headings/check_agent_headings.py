#!/usr/bin/env python3
"""利用側リポの docs/agents/*.md に、共有スキルが読む見出しがあるかを確かめる。

見出しは共有スキルとの契約で、変えるとスキルは何も言わずにその節を読まなくなる。
必須の見出しの一覧は plugins/dev-workflow/agent-headings.json（スキルの近く）の 1 か所だけ。

終了コード: 0 = 全部ある / 1 = 不足あり / 3 = 一覧や引数が壊れている（黙って通さない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_spec(path: Path) -> list[dict[str, object]]:
    try:
        files = json.loads(path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"見出しの一覧を読めません: {path} ({exc!r})") from exc
    if not isinstance(files, list) or not files:
        raise SystemExit(f"見出しの一覧が空です: {path}")
    return files


def level_two_headings(doc: Path) -> set[str]:
    found: set[str] = set()
    for line in doc.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            found.add(line[3:].rstrip())
    return found


def check(files: list[dict[str, object]], root: Path, ignore: set[str]) -> list[str]:
    problems: list[str] = []
    for entry in files:
        rel = str(entry["path"])
        if rel in ignore:
            continue
        doc = root / rel
        if not doc.is_file():
            if not entry.get("optional"):
                problems.append(f"{rel}: ファイルがありません")
            continue
        present = level_two_headings(doc)
        for heading in entry["headings"]:  # type: ignore[attr-defined]
            if heading not in present:
                problems.append(f"{rel}: 見出し `## {heading}` がありません")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--ignore", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        files = load_spec(args.spec)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 3
    problems = check(files, args.root, set(args.ignore))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(
            "共有スキルはこれらの見出しを名前で探します。見出しを変えると、スキルは何も言わずにその節を読まなくなります。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
