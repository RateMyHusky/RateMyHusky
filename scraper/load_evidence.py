"""
Build the unified `evidence` corpus (RMP + Reddit) in PostgreSQL for Ask retrieval.
Idempotent. Reads existing source tables; writes `evidence` and, on a prune, each source's
peak row count in `stats_cache` (embeddings are scraper/embed_evidence.py's job).

Usage:
    python load_evidence.py --selftest                            # offline checks, exit
    python load_evidence.py --build-evidence --prune              # the weekly rebuild
    python load_evidence.py --build-evidence --prune --dry-run    # report the plan, write nothing
"""
import argparse, itertools, os, sys, time, re, hashlib, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from denylist import is_denied_key  # noqa: E402
from dotenv import load_dotenv
import psycopg2

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", ".env"))
URL = os.getenv("ORACLE_DATABASE_URL")

_counter = itertools.count()

# The evidence / evidence_embeddings schema lives in db/postgres/ (02_tables.sql,
# 03_constraints.sql); this loader never creates tables. There is deliberately no
# vector index on evidence_embeddings: retrieval is entity-scoped (filter on
# ev_prof / ev_course, then exact cosine over that entity's rows), so a global
# index would buy nothing and only slow the embedding backfill's writes.

def connect(attempts=20):
    last = None
    for i in range(1, attempts + 1):
        try:
            return psycopg2.connect(URL, sslmode="require", options="-c timezone=UTC")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e):
                raise
            last = str(e)
            print(f"  DNS lookup flaked; retrying ({i}/{attempts})...")
            time.sleep(1.5)
    raise SystemExit(f"Could not connect after {attempts} attempts: {last}")

# ── Sanitization + injection screening (mirrored from load_reddit.py) ──

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)

_INJECTION_PATTERNS = [
    (re.compile(r"ignore (all |the |any |previous )?(instructions|rules|prompts?)", re.I), "ignore_instructions"),
    (re.compile(r"you are now", re.I), "persona_switch"),
    (re.compile(r"</?(system|user|assistant|instructions?)\s*>", re.I), "role_tag"),
    (re.compile(r"<\|.*?\|>"), "chatml_token"),
    (re.compile(r"(disregard|override|bypass) (all|the|any|your|previous|the above)", re.I), "override"),
]

def sanitize_body(text: str) -> str:
    """NFKC-normalize, strip zero-width/control chars, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_ZERO_WIDTH)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return re.sub(r"\s+", " ", text).strip()

def injection_flag(text: str) -> "tuple[bool, str | None]":
    """Return (True, reason) if text matches an injection pattern, else (False, None)."""
    for pat, reason in _INJECTION_PATTERNS:
        if pat.search(text or ""):
            return True, reason
    return False, None

# ── Pure helper functions ──

_NA = {"", "n/a", "na", "none", "no", "-", ".", "nothing", "no comment", "no comments"}

def norm_code(s: str) -> str:
    """Uppercase and strip all whitespace from a course code string."""
    return re.sub(r"\s+", "", str(s or "").upper())

def body_sha(text: str) -> str:
    """SHA-256 hex digest (first 32 chars) of text."""
    return hashlib.sha256((text or "").encode()).hexdigest()[:32]

def is_meaningful(text: str) -> bool:
    """Return True if text passes the quality filter: non-empty, not n/a, >=15 chars."""
    t = sanitize_body(text)
    if not t or t.lower() in _NA:
        return False
    return len(t.strip()) >= 15

def dedup_key(text: str) -> str:
    """Normalized 80-char prefix for deduplication (matches professor_full._dedup_group)."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()[:80]

def _row(source, source_ref, slug, code, body, sentiment=None, score=None,
         permalink=None, subreddit=None, created_utc=None, rmp_meta=None):
    """Build an evidence-row dict."""
    clean = sanitize_body(body)
    flagged, _reason = injection_flag(clean)
    return {
        "source": source,
        "source_ref": str(source_ref),
        "professor_slug": slug,
        # empty-string sentinel, never NULL — ev_dedupe is a plain 4-column unique
        # index, and a NULL course_code would never conflict, so re-runs would
        # duplicate every course-less row.
        "course_code": code or "",
        "body": clean,
        "body_sha": body_sha(clean),
        "sentiment": sentiment,
        "reddit_score": score,
        "permalink": permalink,
        "subreddit": subreddit,
        "created_utc": created_utc,
        "rmp_meta": rmp_meta,
        "flagged": flagged,
    }

# ── Build functions (pure — take injected query_fn, no live DB) ──

def build_reddit_rows(query_fn) -> list:
    """Yield evidence rows from reddit_mentions + reddit_text + reddit_sentiment."""
    rows = query_fn("""
        SELECT m.source_id, m.professor_slug, t.body, t.subreddit, t.created_utc, t.score, t.permalink,
               s.sentiment, t.flagged
        FROM reddit_mentions m
        JOIN reddit_text t ON t.source_id = m.source_id
        LEFT JOIN reddit_sentiment s
          ON s.source_id = t.source_id AND s.professor_slug = m.professor_slug
    """, ())
    # Reddit rows carry a slug and no name, so they cannot be tested against the
    # denylist directly. Restricting to slugs professors_catalog still holds does
    # it transitively — precompute drops a denied professor from the catalog —
    # and independently drops mentions pointing at professors who no longer
    # exist, which were unreachable from the site but still retrievable by chat.
    known_slugs = {r["slug"] for r in query_fn("SELECT slug FROM professors_catalog", ())}
    out = []
    for r in rows:
        if not is_meaningful(r.get("body")):
            continue
        if r.get("professor_slug") not in known_slugs:
            continue
        ev = _row("reddit", r["source_id"], r.get("professor_slug"), None, r.get("body"),
                  sentiment=r.get("sentiment"), score=r.get("score"), permalink=r.get("permalink"),
                  subreddit=r.get("subreddit"), created_utc=r.get("created_utc"))
        ev["flagged"] = bool(r.get("flagged")) or ev["flagged"]
        out.append(ev)
    return out

def build_rmp_rows(query_fn) -> list:
    """Yield evidence rows from rmp_reviews, carrying the precomputed rmp_reviews.course_code."""
    catalog = query_fn("SELECT name_key, slug FROM professors_catalog", ())
    slug_by_key = {r["name_key"]: r["slug"] for r in catalog}
    rows = query_fn("""SELECT id, name_key, course, course_code, comment, quality, difficulty, tags, grade
                       FROM rmp_reviews WHERE comment IS NOT NULL AND comment <> ''""", ())
    out = []
    for r in rows:
        if not is_meaningful(r.get("comment")):
            continue
        slug = slug_by_key.get(r.get("name_key"))
        if not slug:
            continue
        # Belt and braces on a data-deletion request. Once precompute has run
        # with the denylist the professor is absent from professors_catalog and
        # the lookup above already fails — but an evidence build against a
        # catalog written before the request would otherwise re-embed them, and
        # this corpus is what the chat quotes.
        if is_denied_key(r.get("name_key")):
            continue
        course_code = norm_code(r.get("course_code")) or None
        meta = {
            "course": r.get("course"),
            "quality": r.get("quality"),
            "difficulty": r.get("difficulty"),
            "tags": r.get("tags"),
            "grade": r.get("grade"),
        }
        out.append(_row("rmp", r["id"], slug, course_code, r.get("comment"), rmp_meta=meta))
    return out

# ── Upsert ──

def upsert_evidence(conn, rows, batch=1000):
    """Insert evidence rows with ON CONFLICT DO UPDATE; computes body_tsv via SQL."""
    from psycopg2.extras import execute_values
    import json

    def _jsonb(v):
        return json.dumps(v) if v is not None else None

    sql = """
        INSERT INTO evidence
          (source, source_ref, professor_slug, course_code, body, body_tsv, body_sha,
           sentiment, reddit_score, permalink, subreddit, created_utc, rmp_meta, flagged)
        VALUES %s
        ON CONFLICT (source, source_ref, professor_slug, course_code)
        DO UPDATE SET
          body         = excluded.body,
          body_tsv     = excluded.body_tsv,
          body_sha     = excluded.body_sha,
          flagged      = excluded.flagged,
          sentiment    = excluded.sentiment,
          reddit_score = excluded.reddit_score,
          permalink    = excluded.permalink,
          created_utc  = excluded.created_utc,
          rmp_meta     = excluded.rmp_meta,
          subreddit    = excluded.subreddit
    """
    template = "(%(source)s, %(source_ref)s, %(professor_slug)s, %(course_code)s, %(body)s, to_tsvector('english', %(tsv_src)s), %(body_sha)s, %(sentiment)s, %(reddit_score)s, %(permalink)s, %(subreddit)s, %(created_utc)s, %(rmp_meta)s, %(flagged)s)"

    total = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        values = []
        for r in chunk:
            values.append({
                "source": r["source"],
                "source_ref": r["source_ref"],
                "professor_slug": r.get("professor_slug"),
                "course_code": r.get("course_code"),
                "body": r["body"],
                "tsv_src": r["body"],
                "body_sha": r["body_sha"],
                "sentiment": r.get("sentiment"),
                "reddit_score": r.get("reddit_score"),
                "permalink": r.get("permalink"),
                "subreddit": r.get("subreddit"),
                "created_utc": r.get("created_utc"),
                "rmp_meta": _jsonb(r.get("rmp_meta")),
                "flagged": bool(r.get("flagged")),
            })
        # A batch can hit a transient SerializationFailure (40001) under concurrent
        # writes; retry with backoff. Each batch commits independently, so a retried
        # batch is safe (the ON CONFLICT upsert is idempotent).
        for attempt in range(6):
            try:
                with conn.cursor() as cur:
                    execute_values(cur, sql, values, template=template)
                conn.commit()
                break
            except psycopg2.errors.SerializationFailure:
                conn.rollback()
                if attempt == 5:
                    raise
                time.sleep(0.5 * (2 ** attempt))
        total += len(chunk)
    return total

# ── Safety guard: plan both sources, check them, and only then write ──
#
# Every check runs before the upsert and before any delete, for both sources, so a build
# that looks broken writes nothing at all. The real weekly delta is tens of rows: ~0.03%
# stale (14 of 41k rmp rows, 0 reddit) and a few dozen changed bodies.
#
# A prune that would remove more than this share of a source's rows is treated as a
# broken build, not as deletions.
PRUNE_CEILING = 0.05
# A build that would rewrite the text of more than this share of a source's existing rows
# is treated as a broken build too (mangled bodies would otherwise be upserted and
# re-embedded the same day).
CHANGE_CEILING = 0.05
# The weekly ceilings compound: 5% a week is ~40% in ten weeks. So a build may also not
# fall more than this far below the source's peak, the most rows a pruned build has ever
# held, kept in stats_cache under PEAK_KEY.
DRAIN_CEILING = 0.10
PEAK_KEY = "evidence_peak:{}"
SOURCES = ("reddit", "rmp")


def row_key(source_ref, professor_slug, course_code):
    """The evidence row's identity: ev_dedupe's columns past `source`. A row whose comment
    still exists but now belongs to another professor or course is a different row."""
    return (str(source_ref), professor_slug or "", course_code or "")


def check_prune(source: str, n_db: int, n_fresh: int, n_stale: int, force: bool,
                n_changed: int = 0, peak=None, prune: bool = True) -> None:
    """Refuse a build that looks broken. An empty build is refused even with force
    (nothing legitimate produces zero rows for a populated source); a prune over
    PRUNE_CEILING, a rewrite over CHANGE_CEILING, or a build over DRAIN_CEILING below the
    source's peak needs force."""
    if n_fresh == 0 and n_db > 0:
        raise SystemExit(
            f"Refusing to write {source}: the build produced 0 rows but the database holds "
            f"{n_db}. The source tables are probably empty or unreadable; nothing was written."
        )
    if force:
        return
    if prune and n_stale > PRUNE_CEILING * n_db:
        raise SystemExit(
            f"Refusing to prune {source}: {n_stale} of {n_db} rows "
            f"({n_stale / n_db:.1%}) are stale, over the {PRUNE_CEILING:.0%} ceiling. "
            f"Nothing was written. Re-run with --force if this is expected."
        )
    if n_changed > CHANGE_CEILING * n_db:
        raise SystemExit(
            f"Refusing to write {source}: the build changes the text of {n_changed} of {n_db} "
            f"rows ({n_changed / n_db:.1%}), over the {CHANGE_CEILING:.0%} ceiling. "
            f"Nothing was written. Re-run with --force if this is expected."
        )
    if peak and n_fresh < (1 - DRAIN_CEILING) * peak:
        raise SystemExit(
            f"Refusing to write {source}: the build has {n_fresh} rows, {1 - n_fresh / peak:.1%} "
            f"under the source's peak of {peak} (limit {DRAIN_CEILING:.0%}). Small weekly "
            f"losses add up; nothing was written. Re-run with --force if this is expected."
        )


def plan_source(conn, source, rows):
    """Compare the build's rows for `source` with the database: which rows would go
    (stale_ids), how many existing rows would get new text, and the source's peak."""
    fresh = {row_key(r["source_ref"], r.get("professor_slug"), r.get("course_code")): r["body_sha"]
             for r in rows}
    with conn.cursor() as cur:
        cur.execute("SELECT id, source_ref, professor_slug, course_code, body_sha "
                    "FROM evidence WHERE source = %s", (source,))
        db_rows = cur.fetchall()
        cur.execute("SELECT value FROM stats_cache WHERE key = %s", (PEAK_KEY.format(source),))
        peak_row = cur.fetchone()
    stale_ids, changed = [], 0
    for row_id, ref, slug, code, sha in db_rows:
        key = row_key(ref, slug, code)
        if key not in fresh:
            stale_ids.append(row_id)
        elif fresh[key] != sha:
            changed += 1
    return {"source": source, "n_db": len(db_rows), "n_fresh": len(fresh),
            "stale_ids": stale_ids, "n_changed": changed,
            "peak": peak_row[0] if peak_row else None}


def check_plans(plans, force, prune):
    for p in plans:
        check_prune(p["source"], p["n_db"], p["n_fresh"], len(p["stale_ids"]), force,
                    n_changed=p["n_changed"], peak=p["peak"], prune=prune)


def prune_evidence(conn, plans, force=False, batch=1000):
    """Delete every source's stale rows (embeddings first, so no orphan vectors remain) and
    record each source's new peak, all in ONE transaction: a failure leaves the corpus as it
    was, never half-pruned. Returns {source: rows deleted}."""
    for attempt in range(6):
        try:
            deleted = {}
            with conn.cursor() as cur:
                for p in plans:
                    deleted[p["source"]] = 0
                    ids = p["stale_ids"]
                    for start in range(0, len(ids), batch):
                        chunk = ids[start:start + batch]
                        cur.execute("DELETE FROM evidence_embeddings WHERE evidence_id = ANY(%s::uuid[])", (chunk,))
                        cur.execute("DELETE FROM evidence WHERE id = ANY(%s::uuid[])", (chunk,))
                        deleted[p["source"]] += cur.rowcount
                    # After the prune the source holds exactly the build's rows. --force is how
                    # a deliberate shrink is accepted, so it also lowers the peak.
                    peak = p["n_fresh"] if force else max(p["peak"] or 0, p["n_fresh"])
                    cur.execute("INSERT INTO stats_cache (key, value) VALUES (%s, %s) "
                                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                                (PEAK_KEY.format(p["source"]), peak))
            conn.commit()
            return deleted
        except psycopg2.errors.SerializationFailure:
            conn.rollback()
            if attempt == 5:
                raise
            time.sleep(0.5 * (2 ** attempt))

def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    # ── norm_code ──
    check("norm_code uppercases + strips space", norm_code("cs 3500") == "CS3500")
    check("norm_code on clean code", norm_code("EECE2140") == "EECE2140")

    # ── is_meaningful ──
    check("meaningful keeps a real comment", is_meaningful("Great professor, very clear lectures") is True)
    check("meaningful drops n/a", is_meaningful("N/A") is False)
    check("meaningful drops blank", is_meaningful("   ") is False)
    check("meaningful drops <15 chars", is_meaningful("good prof") is False)

    # ── dedup_key ──
    check("dedup_key collapses whitespace + case + caps at 80",
          dedup_key("Great   Prof") == dedup_key("great prof"))

    # ── Reddit rows: one per mention, sentiment + score carried ──
    def reddit_q(sql, params=None):
        if "reddit_mentions" in sql:
            return [{"source_id": "c1", "professor_slug": "guha-prof", "body": "hard but fair, great office hours",
                     "subreddit": "NEU", "score": 12, "permalink": "/r/x",
                     "sentiment": "positive", "flagged": False}]
        if "professors_catalog" in sql:
            return [{"slug": "guha-prof"}]
        return []
    rr = build_reddit_rows(reddit_q)
    check("reddit row source tag", rr[0]["source"] == "reddit")
    check("reddit row keyed to prof", rr[0]["professor_slug"] == "guha-prof")
    check("reddit row carries sentiment", rr[0]["sentiment"] == "positive")
    check("reddit row carries score", rr[0]["reddit_score"] == 12)
    check("reddit row course_code is '' sentinel (never None)", rr[0]["course_code"] == "")
    check("reddit row has body_sha", len(rr[0]["body_sha"]) == 32)
    check("reddit row carries subreddit", rr[0]["subreddit"] == "NEU")

    # ── RMP rows: course_code comes from the precomputed rmp_reviews.course_code ──
    def rmp_q(sql, params=None):
        if "rmp_reviews" in sql:
            return [
                {"id": "r1", "name_key": "olin guha", "course": "3500", "course_code": "CS3500", "comment": "Tough grader but I learned a ton in this class",
                 "quality": 5, "difficulty": 4, "tags": "GIVES GOOD FEEDBACK", "grade": "A"},
                {"id": "r2", "name_key": "olin guha", "course": "Algorithms", "course_code": None, "comment": "Loved the material and the pacing of the course",
                 "quality": 4, "difficulty": 3, "tags": "", "grade": "B"},
            ]
        if "professors_catalog" in sql:
            return [{"name_key": "olin guha", "slug": "guha-prof"}]
        return []
    mr = build_rmp_rows(rmp_q)
    check("rmp row tagged rmp", all(r["source"] == "rmp" for r in mr))
    check("rmp keyed to prof slug", all(r["professor_slug"] == "guha-prof" for r in mr))
    check("rmp resolved code keeps course_code", mr[0]["course_code"] == "CS3500")
    check("rmp unresolved course -> course_code '' (kept, prof-only)", mr[1]["course_code"] == "")
    check("rmp carries meta", mr[0]["rmp_meta"]["quality"] == 5 and mr[0]["rmp_meta"]["grade"] == "A")

    # ── Issue 24: upsert refreshes mutable metadata columns, not just body/flagged ──
    upsert_sql_holder = []
    class _FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): upsert_sql_holder.append(sql); self.rowcount = 0
    class _FakeConn:
        def cursor(self, *a, **k): return _FakeCursor()
        def commit(self): pass
        def rollback(self): pass
    def _fake_execute_values(cur, sql, values, template=None):
        upsert_sql_holder.append(sql)
    import psycopg2.extras as _pge
    _saved = _pge.execute_values
    _pge.execute_values = _fake_execute_values
    try:
        upsert_evidence(_FakeConn(), [_row("reddit", "r1", "guha-prof", None, "great professor and clear lectures")])
    finally:
        _pge.execute_values = _saved
    upsert_sql = re.sub(r"\s+", " ", upsert_sql_holder[-1])
    for col in ("sentiment", "reddit_score", "permalink", "created_utc", "rmp_meta", "subreddit"):
        check(f"upsert SET-list refreshes {col}", f"{col} = excluded.{col}" in upsert_sql)

    # ── Prune guard: plan by full row key, check before writing, delete by id in one commit ──
    class _FakeEvidenceCursor:
        def __init__(self, conn): self.conn = conn; self.rowcount = 0; self._last = ""
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            self._last = sql
            self.conn.statements.append((sql, params))
            if sql.startswith("DELETE FROM evidence WHERE"):
                self.rowcount = len(params[0])
        def fetchall(self): return self.conn.db_rows
        def fetchone(self): return (self.conn.peak,) if self.conn.peak is not None else None
    class _FakeEvidenceConn:
        def __init__(self, db_rows, peak=None):
            self.db_rows, self.peak, self.statements, self.commits = db_rows, peak, [], 0
        def cursor(self, *a, **k): return _FakeEvidenceCursor(self)
        def commit(self): self.commits += 1
        def rollback(self): pass
    keep = _row("reddit", "c1", "guha-prof", None, "hard but fair, great office hours")
    moved = _row("reddit", "c2", "lee-prof", None, "the midterm curve was generous this term")
    db = [(1, "c1", "guha-prof", "", keep["body_sha"]),
          (2, "c2", "wrong-prof", "", moved["body_sha"]),     # same comment, re-matched to lee-prof
          (3, "c3", "guha-prof", "", "oldsha")]               # gone from the build
    plan = plan_source(_FakeEvidenceConn(db, peak=3), "reddit", [keep, moved])
    check("plan: a comment re-matched to another professor leaves its old row stale",
          plan["stale_ids"] == [2, 3])
    check("plan: counts rows and reads the peak", plan["n_db"] == 3 and plan["n_fresh"] == 2 and plan["peak"] == 3)
    pconn = _FakeEvidenceConn(db)
    deleted = prune_evidence(pconn, [plan], force=True, batch=1)
    deletes = [st for st in pconn.statements if st[0].startswith("DELETE")]
    check("prune deletes embeddings before evidence, by id, per batch",
          [st[0].split(" WHERE")[0] for st in deletes] == ["DELETE FROM evidence_embeddings",
                                                            "DELETE FROM evidence"] * 2
          and [st[1][0] for st in deletes] == [[2], [2], [3], [3]])
    check("prune commits once and reports per source", pconn.commits == 1 and deleted == {"reddit": 2})
    check("forced prune resets the peak to the build",
          any("stats_cache" in st[0] and st[1] == ("evidence_peak:reddit", 2) for st in pconn.statements))
    try:
        check_plans([plan], force=False, prune=True)   # 2 of 3 stale: over the ceiling
        refused = False
    except SystemExit:
        refused = True
    check("an over-ceiling plan is refused", refused)

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0

def main():
    parser = argparse.ArgumentParser(description="Build the evidence corpus in PostgreSQL")
    parser.add_argument("--selftest", action="store_true", help="Run offline checks")
    parser.add_argument("--build-evidence", action="store_true", help="Populate evidence from all sources")
    parser.add_argument("--prune", action="store_true",
                         help="After building, delete evidence rows (+ their embeddings) the build "
                              "no longer produces: a gone comment or review, or one now under another "
                              "professor or course (requires --build-evidence)")
    parser.add_argument("--force", action="store_true",
                         # argparse %-formats help text, so the percent signs are doubled.
                         help=(f"Accept a build over the safety ceilings: more than "
                               f"{PRUNE_CEILING:.0%} of a source's rows stale or "
                               f"{CHANGE_CEILING:.0%} rewritten, or over {DRAIN_CEILING:.0%} "
                               "under its peak (also resets the peak); requires --prune"
                               ).replace("%", "%%"))
    parser.add_argument("--dry-run", action="store_true",
                         help="Build and run the checks, print what would change, write nothing")
    args = parser.parse_args()
    if args.force and not args.prune:
        parser.error("--force requires --prune")

    if args.selftest:
        sys.exit(selftest())

    if args.build_evidence:
        import psycopg2.extras
        conn = connect()

        def query_fn(sql, params=None):
            with conn.cursor(name=f"ev_cur_{next(_counter)}", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or ())
                return cur.fetchall()

        built = {"reddit": build_reddit_rows(query_fn), "rmp": build_rmp_rows(query_fn)}
        # Both sources are planned and checked before anything is written, so a build that
        # fails a check (either source) leaves the corpus exactly as it was.
        plans = [plan_source(conn, source, built[source]) for source in SOURCES]
        for p in plans:
            print(f"{p['source']}: {p['n_fresh']} built, {p['n_db']} in the database, "
                  f"{len(p['stale_ids'])} stale, {p['n_changed']} with new text, peak {p['peak']}")
        check_plans(plans, force=args.force, prune=args.prune)
        if args.dry_run:
            print("Dry run: nothing written")
            conn.close()
            sys.exit(0)

        n = upsert_evidence(conn, built["reddit"] + built["rmp"])
        print(f"Upserted {n} evidence rows")

        if args.prune:
            for source, deleted in prune_evidence(conn, plans, force=args.force).items():
                print(f"Pruned {deleted} stale {source} evidence rows")

        conn.close()
        sys.exit(0)

    print("Use --selftest for offline checks or --build-evidence to populate")
    sys.exit(0)

if __name__ == "__main__":
    main()
