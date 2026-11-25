#!/usr/bin/env python3
"""見出しの一覧（agent-headings.json）・README の契約表・スキル本文の見出し参照が食い違っていないかを確かめる。

このリポ自身の CI 用（利用側リポへは配らない）。配る検査は .github/actions/check-agent-headings。
一覧の読み方（検証・平らにする規則）はそのチェッカーのものを使い、別実装を持たない。

食い違いの種類:
  - 一覧にあるのに、スキル本文（プラグイン配下の .md / .sh / .py の `## 見出し`）が読まない
  - スキル本文が読むのに、一覧に無い
  - README の表の (ファイル, 見出し) の対が、一覧と合わない

終了コード: 0 = 一致 / 1 = 食い違いあり / 3 = 入力が読めない・壊れている。
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

CHECKER = Path(__file__).resolve().parents[2] / ".github" / "actions" / "check-agent-headings" / "check_agent_headings.py"

BACKTICKED_HEADING = re.compile(r"`## ([^`]+)`")
README_ROW = re.compile(r"^\|\s*`(docs/agents/[^`]+)`\s*\|(.*)$")

# 上流の code-review が返す出力の見出し。利用側の docs/agents との契約ではない。
NOT_A_CONTRACT = {"Standards", "Spec"}


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_agent_headings", CHECKER)
    if spec is None or spec.loader is None:
        raise ImportError(f"チェッカーを読めません: {CHECKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def referenced_headings(plugin_root: Path) -> set[str]:
    if not plugin_root.is_dir():
        raise OSError(f"{plugin_root} はディレクトリではありません")
    found: set[str] = set()
    for path in plugin_root.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".sh", ".py"}:
            found |= set(BACKTICKED_HEADING.findall(path.read_text(encoding="utf-8")))
    return found - NOT_A_CONTRACT


def readme_pairs(readme: Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for line in readme.read_text(encoding="utf-8").splitlines():
        row = README_ROW.match(line)
        if row:
            pairs |= {(row.group(1), h) for h in BACKTICKED_HEADING.findall(row.group(2))}
    return pairs


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--plugin-root", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        checker = load_checker()
    except (ImportError, OSError) as exc:
        print(f"読めません: {exc}", file=sys.stderr)
        return 3
    try:
        files = checker.load_spec(args.spec)
        referenced = referenced_headings(args.plugin_root)
        in_readme = readme_pairs(args.readme)
    except checker.SpecError as exc:
        print(exc, file=sys.stderr)
        return 3
    except (ImportError, OSError) as exc:
        print(f"読めません: {exc}", file=sys.stderr)
        return 3

    listed_pairs = {(e["path"], h) for e in files for h in checker.declared_headings(e)}
    listed = {h for _, h in listed_pairs}

    problems = [f"一覧にあるがスキルが読まない見出し: `## {h}`" for h in sorted(listed - referenced)]
    problems += [f"スキルが読むが一覧に無い見出し: `## {h}`" for h in sorted(referenced - listed)]
    problems += [f"一覧にあるが README の表に無い: {p} `## {h}`" for p, h in sorted(listed_pairs - in_readme)]
    problems += [f"README の表にあるが一覧に無い: {p} `## {h}`" for p, h in sorted(in_readme - listed_pairs)]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
