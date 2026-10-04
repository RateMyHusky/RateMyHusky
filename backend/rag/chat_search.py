import sys, re, argparse

# A course code mentioned inside a comment body, e.g. "PHIL 3100", "BIO3100": 2–5 letters
# then 4 digits, optional space. Used to link a citation to a course profile.
_BODY_COURSE_RE = re.compile(r"\b([A-Za-z]{2,5})\s?(\d{4})\b")

def _resolve_link(comment, query_fn):
    """Pick the [N] citation's link target. Prefer the curated professor_slug (from
    reddit_mentions); else a course code mentioned in the body that exists in the catalog;
    else None (rendered as a plain, unlinked [N])."""
    slugs = comment.get("professor_slugs") or []
    if slugs:
        return {"type": "professor", "value": slugs[0]}
    for letters, digits in _BODY_COURSE_RE.findall(comment.get("body") or ""):
        code = f"{letters}{digits}".upper()
        row = query_fn("SELECT code FROM course_catalog WHERE code = %s", (code,))
        if row:
            return {"type": "course", "value": row[0]["code"]}
    return None

def keyword_search(q, query_fn, prof_search_fn, limit=20, mod_filter=""):
    # Two independent gates, same as fetch_reddit_mentions: t.flagged is the
    # scraper's prompt-injection marker, mod_filter is the content verdict. The
    # caller passes mod_filter in so rag/ keeps its no-backend-root-imports rule.
    rows = query_fn(f"""
        SELECT t.source_id, t.body, t.subreddit, t.permalink,
               array_agg(DISTINCT m.professor_slug) AS professor_slugs,
               ts_rank(t.body_tsv, plainto_tsquery('english', %s)) AS rank
        FROM reddit_text t
        JOIN reddit_mentions m ON m.source_id = t.source_id
        WHERE t.flagged = false{mod_filter}
          AND t.body_tsv @@ plainto_tsquery('english', %s)
        GROUP BY t.source_id, t.body, t.subreddit, t.permalink, t.body_tsv
        ORDER BY rank DESC
        LIMIT %s
    """, (q, q, limit))

    if not rows:
        return {"comments": [], "professors": prof_search_fn(q, limit=5)}

    source_ids = [r["source_id"] for r in rows]
    sentiment_rows = query_fn("""
        SELECT source_id, professor_slug, sentiment, score
        FROM reddit_sentiment
        WHERE source_id = ANY(%s)
    """, (source_ids,))

    # Build per-source_id sentiment map: {source_id: {slug: {sentiment, score}}}
    sentiments_by_sid = {}
    for s in sentiment_rows:
        sid = s["source_id"]
        if sid not in sentiments_by_sid:
            sentiments_by_sid[sid] = {}
        sentiments_by_sid[sid][s["professor_slug"]] = {
            "sentiment": s.get("sentiment"),
            "score": s.get("score"),
        }

    comments = []
    for r in rows:
        body = r.get("body") or ""
        sid = r["source_id"]
        comments.append({
            "source_id": sid,
            "professor_slugs": list(r.get("professor_slugs") or []),
            "snippet": body[:240],
            "sentiments": sentiments_by_sid.get(sid, {}),
            "subreddit": r.get("subreddit"),
            "permalink": r.get("permalink"),
            "rank": r.get("rank"),
            "link": _resolve_link(r, query_fn),
        })

    return {"comments": comments, "professors": prof_search_fn(q, limit=5)}

def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    captured_main_sql = []

    def query_fn(sql, params):
        if "reddit_sentiment" in sql and "ANY(%s)" in sql:
            # Second query: sentiment by source_id
            return [
                {"source_id": "c1", "professor_slug": "ada-lovelace",
                 "sentiment": "positive", "score": 0.6},
            ]
        # Main deduped query
        captured_main_sql.append(sql)
        check("query excludes flagged rows", "flagged = false" in sql or "NOT flagged" in sql)
        check("query is parameterized", "%s" in sql)
        check("query uses CRDB-supported tsquery (plainto_tsquery)", "plainto_tsquery" in sql)
        check("query avoids unsupported websearch_to_tsquery", "websearch_to_tsquery" not in sql)
        return [
            {"source_id": "c1", "body": "great grader", "subreddit": "NEU",
             "permalink": "/r/x", "professor_slugs": ["ada-lovelace"], "rank": 0.9},
        ]

    def prof_search_fn(q, limit=5):
        return [{"slug": "ada-lovelace", "name": "Ada Lovelace"}]

    result = keyword_search("grader", query_fn, prof_search_fn, limit=20)
    check("returns dict with comments and professors", isinstance(result, dict)
          and "comments" in result and "professors" in result)
    check("comments is non-empty", len(result["comments"]) == 1)
    check("result has snippet", "snippet" in result["comments"][0])
    check("professor_slugs is a list", isinstance(result["comments"][0]["professor_slugs"], list))
    check("sentiments is a dict", isinstance(result["comments"][0]["sentiments"], dict))
    check("sentiment carries data for slug",
          result["comments"][0]["sentiments"].get("ada-lovelace", {}).get("sentiment") == "positive")
    check("professors == stub list", result["professors"] == [{"slug": "ada-lovelace", "name": "Ada Lovelace"}])

    # ── per-comment link target ([N] should link to a profile) ──
    # A comment WITH a professor_slug links to that professor (curated data wins).
    check("comment with slug -> professor link",
          result["comments"][0].get("link") == {"type": "professor", "value": "ada-lovelace"})

    # A comment with NO slug but a catalog-verified course code in its body -> course link.
    # One without any resolvable entity -> link is None (rendered as plain [N], no anchor).
    def link_query_fn(sql, params):
        if "reddit_sentiment" in sql and "ANY(%s)" in sql:
            return []
        if "course_catalog" in sql:
            check("course lookup normalizes/uppercases code", params and params[0] == "PHIL3100")
            return [{"code": "PHIL3100"}]   # PHIL3100 exists; off-topic comment's code won't
        return [
            {"source_id": "c2", "body": "PHIL 3100: Religious Worlds — anyone have the syllabus?",
             "subreddit": "NEU", "permalink": "/r/a", "professor_slugs": [], "rank": 0.8},
            {"source_id": "c3", "body": "How does Oakland compare to Boston, no course here",
             "subreddit": "NEU", "permalink": "/r/b", "professor_slugs": [], "rank": 0.5},
        ]
    res2 = keyword_search("3100", link_query_fn, lambda q, limit=5: [], limit=20)
    by_id = {c["source_id"]: c for c in res2["comments"]}
    check("comment w/ course code in body -> course link",
          by_id["c2"].get("link") == {"type": "course", "value": "PHIL3100"})
    check("comment with no entity -> link is None", by_id["c3"].get("link") is None)

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0

def main():
    p = argparse.ArgumentParser(description="Reddit keyword search helper.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")

if __name__ == "__main__":
    main()
