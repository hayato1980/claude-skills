#!/usr/bin/env python3
"""利用側リポの docs/agents/*.md に、共有スキルが読む見出しがあるかを確かめる。

見出しは共有スキルとの契約で、変えるとスキルは何も言わずにその節を読まなくなる。
必須の見出しの一覧は plugins/dev-workflow/agent-headings.json（スキルの近く）の 1 か所だけ。

照合はスキル側の読み方（行の完全一致。例: blocking_jobs.sh の `$0 == "## ..."`）と同じにする。
行末の空白や CR を許すと、検査は緑なのにスキルは節を読めない、という逆の結果になる。

終了コード: 0 = 全部ある / 1 = 不足あり / 3 = 一覧や引数が壊れている（黙って通さない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class SpecError(Exception):
    """見出しの一覧が読めない、または形が壊れている。"""


def load_spec(path: Path) -> list[dict[str, object]]:
    try:
        files = json.loads(path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SpecError(f"見出しの一覧を読めません: {path} ({exc!r})") from exc
    if not isinstance(files, list) or not files:
        raise SpecError(f"見出しの一覧が空です: {path}")
    for index, entry in enumerate(files):
        where = f"{path} の files[{index}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SpecError(f"{where} に文字列の path がありません")
        headings = entry.get("headings")
        if not isinstance(headings, list) or not headings or not all(isinstance(h, str) and h for h in headings):
            raise SpecError(f"{where}（{entry['path']}）の headings は空でない文字列のリストにしてください")
        if not isinstance(entry.get("optional", False), bool):
            raise SpecError(f"{where}（{entry['path']}）の optional は真偽値にしてください")
    return files


def level_two_headings(doc: Path) -> set[str]:
    # 改行は LF だけで割る（CRLF の CR を行末に残す）。スキル側（awk / grep）が見る行と同じにするため。
    lines = doc.read_bytes().decode("utf-8").split("\n")
    return {line[3:] for line in lines if line.startswith("## ")}


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
                problems.append(f"{rel}: 見出し `## {heading}` がありません（行末の空白・CR も不一致になります）")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument(
        "--ignore-list",
        default="",
        help="空白区切りの除外ファイル。glob としては展開しない（そのまま文字列で照合する）",
    )
    args = parser.parse_args(argv)
    try:
        files = load_spec(args.spec)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 3
    ignore = set(args.ignore) | set(args.ignore_list.split())
    problems = check(files, args.root, ignore)
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
