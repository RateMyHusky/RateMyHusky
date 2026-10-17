"""The scraper modules' DDL must be satisfied by db/postgres/.

The loaders no longer create tables on PostgreSQL; they call
schema_check.require_columns against the live schema. This runs that exact check
against the scratch database built from db/postgres/, so adding a column to a
loader's DDL without adding it to 02_tables.sql fails here, not in production.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scraper"))

import load_banner  # noqa: E402
import load_catalog  # noqa: E402
import match_banner_instructors  # noqa: E402
from schema_check import require_columns  # noqa: E402

MODULES = [load_banner, match_banner_instructors, load_catalog]


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_schema_files_define_every_column_the_module_uses(pg, module):
    expected = module.expected_schema()
    assert expected, "the module's DDL produced no tables"
    require_columns(pg.cursor(), expected)


def test_apply_ddl_checks_instead_of_creating_on_postgres(pg):
    cur = pg.cursor()
    tables = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    cur.execute(tables)
    before = {r[0] for r in cur.fetchall()}
    load_banner.apply_ddl(cur)
    cur.execute(tables)
    assert {r[0] for r in cur.fetchall()} == before


def test_a_missing_column_is_reported(pg):
    cur = pg.cursor()
    cur.execute("ALTER TABLE banner_sections DROP COLUMN part_of_term")
    try:
        with pytest.raises(RuntimeError, match=r"banner_sections\.part_of_term"):
            load_banner.apply_ddl(cur)
    finally:
        pg.rollback()
