"""The one-off name backfill against real PostgreSQL."""

import pytest

import tidy_names
from tests.pg.pgutil import rows, scalar, truncate

SEEDS = [
    ("david-o-brien", "David O&#39;Brien"),
    ("amy-mcgreevy", "Amy Mcgreevy"),
    ("thomas-sexton", "THOMAS SEXTON"),
    ("jaime-d-almeida", "Jaime d'Almeida"),
    ("benjamin-machlin", "Benjamin Machlin"),
    ("blank", ""),
]


@pytest.fixture(autouse=True)
def seeded(pg):
    truncate(pg, "professors")
    with pg.cursor() as cur:
        for slug, name in SEEDS:
            cur.execute("INSERT INTO professors (slug, name, name_key) VALUES (%s, %s, %s)",
                        (slug, name, slug))
    pg.commit()


def test_dry_run_writes_nothing(pg):
    changes = tidy_names.tidy(pg, dry_run=True)
    assert [c[0] for c in changes] == ["amy-mcgreevy", "david-o-brien", "thomas-sexton"]
    assert scalar(pg, "SELECT name FROM professors WHERE slug = 'david-o-brien'") == "David O&#39;Brien"


def test_real_run_changes_exactly_the_bad_rows_and_is_idempotent(pg):
    tidy_names.tidy(pg)
    got = {r["slug"]: r["name"] for r in rows(pg, "SELECT slug, name FROM professors")}
    assert got["david-o-brien"] == "David O'Brien"
    assert got["amy-mcgreevy"] == "Amy McGreevy"
    assert got["thomas-sexton"] == "Thomas Sexton"
    assert got["jaime-d-almeida"] == "Jaime d'Almeida"
    assert got["benjamin-machlin"] == "Benjamin Machlin" and got["blank"] == ""
    assert tidy_names.tidy(pg) == []
