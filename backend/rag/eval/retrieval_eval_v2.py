import os, sys, json, argparse, re
from collections import defaultdict
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from rag.chat_retrieve import retrieve
from rag.eval.eval_common import connect as _connect

_STOP = {"is", "a", "an", "the", "professor", "prof", "dr", "good", "how",
         "hard", "does", "what", "are", "of", "for", "to", "should", "i",
         "take", "class", "with", "as", "beginner", "fair", "grader",
         "harsh", "still", "teaching", "record", "lectures", "homework",
         "much", "assign", "students", "saying", "about", "summarize",
         "reviews", "only", "negative", "positive", "pros", "cons", "and",
         "exams", "similar", "to", "his", "her", "tell", "me", "good"}


def make_fns(conn):
    def query(sql, params=None):
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur.fetchall()

    def query_one(sql, params=None):
        rows = query(sql, params)
        return rows[0] if rows else None
    return query, query_one


def _name_tokens(q):
    """Heuristic gate stand-in: capitalized words that aren't sentence-initial stopwords —
    a crude 'extract the professor name from the question'."""
    cleaned = re.sub(r"[^\w\s]", " ", q)
    toks = [t for t in cleaned.split() if t.lower() not in _STOP and len(t) > 1]
    return " ".join(toks)


def make_prof_search(query, fuzzy=False):
    def prof_search(q, limit=5):
        words = [w for w in (q or "").lower().split() if w and w not in _STOP]
        if not words:
            return []
        if not fuzzy:
            where = " AND ".join("name_key LIKE %s" for _ in words)
            params = [f"%{w}%" for w in words]
            return query("SELECT slug, name, name_key, department, avg_rating, total_reviews "
                         "FROM professors_catalog WHERE " + where +
                         " ORDER BY total_reviews DESC LIMIT %s", params + [limit])
        # fuzzy: per-word similarity OR exact-substring, union, ranked by best similarity
        clauses, params = [], []
        for w in words:
            clauses.append("(name_key LIKE %s OR similarity(name_key, %s) > 0.3)")
            params += [f"%{w}%", w]
        where = " OR ".join(clauses)
        rows = query("SELECT slug, name, name_key, department, avg_rating, total_reviews, "
                     "  greatest(" + ",".join("similarity(name_key, %s)" for _ in words) + ") AS sim "
                     "FROM professors_catalog WHERE " + where +
                     " ORDER BY sim DESC, total_reviews DESC LIMIT %s",
                     [w for w in words] + params + [limit])
        return rows
    return prof_search


def evaluate(eval_set, query, query_one, prof_search):
    """For each question, resolve via the hint (extracted name tokens). Judge correctness
    per the question's expected behavior."""
    by_cat = defaultdict(lambda: {"correct": 0, "total": 0, "detail": []})
    for ex in eval_set:
        cat = ex["category"]; expect = ex["expect"]
        hint = _name_tokens(ex["question"])
        r = retrieve(ex["question"], hint, query, query_one, prof_search, limit=8)
        got = r["professor_slug"]
        # judge
        if expect.startswith("slug:") and "|" not in expect:
            ok = (got == expect.split(":", 1)[1])
        elif expect.startswith("slug:") and "|" in expect:  # comparison: resolving EITHER named prof counts (single-entity retriever can't do both)
            ok = got in expect.split(":", 1)[1].split("|")
        elif expect == "ambiguous":
            # correct = does NOT confidently lock to one specific prof when many share the surname.
            # structured returns the top-by-reviews; we mark "wrong" because it silently picks one.
            ok = (got is None)
        elif expect.startswith("out_of_scope"):
            # correct behavior = NOT answered as a single-prof RAG (got should be None or clearly not a confident named match)
            ok = (got is None)
        else:
            ok = False
        by_cat[cat]["total"] += 1
        by_cat[cat]["correct"] += 1 if ok else 0
        by_cat[cat]["detail"].append({"q": ex["question"], "got": got, "expect": expect, "ok": ok})
    return by_cat


def main():
    p = argparse.ArgumentParser(description="Retrieval bake-off v2 (all categories).")
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if not args.run:
        print("use --run"); return
    eval_set = json.load(open(os.path.join(os.path.dirname(__file__), "eval_set_v2.json"), encoding="utf-8"))
    conn = _connect()
    query, query_one = make_fns(conn)
    for label, fuzzy in [("structured", False), ("structured+fuzzy", True)]:
        ps = make_prof_search(query, fuzzy=fuzzy)
        res = evaluate(eval_set, query, query_one, ps)
        print(f"\n===== {label} =====")
        tot_c = tot_n = 0
        for cat in sorted(res):
            c, n = res[cat]["correct"], res[cat]["total"]
            tot_c += c; tot_n += n
            print(f"  {cat:<22} {c}/{n}")
        print(f"  {'OVERALL':<22} {tot_c}/{tot_n} = {tot_c/tot_n:.0%}")
    conn.close()


if __name__ == "__main__":
    main()
