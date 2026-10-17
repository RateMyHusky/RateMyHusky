"""No live code may still talk CockroachDB.

The env var is ORACLE_DATABASE_URL; its old name, CRDB_DATABASE_URL, fails this
test, as does anything else that names CockroachDB or uses SQL or settings only
CockroachDB accepts. Extend SCOPES rather than allowlisting.
"""

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
SCOPES = ["backend/*.py", "backend/**/*.py", "scraper/*.py", "scraper/**/*.py",
          ".github/workflows/*.yml", "README.md",
          "frontend/src/pages/Privacy.tsx", "frontend/src/pages/Terms.tsx"]
SELF = "backend/tests/test_no_crdb_references.py"

FORBIDDEN_I = re.compile(
    r"cockroach|\bCRDB\b|CRDB_DATABASE_URL|NEW_CRDB|_to_crdb|unique_rowid|SET experimental_|"
    r"UPSERT INTO|SHOW CREATE|autocommit_before_ddl|sql_safe_updates|request units?|C-SPANN",
    re.IGNORECASE)
FORBIDDEN = re.compile(r"\bRUs?\b")


def _files():
    out = subprocess.run(["git", "ls-files", "--", *SCOPES], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p != SELF and (REPO / p).exists()]


def test_no_cockroachdb_references_remain():
    hits = []
    for rel in _files():
        for n, line in enumerate((REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if FORBIDDEN_I.search(line) or FORBIDDEN.search(line):
                hits.append(f"{rel}:{n}: {line.strip()}")
    assert not hits, "CockroachDB references remain:\n" + "\n".join(hits)
