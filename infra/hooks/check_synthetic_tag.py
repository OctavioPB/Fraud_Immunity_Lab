#!/usr/bin/env python3
"""
Pre-commit hook: any Python file in red_team/ or ingestion/producers/
that produces data must include the synthetic tag pattern.
Hard Rule #3 from CLAUDE.md: synthetic data is ALWAYS tagged.
"""

import ast
import sys


REQUIRED_PATTERN = '"synthetic"'
EXEMPT_PREFIXES = ("base_", "conftest", "__init__")


def check_file(path: str) -> bool:
    filename = path.split("/")[-1].split("\\")[-1]
    if any(filename.startswith(p) for p in EXEMPT_PREFIXES):
        return True

    try:
        source = open(path, encoding="utf-8").read()
    except OSError:
        return True

    # Only check files that look like they produce events/data
    if not any(
        kw in source
        for kw in ("produce", "inject", "publish", "emit", "synthetic")
    ):
        return True

    if '"synthetic"' not in source and "'synthetic'" not in source:
        print(
            f"[synthetic-tag-check] FAIL: {path}\n"
            "  Files that produce synthetic data must include the tag:\n"
            '  {"synthetic": true, "origin": "red_team"}\n'
            "  See CLAUDE.md Hard Rule #3."
        )
        return False

    return True


def main() -> int:
    files = sys.argv[1:]
    failures = [f for f in files if not check_file(f)]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
