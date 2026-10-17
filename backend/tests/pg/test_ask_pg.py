"""Ask retrieval SQL against pgvector and PostgreSQL full-text search."""

from rag import chat_retrieve, chat_search
from tests.pg.pgutil import query_fn, truncate

ALICE = "Alice Smith holds great office hours every week and explains recursion clearly."
MIDTERM = "The midterm curve in her class was generous this semester, people said."


def seed_evidence(conn):
    truncate(conn, "evidence")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO evidence (source, source_ref, professor_slug, course_code, body, body_tsv, body_sha, flagged) "
            "VALUES ('rmp', '1', 'alice-smith', '', %s, to_tsvector('english', %s), 'sha1', false), "
            "       ('reddit', 'c1', 'alice-smith', '', %s, to_tsvector('english', %s), 'sha2', false) "
            "RETURNING id", (ALICE, ALICE, MIDTERM, MIDTERM))
        ids = [r[0] for r in cur.fetchall()]
        for axis, evidence_id in enumerate(ids):
            vec = [0.0] * 384
            vec[axis] = 1.0
            cur.execute("INSERT INTO evidence_embeddings (evidence_id, embedding, model_version) "
                        "VALUES (%s, %s::vector, 'test')", (evidence_id, str(vec)))
    conn.commit()
    return ids


def test_vector_candidates_rank_by_cosine(pg):
    ids = seed_evidence(pg)
    where, params = chat_retrieve._entity_filter("alice-smith", None)
    qv = [0.0] * 384
    qv[0] = 1.0
    qv[1] = 1e-05          # str() renders this as '1e-05'; pgvector must accept it
    got = chat_retrieve._vector_candidates(where, params, qv, query_fn(pg))
    assert [i for i, _ in got] == ids
    assert got[0][1] > 0.99 and got[1][1] < 0.01


def test_lexical_candidates_use_english_full_text_search(pg):
    ids = seed_evidence(pg)
    where, params = chat_retrieve._entity_filter("alice-smith", None)
    got = chat_retrieve._lexical_candidates(where, params, "office hours", query_fn(pg))
    assert [i for i, _ in got] == [ids[0]]


def test_keyword_search_over_reddit_text(pg):
    truncate(pg, "reddit_text", "reddit_mentions", "reddit_sentiment")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO reddit_text (source_id, source_type, subreddit, body, body_tsv, flagged) "
                    "VALUES ('c1', 'comment', 'NEU', %s, to_tsvector('english', %s), false)", (MIDTERM, MIDTERM))
        cur.execute("INSERT INTO reddit_mentions (mention_id, source_type, source_id, professor_slug, name_key, method) "
                    "VALUES ('m1', 'comment', 'c1', 'alice-smith', 'alice smith', 'exact')")
        cur.execute("INSERT INTO reddit_sentiment (source_type, source_id, professor_slug, sentiment, score) "
                    "VALUES ('comment', 'c1', 'alice-smith', 'positive', 0.8)")
    pg.commit()
    result = chat_search.keyword_search("midterm curve", query_fn(pg), lambda q, limit=5: [])
    assert [c["source_id"] for c in result["comments"]] == ["c1"]
    assert result["comments"][0]["professor_slugs"] == ["alice-smith"]
    assert result["comments"][0]["sentiments"]["alice-smith"]["sentiment"] == "positive"
