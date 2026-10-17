"""schema_check turns loader DDL into expected columns and checks PostgreSQL has them."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import load_banner  # noqa: E402
from schema_check import expected_columns, require_columns  # noqa: E402

DDL = [
    "CREATE TABLE IF NOT EXISTS t (a TEXT PRIMARY KEY, b INT NOT NULL, "
    "seen TIMESTAMPTZ DEFAULT now())",
    "CREATE INDEX IF NOT EXISTS t_b ON t (b)",
    "CREATE TABLE IF NOT EXISTS u (x TEXT NOT NULL, y TEXT, PRIMARY KEY (x, y))",
]


class FakePg:
    """A cursor whose information_schema.columns answer is fixed."""

    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        return self.rows


def test_expected_columns_reads_tables_and_columns_in_order():
    assert expected_columns(DDL) == {"t": ["a", "b", "seen"], "u": ["x", "y"]}


def test_expected_columns_includes_added_columns():
    got = expected_columns(DDL, added_columns=(("t", "extra", "TEXT"), ("t", "a", "TEXT")))
    assert got["t"] == ["a", "b", "seen", "extra"]


def test_require_columns_passes_when_everything_is_present():
    pg = FakePg([("t", "a"), ("t", "b"), ("t", "seen"), ("u", "x"), ("u", "y"),
                 ("other", "z")])
    require_columns(pg, expected_columns(DDL))
    assert "information_schema.columns" in pg.sql[0]
    assert not any(w in pg.sql[0].upper() for w in ("CREATE", "ALTER"))


def test_require_columns_names_the_missing_table_and_column():
    pg = FakePg([("t", "a"), ("t", "seen")])
    with pytest.raises(RuntimeError) as err:
        require_columns(pg, expected_columns(DDL))
    msg = str(err.value)
    assert "missing tables: u" in msg
    assert "missing columns: t.b" in msg
    assert "02_tables.sql" in msg and "README.md" in msg


def test_apply_ddl_on_a_postgres_cursor_issues_no_create_or_alter():
    class Pg(FakePg):
        pass

    cols = expected_columns([s for s in load_banner.DDL.split(";")],
                            load_banner.ADDED_COLUMNS)
    pg = Pg([(t, c) for t, cs in cols.items() for c in cs])
    load_banner.apply_ddl(pg)
    assert len(pg.sql) == 1
    assert not any(w in s.upper() for s in pg.sql for w in ("CREATE", "ALTER"))


def test_apply_ddl_on_a_postgres_cursor_fails_when_a_column_is_missing():
    pg = FakePg([("banner_terms", "term_code")])
    with pytest.raises(RuntimeError, match="banner_roster_duplicates"):
        load_banner.apply_ddl(pg)
    assert all("CREATE" not in s.upper() and "ALTER" not in s.upper() for s in pg.sql)


def test_apply_ddl_on_sqlite_still_creates_tables():
    cur = sqlite3.connect(":memory:").cursor()
    load_banner.apply_ddl(cur)
    assert {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {
        "banner_terms", "banner_sections", "banner_roster_duplicates"}
