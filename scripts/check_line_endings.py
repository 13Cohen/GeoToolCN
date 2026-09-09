"""Fail if a text file's line endings changed.

Editing README.md with a script that reads and rewrites text silently converts
its CRLF endings to LF, turning a two-line edit into a whole-file diff.  It
happened twice while building version 3.

    python scripts/check_line_endings.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# path -> expected ending, taken from what the file already uses in git.
EXPECTED = {"README.md": b"\r\n"}


def main() -> int:
    problems = []
    for name, ending in EXPECTED.items():
        path = _ROOT / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        data = path.read_bytes()
        has_crlf = b"\r\n" in data
        wants_crlf = ending == b"\r\n"
        if has_crlf != wants_crlf:
            problems.append(
                f"{name}: expected {'CRLF' if wants_crlf else 'LF'} line endings, "
                f"found {'CRLF' if has_crlf else 'LF'}"
            )
    if problems:
        print("Line ending check failed:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"Line endings OK ({len(EXPECTED)} file(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
