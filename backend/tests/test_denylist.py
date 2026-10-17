"""A data-deletion request has to survive a pipeline that rebuilds from CSVs.

precompute DROPs and rebuilds professors_catalog every run, and load_rmp
re-inserts rmp_reviews from the store, so deleting a professor's
rows by hand removes them only until the next refresh. The denylist is the part
that persists: it lives in the repo and every loader consults it before writing.

These tests cover the matching rule and the two properties that make it work —
alias resolution (a professor spelled two ways is one person) and the loaders
actually consulting it. The purge path is covered by driving find_targets against
a recording fake cursor.

No database, no network.
"""

import hashlib

import pytest

import denylist
from denylist import (
    entry_hash,
    is_denied,
    is_denied_key,
    denied_hashes,
    name_key,
    normalize_name,
)


@pytest.fixture
def listfile(tmp_path, monkeypatch):
    """A denylist file at a temp path, with the module cache pointed at it."""
    path = tmp_path / "denylist.txt"
    path.write_text("")
    monkeypatch.setattr(denylist, "DENYLIST_PATH", str(path))
    denylist._cache.clear()

    def add(*names, note="test"):
        with open(path, "a", encoding="utf-8") as fh:
            for n in names:
                fh.write(f"{entry_hash(n)}  # {note}\n")
        denylist._cache.clear()
        return path

    add.path = path
    return add


# ── the matching rule ───────────────────────────────────────────────────────

def test_normalize_matches_pipeline_rule():
    """The key has to be byte-identical to pipeline.names' or the filter never fires.

    denylist.py keeps its own copy rather than importing pipeline.names, to stay
    import-light for loaders that do not carry the pipeline package.
    """
    from pipeline.names import normalize_name as pc_normalize
    for raw in ["Julia Garrett", "  JULIA   GARRETT ", "Renée Descartes",
                "José Álvarez", "O'Brien", "Zhiyuan (Katherine) Zhang"]:
        assert normalize_name(raw) == pc_normalize(raw), raw


def test_purge_slug_rule_matches_pipeline():
    """purge_denied reconstructs slugs the pipeline wrote; the rules must agree.

    Duplicated for the same reason normalize_name is: purge_denied is a small
    operational script that stays import-light rather than importing pipeline.names.
    """
    from pipeline.names import name_to_slug as pc_slug
    from purge_denied import name_to_slug
    for key in ["julia garrett", "jose garcia", "o'brien smith",
                "md nazmus sakib miazi", "zhiyuan (katherine) zhang"]:
        assert name_to_slug(key) == pc_slug(key), key


def test_a_listed_professor_is_denied(listfile):
    listfile("Julia Garrett")
    assert is_denied("Julia Garrett")
    assert is_denied("  julia   garrett  ")
    assert is_denied("JULIA GARRETT")


def test_an_unlisted_professor_is_not(listfile):
    listfile("Julia Garrett")
    assert not is_denied("Garrett Morrow")
    assert not is_denied("Julia Garretson")
    assert not is_denied("Julia")


def test_empty_and_missing_names_are_not_denied(listfile):
    listfile("Julia Garrett")
    assert not is_denied(None)
    assert not is_denied("")
    assert not is_denied("   ")


def test_an_empty_list_denies_nobody(listfile):
    assert denied_hashes() == frozenset()
    assert not is_denied("Julia Garrett")


def test_aliases_resolve_so_both_spellings_are_caught(listfile):
    """One person, two spellings, one request — both halves must go.

    Sources spell the same professor differently; ALIAS_MAP is what makes them
    one row. A denylist that matched only the spelling someone happened to type
    in their request would leave the other spelling published.
    """
    listfile("Md Nazmus Sakib Miazi")     # the long spelling
    assert is_denied("sakib miazi")        # the RMP spelling
    assert is_denied("Md Nazmus Sakib Miazi")
    # ...and adding it under the RMP spelling resolves to the same entry.
    assert entry_hash("sakib miazi") == entry_hash("md nazmus sakib miazi")


def test_key_form_skips_renormalizing(listfile):
    listfile("Julia Garrett")
    assert is_denied_key("julia garrett")
    assert not is_denied_key("Julia Garrett"), "is_denied_key takes a normalized key"
    assert not is_denied_key(None)
    assert not is_denied_key("")


def test_entries_are_hashed_not_plaintext(listfile):
    """The file must not contain the name; the repo is public."""
    path = listfile("Julia Garrett")
    text = path.read_text()
    assert "julia" not in text.lower()
    assert "garrett" not in text.lower()
    assert hashlib.sha256(b"julia garrett").hexdigest() in text


def test_comments_and_blank_lines_are_ignored(listfile, tmp_path):
    path = listfile.path
    path.write_text(
        "# a header comment\n"
        "\n"
        f"{entry_hash('Julia Garrett')}  # 2026-08-11 request\n"
        "   \n"
    )
    denylist._cache.clear()
    assert denied_hashes() == frozenset({entry_hash("Julia Garrett")})
    assert is_denied("Julia Garrett")


def test_a_missing_file_is_an_empty_list(tmp_path, monkeypatch):
    """No file is the normal state for a fresh checkout, not an error."""
    monkeypatch.setattr(denylist, "DENYLIST_PATH", str(tmp_path / "nope.txt"))
    denylist._cache.clear()
    assert denied_hashes() == frozenset()
    assert not is_denied("Julia Garrett")


# ── the CLI ─────────────────────────────────────────────────────────────────

def test_add_writes_a_hash_and_is_idempotent(listfile, capsys):
    denylist.main(["add", "Julia Garrett", "--note", "2026-08-11 request"])
    text = listfile.path.read_text()
    assert entry_hash("Julia Garrett") in text
    assert "2026-08-11 request" in text
    assert "Julia" not in text

    denylist.main(["add", "julia garrett"])
    assert text.count(entry_hash("Julia Garrett")) == 1
    assert "Already on the list" in capsys.readouterr().out


def test_check_exit_code_reports_membership(listfile):
    listfile("Julia Garrett")
    assert denylist.main(["check", "Julia Garrett"]) == 0
    assert denylist.main(["check", "Garrett Morrow"]) == 1


# ── the loaders consult it ──────────────────────────────────────────────────

def test_migrate_tags_every_table_that_carries_a_name():
    """A table with a professor name in it must be filtered, or data leaks through."""
    from load_rmp import TABLES
    expected = {
        "rmp_professors": ("name",),
        "rmp_reviews": ("professor_name",),
        "professor_photos": ("name",),
    }
    for table, cols in expected.items():
        assert TABLES[table].get("deny_name") == cols, f"{table} is not filtered"


def test_migrate_withholds_a_denied_row(listfile, tmp_path, capsys):
    """upload_csv drops the row rather than inserting it."""
    import load_rmp

    listfile("Julia Garrett")
    csv_path = tmp_path / "rmp_professors.csv"
    csv_path.write_text(
        "name,department,rating,num_ratings,would_take_again_pct,"
        "level_of_difficulty,professor_url\n"
        "Julia Garrett,English,3.4,13,80%,2.5,https://x\n"
        "Garrett Morrow,Political Science,4.4,20,90%,2.0,https://y\n"
    )

    inserted = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): pass

    class Conn:
        def cursor(self): return Cur()
        def commit(self): pass

    def fake_execute_values(cur, sql, batch, page_size=None):
        inserted.extend(batch)

    load_rmp.execute_values = fake_execute_values
    conf = load_rmp.TABLES["rmp_professors"]
    load_rmp.upload_csv(
        Conn(), "rmp_professors", conf["columns"], str(csv_path),
        conf["transform"], conf["on_conflict"], None, None, conf["deny_name"])

    names = [row[0] for row in inserted]
    assert names == ["Garrett Morrow"]
    assert "1 withheld (denylist)" in capsys.readouterr().out


def test_precompute_filters_the_rmp_frame(listfile):
    """The catalog build drops them from the RMP frame."""
    import pandas as pd
    listfile("Julia Garrett")

    rmp = pd.DataFrame({"_name_key": ["julia garrett", "garrett morrow"]})
    assert list(rmp[~rmp["_name_key"].map(is_denied_key)]["_name_key"]) == ["garrett morrow"]


def test_evidence_builders_import_the_filter():
    """The RAG corpus is what chat quotes; it has to honour the list too."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "scraper" / "load_evidence.py"
    text = src.read_text(encoding="utf-8")
    assert "from denylist import is_denied_key" in text
    assert 'is_denied_key(r.get("name_key"))' in text, (
        "the RMP evidence builder must check the denylist")
    assert "known_slugs" in text, "reddit rows must be restricted to catalog slugs"


# ── the purge resolves identity before deleting ─────────────────────────────

class FakeCursor:
    """Answers find_targets' probe queries from canned rows.

    Dispatch is on (table, shape) rather than a single substring: the
    rmp_reviews probes both mention name_key, so matching that alone would
    answer one with the other's rows.
    """

    def __init__(self, catalog, rmp_reviews, slug_rows=(), null_key_reviews=(),
                 professors=()):
        self._data = {
            "catalog": catalog,
            "professors": professors,
            "rmp_reviews": rmp_reviews,
            "slugs": slug_rows,
            "rmp_null": null_key_reviews,
        }
        self._rows = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        if "FROM professors_catalog" in flat:
            key = "catalog"
        elif "FROM professors" in flat:
            key = "professors"
        elif "professor_slug FROM" in flat:
            key = "slugs"
        elif "FROM rmp_reviews" in flat:
            key = "rmp_null" if "name_key IS NULL" in flat else "rmp_reviews"
        else:
            key = None
        self._rows = self._data.get(key, []) if key else []

    def fetchall(self):
        return list(self._rows)


def test_purge_finds_the_professor_through_the_catalog(listfile):
    from purge_denied import find_targets
    listfile("Julia Garrett")
    cur = FakeCursor(
        catalog=[("julia-garrett", "Julia Garrett", "julia garrett"),
                 ("garrett-morrow", "Garrett Morrow", "garrett morrow")],
        rmp_reviews=[("Julia Garrett", "julia garrett")],
    )
    slugs, name_keys, _ = find_targets(cur)
    assert slugs == ["julia-garrett"]
    assert "julia garrett" in name_keys
    assert "garrett morrow" not in name_keys


def test_purge_still_finds_them_after_precompute_removed_the_catalog_row(listfile):
    """The case a naive purge misses entirely.

    Run precompute first and the professor has no catalog row, while their
    review rows are still loaded. A purge that only searched the catalog would
    find nothing and report clean while the data sat there.
    """
    from purge_denied import find_targets
    listfile("Julia Garrett")
    cur = FakeCursor(
        catalog=[("garrett-morrow", "Garrett Morrow", "garrett morrow")],
        rmp_reviews=[("Julia Garrett", "julia garrett"),
                     ("Garrett Morrow", "garrett morrow")],
    )
    slugs, name_keys, _ = find_targets(cur)
    assert slugs == []
    assert name_keys == ["julia garrett"]


def test_purge_recovers_evidence_slugs_the_catalog_can_no_longer_resolve(listfile):
    """evidence and the reddit tables key on professor_slug, nothing else.

    Once precompute has dropped the catalog row there is no slug to look up, so
    `slugs` came back empty and every RAG row the chat can still retrieve and
    quote survived the purge — while the tool printed a clean result. The slug is
    name_to_slug(name_key), so the raw-table name match reconstructs it.
    """
    from purge_denied import find_targets
    listfile("Julia Garrett")
    cur = FakeCursor(
        catalog=[("garrett-morrow", "Garrett Morrow", "garrett morrow")],
        rmp_reviews=[("Julia Garrett", "julia garrett")],
        slug_rows=[("julia-garrett",), ("garrett-morrow",)],
    )
    slugs, _, _ = find_targets(cur)
    assert slugs == ["julia-garrett"]


def test_slug_recovery_does_not_widen_to_deduped_variants(listfile):
    """Reconstruction takes the exact slug and nothing adjacent.

    precompute breaks name_to_slug collisions with -2, -3. Sweeping those in on a
    prefix match would delete rows this tool cannot prove belong to the denied
    professor, and over-deletion is the one failure a purge cannot undo. The
    catalog path is still authoritative when the row exists; this only fills the
    hole left after precompute drops it.
    """
    from purge_denied import find_targets
    listfile("Julia Garrett")
    cur = FakeCursor(
        catalog=[],
        rmp_reviews=[("Julia Garrett", "julia garrett")],
        slug_rows=[("julia-garrett",), ("julia-garrett-2",)],
    )
    slugs, _, _ = find_targets(cur)
    assert slugs == ["julia-garrett"]


def test_a_missing_slug_table_does_not_poison_the_transaction(listfile):
    """The slug probe is the first query here allowed to fail.

    psycopg2 aborts the whole transaction on any error, so swallowing the
    exception without a rollback leaves every later statement failing with
    "current transaction is aborted" — the purge would then skip its first real
    delete step for a reason that has nothing to do with it. reddit_sentiment is
    genuinely absent on a database that never ran the reddit loader.
    """
    from purge_denied import find_targets

    class Poisonable(FakeCursor):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.rolled_back = 0
            outer = self

            class Conn:
                def rollback(self):
                    outer.rolled_back += 1

            self.connection = Conn()

        def execute(self, sql, params=None):
            if "professor_slug FROM reddit_sentiment" in " ".join(sql.split()):
                raise RuntimeError('relation "reddit_sentiment" does not exist')
            super().execute(sql, params)

    listfile("Julia Garrett")
    cur = Poisonable(
        catalog=[],
        rmp_reviews=[("Julia Garrett", "julia garrett")],
        slug_rows=[("julia-garrett",)],
    )
    slugs, name_keys, _ = find_targets(cur)
    assert slugs == ["julia-garrett"], "a later probe was lost to the failed one"
    assert name_keys == ["julia garrett"]
    assert cur.rolled_back == 1, "the failed probe left the transaction aborted"


def test_purge_normalizes_a_review_name_with_no_name_key(listfile):
    """A row whose name_key is not backfilled still resolves through name_key().

    A hand-built "  josé  garcía " key skips the NFKD fold and the whitespace
    collapse, and would match nothing.
    """
    from purge_denied import find_targets
    listfile("José García")
    cur = FakeCursor(
        catalog=[],
        rmp_reviews=[("José  García ", None)],
    )
    _, name_keys, _ = find_targets(cur)
    assert name_keys == ["jose garcia"]


def test_purge_resolves_an_alias_from_a_review_name(listfile):
    """name_key applies ALIAS_MAP, so the alias spelling resolves to the target."""
    from prof_aliases import ALIAS_MAP
    from purge_denied import find_targets
    alias = next(iter(ALIAS_MAP))
    listfile(ALIAS_MAP[alias])
    cur = FakeCursor(catalog=[], rmp_reviews=[(alias, None)])
    _, name_keys, _ = find_targets(cur)
    assert name_keys == [ALIAS_MAP[alias]]


def test_purge_collects_review_ids_whose_name_key_is_not_backfilled_yet(listfile):
    """precompute backfills rmp_reviews.name_key; rows the loader just wrote are
    NULL, and the delete is `WHERE name_key = ANY(...)`, so a purge run between
    the weekly RMP load and precompute left them behind."""
    from purge_denied import find_targets
    listfile("Julia Garrett")
    cur = FakeCursor(
        catalog=[],
        rmp_reviews=[("Julia Garrett", "julia garrett")],
        null_key_reviews=[(101, "Julia Garrett"), (102, "Garrett Morrow")],
    )
    _, _, review_ids = find_targets(cur)
    assert review_ids == [101]


def test_nothing_matches_an_empty_list(listfile):
    from purge_denied import find_targets
    cur = FakeCursor(
        catalog=[("julia-garrett", "Julia Garrett", "julia garrett")],
        rmp_reviews=[("Julia Garrett", "julia garrett")],
    )
    assert find_targets(cur) == ([], [], [])


def test_migrate_filter_survives_a_transform_that_yields_nothing(listfile):
    """The filter must not depend on the transform understanding the CSV.

    A transform that reads camelCase keys against a snake_case export produces
    empty strings for every field. A name check against only that output would
    wave every row through and report nothing wrong — the one failure mode a
    privacy filter must not have.
    """
    from load_rmp import _row_is_denied
    listfile("Julia Garrett")
    deny = ("first_name", "last_name")

    # Transform understood the CSV.
    assert _row_is_denied({"first_name": "Julia", "last_name": "Garrett"}, {}, deny)
    # Transform produced nothing; the raw snake_case row still catches it.
    raw_snake = {"first_name": "Julia", "last_name": "Garrett"}
    assert _row_is_denied({"first_name": "", "last_name": ""}, raw_snake, deny)
    # ...and the raw camelCase row too.
    raw_camel = {"firstName": "Julia", "lastName": "Garrett"}
    assert _row_is_denied({"first_name": "", "last_name": ""}, raw_camel, deny)
    # A different professor passes through under every spelling.
    assert not _row_is_denied({"first_name": "Garrett", "last_name": "Morrow"}, {}, deny)
    assert not _row_is_denied({}, {"firstName": "Garrett", "lastName": "Morrow"}, deny)
    # An all-empty row is not a match for a one-word denylist entry.
    assert not _row_is_denied({"first_name": "", "last_name": ""}, {}, deny)


def test_camel_conversion_matches_the_transform_keys():
    from load_rmp import _camel
    assert _camel("professor_name") == "professorName"
    assert _camel("name") == "name"


def test_purge_finds_a_professor_with_no_reviews_through_the_pipeline_table(listfile):
    """No catalog row and no RMP reviews leaves only the pipeline's professors row.

    Without it the slug never resolves, the reddit and evidence rows survive, and
    the tool prints "Nothing to purge".
    """
    from purge_denied import find_targets
    listfile("Julia Garrett")
    cur = FakeCursor(
        catalog=[], rmp_reviews=[],
        professors=[("julia-garrett", "Julia Garrett", "julia garrett"),
                    ("garrett-morrow", "Garrett Morrow", "garrett morrow")],
        slug_rows=[("julia-garrett",)],
    )
    slugs, name_keys, _ = find_targets(cur)
    assert slugs == ["julia-garrett"]
    assert name_keys == ["julia garrett"]


def test_purge_deletes_the_pipeline_identity_rows(listfile):
    """A deletion request must not leave the name, RMP name or RMP URL behind."""
    from purge_denied import purge
    listfile("Julia Garrett")

    class Recording(FakeCursor):
        executed = []

        def execute(self, sql, params=None):
            Recording.executed.append(" ".join(sql.split()))
            super().execute(sql, params)

        def fetchone(self):
            return (1,)

    cur = Recording(catalog=[("julia-garrett", "Julia Garrett", "julia garrett")],
                    rmp_reviews=[])

    class Conn:
        def cursor(self):
            return cur

        def commit(self):
            pass

        def rollback(self):
            pass

    purge(Conn())
    assert "DELETE FROM rmp_links WHERE slug = ANY(%s)" in Recording.executed
    assert "DELETE FROM professors WHERE slug = ANY(%s)" in Recording.executed
