"""Fail a PR that adds a line naming the retired review source.

Only added lines are checked; deleting old code never fails. This file and its
fixture necessarily contain the pattern, so they are excluded.

    python .github/scripts/legacy_terms_guard.py --selftest
    python .github/scripts/legacy_terms_guard.py --base origin/main
"""

import argparse
import pathlib
import re
import subprocess
import sys

PATTERN = re.compile(r"(?i:\btrace\b|trace_)|[Tt]race[A-Z]")
# Legitimate words the pattern also hits. Removed from a line before matching.
ALLOWED = re.compile(r"(?i)traceback|trace-deprecation|stack trace|reasoning trace|tracey|tracy")

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE / "legacy_terms_fixture.txt"
EXCLUDED = {".github/scripts/legacy_terms_guard.py", ".github/scripts/legacy_terms_fixture.txt"}


def violates(line: str) -> bool:
    return bool(PATTERN.search(ALLOWED.sub("", line)))


def added_lines(base: str):
    """(path, line_no, text) for every line the branch adds relative to `base`."""
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD"],
        capture_output=True, text=True, check=True, encoding="utf-8",
    ).stdout
    path, line_no = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            yield path, line_no, raw[1:]
            line_no += 1


def selftest() -> int:
    bad = []
    for entry in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not entry.strip():
            continue
        expect, text = (part.strip() for part in entry.split("|", 1))
        if violates(text) != (expect == "FAIL"):
            bad.append(entry)
    for entry in bad:
        print(f"misclassified: {entry}")
    print("selftest ok" if not bad else f"selftest FAILED ({len(bad)})")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    hits = [(p, n, t) for p, n, t in added_lines(args.base) if p not in EXCLUDED and violates(t)]
    for p, n, t in hits:
        print(f"::error file={p},line={n}::retired source name in an added line: {t.strip()[:120]}")
    print(f"{len(hits)} violation(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
