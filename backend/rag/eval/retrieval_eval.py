import os, sys, json, argparse
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from rag.chat_retrieve import retrieve
from rag.eval.eval_common import connect as _connect


def make_query_fns(conn):
    def query(sql, params=None):
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur.fetchall()

    def query_one(sql, params=None):
        rows = query(sql, params)
        return rows[0] if rows else None

    return query, query_one


def make_prof_search(query):
    """Thin stand-in for server._professor_search: word-level name_key LIKE match,
    ranked by total_reviews. Avoids importing server.py (Flask side effects)."""
    def prof_search(q, limit=5):
        words = [w for w in (q or "").lower().split() if w]
        if not words:
            return []
        where = " AND ".join("name_key LIKE %s" for _ in words)
        params = [f"%{w}%" for w in words]
        return query(
            "SELECT slug, name, name_key, department, avg_rating, total_reviews "
            "FROM professors_catalog WHERE " + where + " "
            "ORDER BY total_reviews DESC LIMIT %s",
            params + [limit],
        )
    return prof_search


def score_retriever(retriever_fn, eval_set, query, query_one, prof_search, hint_fn=None):
    hits, misses = 0, []
    for ex in eval_set:
        hint = hint_fn(ex) if hint_fn else None
        r = retriever_fn(ex["question"], hint, query, query_one, prof_search, limit=8)
        if r["professor_slug"] == ex["expected_slug"]:
            hits += 1
        else:
            misses.append({"q": ex["question"], "got": r["professor_slug"], "want": ex["expected_slug"]})
    n = len(eval_set)
    return {"accuracy": hits / n if n else 0.0, "n": n, "hits": hits, "misses": misses}


def main():
    p = argparse.ArgumentParser(description="Retrieval bake-off scorer (structured-first A).")
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if not args.run:
        print("use --run to score retriever A against the live DB")
        return
    eval_set = json.load(open(os.path.join(os.path.dirname(__file__), "eval_set.json"), encoding="utf-8"))
    conn = _connect()
    query, query_one = make_query_fns(conn)
    prof_search = make_prof_search(query)

    # Retriever A, raw-query (no LLM hint) — the brief's default measurement.
    raw = score_retriever(retrieve, eval_set, query, query_one, prof_search)
    # Retriever A, hint-assisted (simulate the gate extracting the prof name = the production path).
    #   The classifier hint in prod is the professor name; here we use the expected prof's display
    #   name as the hint to measure resolution quality WHEN the gate does its job.
    name_by_slug = {}
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT slug, name FROM professors_catalog WHERE slug = ANY(%s)",
                ([e["expected_slug"] for e in eval_set],))
    for row in cur.fetchall():
        name_by_slug[row["slug"]] = row["name"]
    hinted = score_retriever(retrieve, eval_set, query, query_one, prof_search,
                             hint_fn=lambda ex: name_by_slug.get(ex["expected_slug"]))
    conn.close()
    print(json.dumps({"A_raw_query": {k: v for k, v in raw.items() if k != "misses"},
                      "A_hint_assisted": {k: v for k, v in hinted.items() if k != "misses"}}, indent=2))
    print("\n-- raw-query misses (first 15) --")
    for m in raw["misses"][:15]:
        print(f"  got={m['got']}  want={m['want']}  q={m['q']!r}")


if __name__ == "__main__":
    main()
