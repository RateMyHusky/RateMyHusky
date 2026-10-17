"""The RMP loader and the prune against real PostgreSQL."""

import csv

import load_rmp
import prune_rmp_reviews
from tests.pg.pgutil import rows, scalar, truncate

REVIEW_COLUMNS = load_rmp.TABLES["rmp_reviews"]["columns"]
REVIEWS = [
    {"professor_name": "Alice Smith", "course": "CS2500", "date": "2025-01-01", "comment": "Clear lectures."},
    {"professor_name": "Alice Smith", "course": "CS2500", "date": "2025-02-01", "comment": "Fair exams."},
    {"professor_name": "Bob Jones", "course": "MATH1341", "date": "2025-03-01", "comment": ""},
]


def write_reviews(tmp_path, reviews, name="rmp_reviews.csv"):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for r in reviews:
            writer.writerow({c: r.get(c, "") for c in REVIEW_COLUMNS})
    return str(path)


def test_review_upsert_is_idempotent_through_on_conflict(pg, tmp_path):
    truncate(pg, "rmp_reviews")
    path = write_reviews(tmp_path, REVIEWS)
    conf = load_rmp.TABLES["rmp_reviews"]
    for _ in range(2):  # no client-side pre-filter: exercises the ON CONFLICT target
        load_rmp.upload_csv(pg, "rmp_reviews", conf["columns"], path, conf["transform"],
                            conf["on_conflict"], None, None, conf["deny_name"])
    assert scalar(pg, "SELECT count(*) FROM rmp_reviews") == len(REVIEWS)


def test_new_reviews_get_identity_ids_past_the_migrated_max(pg, tmp_path):
    truncate(pg, "rmp_reviews")
    big = 1_100_000_000_000_000_000  # ids migrated from the previous database are this large
    with pg.cursor() as cur:
        cur.execute("INSERT INTO rmp_reviews (id, professor_name, course, date, comment) "
                    "VALUES (%s, 'Old Prof', 'CS1', '2020', 'old')", (big,))
        cur.execute("SELECT setval(pg_get_serial_sequence('rmp_reviews', 'id'), %s)", (big,))
    pg.commit()
    load_rmp.load_table(pg, "rmp_reviews", write_reviews(tmp_path, REVIEWS))
    assert scalar(pg, "SELECT min(id) FROM rmp_reviews WHERE professor_name <> 'Old Prof'") > big
    assert scalar(pg, "SELECT count(*) FROM rmp_reviews") == len(REVIEWS) + 1


def test_replace_leaves_exactly_the_csv_rows(pg, tmp_path):
    truncate(pg, "rmp_professors")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO rmp_professors (name, department) VALUES ('Gone Prof', 'History')")
    pg.commit()
    path = tmp_path / "rmp_professors.csv"
    path.write_text(
        "name,department,rating,num_ratings,would_take_again_pct,level_of_difficulty,professor_url\n"
        "Prof One,Math,4.0,10,90%,2.0,https://a\nProf Two,Physics,3.0,5,50%,3.0,https://b\n",
        encoding="utf-8")
    load_rmp.load_table(pg, "rmp_professors", str(path), replace=True)
    names = sorted(r["name"] for r in rows(pg, "SELECT name FROM rmp_professors"))
    assert names == ["Prof One", "Prof Two"]


def test_prune_removes_vanished_reviews_with_their_evidence(pg, tmp_path):
    truncate(pg, "rmp_reviews", "evidence")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO rmp_reviews (professor_name, course, date, comment) VALUES "
                    "('Alice Smith', 'CS2500', '2025-01-01', 'a'), "
                    "('Alice Smith', 'CS2500', '2025-02-01', 'b'), "
                    "('Alice Smith', 'CS2500', '2025-03-01', 'gone') RETURNING id")
        gone_id = cur.fetchall()[-1][0]
        cur.execute("INSERT INTO evidence (source, source_ref, professor_slug, course_code, body, body_sha) "
                    "VALUES ('rmp', %s, 'alice-smith', 'CS2500', 'gone review', 'sha') RETURNING id",
                    (str(gone_id),))
        evidence_id = cur.fetchone()[0]
        cur.execute("INSERT INTO evidence_embeddings (evidence_id, embedding, model_version) "
                    "VALUES (%s, %s::vector, 'test')", (evidence_id, str([0.0] * 383 + [1.0])))
    pg.commit()

    keep = write_reviews(tmp_path, [
        {"professor_name": "Alice Smith", "course": "CS2500", "date": "2025-01-01"},
        {"professor_name": "Alice Smith", "course": "CS2500", "date": "2025-02-01"},
    ])
    prune_rmp_reviews.prune(pg, keep, force=True)

    assert sorted(r["comment"] for r in rows(pg, "SELECT comment FROM rmp_reviews")) == ["a", "b"]
    assert scalar(pg, "SELECT count(*) FROM evidence") == 0
    assert scalar(pg, "SELECT count(*) FROM evidence_embeddings") == 0
