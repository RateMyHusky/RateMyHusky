"""The Ask corpus prune (scraper/load_evidence.py) against PostgreSQL: full-key staleness,
uuid ids, embeddings removed with their rows, the stored peak, and a refused build writing
nothing."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scraper"))

import load_evidence as le  # noqa: E402
from tests.pg.pgutil import rows, scalar, truncate  # noqa: E402

BODY = "a long enough review body to count as meaningful text"


def rmp(ref, slug="guha", code="CS3500", body=BODY):
    return le._row("rmp", ref, slug, code, body)


def seed(conn, evidence_rows, peak=None):
    truncate(conn, "evidence", "evidence_embeddings", "stats_cache")
    le.upsert_evidence(conn, evidence_rows)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO evidence_embeddings (evidence_id, embedding, model_version) "
                    "SELECT id, array_fill(0.1::real, ARRAY[384])::vector, 'test' FROM evidence")
        if peak is not None:
            cur.execute("INSERT INTO stats_cache (key, value) VALUES ('evidence_peak:rmp', %s)", (peak,))
    conn.commit()


def keys(conn):
    return sorted((r["source_ref"], r["professor_slug"], r["course_code"])
                  for r in rows(conn, "SELECT source_ref, professor_slug, course_code FROM evidence"))


def run(conn, built, force=False):
    plans = [le.plan_source(conn, "rmp", built)]
    le.check_plans(plans, force=force, prune=True)
    le.upsert_evidence(conn, built)
    return le.prune_evidence(conn, plans, force=force)


def test_rows_under_an_old_professor_or_course_are_pruned_with_their_embeddings(pg):
    old = [rmp(str(i)) for i in range(40)]
    seed(pg, old)
    built = [rmp(str(i)) for i in range(38)] + [rmp("38", code="CS3650"), rmp("39", slug="lee")]
    assert run(pg, built) == {"rmp": 2}
    assert ("38", "guha", "CS3500") not in keys(pg) and ("38", "guha", "CS3650") in keys(pg)
    assert ("39", "guha", "CS3500") not in keys(pg) and ("39", "lee", "CS3500") in keys(pg)
    assert scalar(pg, "SELECT count(*) FROM evidence") == 40
    # The two pruned rows' embeddings went with them; the two new rows have none yet.
    assert scalar(pg, "SELECT count(*) FROM evidence_embeddings") == 38
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'evidence_peak:rmp'") == 40


def test_a_drained_build_is_refused_and_writes_nothing(pg):
    seed(pg, [rmp(str(i)) for i in range(40)], peak=50)       # 40 is 20% under the peak
    before = keys(pg)
    with pytest.raises(SystemExit, match="under the source's peak"):
        run(pg, [rmp(str(i)) for i in range(40)] + [rmp("new")])
    assert keys(pg) == before
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'evidence_peak:rmp'") == 50
