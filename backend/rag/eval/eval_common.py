"""Shared plumbing for backend/rag/eval scripts: live-DB connection (DNS-retry),
query fns, professor-search stand-in, natural-key label resolution, and run-folder helpers."""
import os, sys, json, time, argparse, datetime, subprocess

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(os.path.dirname(EVAL_DIR))
RUNS_DIR = os.path.join(EVAL_DIR, "runs")
QUESTIONS_PATH = os.path.join(EVAL_DIR, "eval_questions.json")
QRELS_PATH = os.path.join(EVAL_DIR, "qrels.json")
POOL_PATH = os.path.join(EVAL_DIR, "pool.json")
sys.path.insert(0, BACKEND_DIR)


def connect(attempts=20):
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_DIR, ".env"))
    url = os.getenv("ORACLE_DATABASE_URL")
    if not url:
        sys.exit("Need ORACLE_DATABASE_URL in backend/.env")
    last = None
    for i in range(1, attempts + 1):
        try:
            return psycopg2.connect(url, sslmode="require", connect_timeout=20,
                                    options="-c timezone=UTC")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e):
                raise
            last = str(e)
            print(f"  DNS lookup flaked; retrying ({i}/{attempts})...")
            time.sleep(3)
    sys.exit(f"Could not resolve the database host after {attempts} attempts.\n{last}")


def make_query_fns(conn):
    from psycopg2.extras import RealDictCursor
    def query(sql, params=None):
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur.fetchall()
    def query_one(sql, params=None):
        rows = query(sql, params)
        return rows[0] if rows else None
    return query, query_one


def make_prof_search(query):
    """Thin stand-in for server._professor_search (avoids importing server.py's Flask side
    effects): word-level name_key LIKE match, ranked by total_reviews."""
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
            params + [limit])
    return prof_search


def unit_id(question_id, entity):
    return f"{question_id}::{entity.get('slug') or entity.get('code')}"


def entity_args(entity):
    """(slug, code) positional pair for fetch_evidence / _entity_filter."""
    return entity.get("slug"), entity.get("code")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BACKEND_DIR).decode().strip()
    except Exception:
        return "unknown"


def new_run_dir(label, runs_dir=None):
    """Build a fresh timestamped run dir path under runs_dir (default RUNS_DIR). Does not
    create it -- ensure_run_dir validates containment before creating."""
    runs_dir = RUNS_DIR if runs_dir is None else runs_dir
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    return os.path.join(runs_dir, f"{stamp}-{label}")


def ensure_run_dir(run_dir_arg, label, runs_dir=None):
    """Resolve the eval run dir (an explicit --run-dir, or a freshly stamped one from
    `label`) and require it sits DIRECTLY inside runs_dir -- its realpath's parent must equal
    realpath(runs_dir). answers.json/retrieval_metrics.json are only covered by the
    backend/rag/eval/runs/*/answers.json* gitignore rule when the run dir is a direct child of
    runs/, so a relative --run-dir that resolves elsewhere (e.g. 'runs/../evil'), an absolute
    path outside runs_dir, or a --label containing '/' (nesting the dir another level) are
    all rejected instead of silently writing evidence bodies somewhere ungitignored. Creates
    the dir and returns its resolved path. runs_dir defaults to RUNS_DIR; overridable only so
    the selftest below can point it at a scratch temp dir instead of littering the real
    backend/rag/eval/runs."""
    runs_dir = RUNS_DIR if runs_dir is None else runs_dir
    path = run_dir_arg or new_run_dir(label, runs_dir)
    resolved = os.path.realpath(path)
    base = os.path.realpath(runs_dir)
    if os.path.dirname(resolved) != base:
        sys.exit(f"run dir must be a single directory directly under {base} (got: {resolved})")
    os.makedirs(resolved, exist_ok=True)
    return resolved


def hydrate_natural_keys(ids, query_fn):
    if not ids:
        return {}
    rows = query_fn(
        "SELECT id, source, source_ref, professor_slug, course_code, body_sha "
        "FROM evidence WHERE id IN %s", (tuple(ids),))
    return {str(r["id"]): {"source": r["source"], "source_ref": r["source_ref"],
                           "professor_slug": r.get("professor_slug"),
                           "course_code": r.get("course_code") or "",
                           "body_sha": r.get("body_sha")} for r in rows}


def _nk(label_or_row):
    return (label_or_row["source"], label_or_row["source_ref"],
            label_or_row.get("professor_slug"), label_or_row.get("course_code") or "")


def rel_lookup(labels, run_ids, query_fn):
    """Map run evidence ids (str) -> graded rel. A uuid miss (corpus reloaded since labeling)
    falls back to natural-key matching. Returns (rel_by_id, unlabeled_ids)."""
    by_uuid = {l["evidence_id"]: l["rel"] for l in labels}
    by_key = {_nk(l): l["rel"] for l in labels}
    rel_by_id = {i: by_uuid[i] for i in run_ids if i in by_uuid}
    missing = [i for i in run_ids if i not in rel_by_id]
    if missing:
        keys = hydrate_natural_keys(missing, query_fn)
        for i in missing:
            row = keys.get(i)
            if row and _nk(row) in by_key:
                rel_by_id[i] = by_key[_nk(row)]
    return rel_by_id, [i for i in run_ids if i not in rel_by_id]


def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    check("unit_id uses slug", unit_id("p01", {"slug": "olin-guha"}) == "p01::olin-guha")
    check("unit_id falls back to code", unit_id("c01", {"code": "CS3500"}) == "c01::CS3500")
    check("entity_args pair", entity_args({"slug": "s"}) == ("s", None)
          and entity_args({"code": "CS3500"}) == (None, "CS3500"))

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.json")
        check("load_json missing -> default", load_json(p, {"d": 1}) == {"d": 1})
        save_json_atomic(p, {"a": 2})
        check("atomic save round-trips", load_json(p, None) == {"a": 2})
        check("no tmp file left behind", not os.path.exists(p + ".tmp"))

    labels = [
        {"evidence_id": "id-1", "source": "rmp", "source_ref": "t1",
         "professor_slug": "guha", "course_code": "", "body_sha": "s1", "rel": 2},
        {"evidence_id": "id-old", "source": "rmp", "source_ref": "r1",
         "professor_slug": "guha", "course_code": "", "body_sha": "s2", "rel": 1},
    ]
    def fake_query(sql, params):
        check("natural-key hydrate only for uuid misses", params == (("id-new", "id-x"),))
        return [{"id": "id-new", "source": "rmp", "source_ref": "r1",
                 "professor_slug": "guha", "course_code": "", "body_sha": "s2"}]
    rel, unlabeled = rel_lookup(labels, ["id-1", "id-new", "id-x"], fake_query)
    check("uuid match", rel.get("id-1") == 2)
    check("natural-key fallback recovers a reloaded row", rel.get("id-new") == 1)
    check("unknown id reported unlabeled", unlabeled == ["id-x"])

    def rejects(run_dir_arg, label, runs_dir):
        try:
            ensure_run_dir(run_dir_arg, label, runs_dir)
            return False
        except SystemExit:
            return True

    with tempfile.TemporaryDirectory() as scratch:
        fake_runs_dir = os.path.join(scratch, "runs")
        os.makedirs(fake_runs_dir, exist_ok=True)

        good = ensure_run_dir(None, "baseline", fake_runs_dir)
        check("ensure_run_dir: valid label creates a dir directly under runs_dir",
              os.path.isdir(good) and os.path.dirname(os.path.realpath(good)) == os.path.realpath(fake_runs_dir))
        check("ensure_run_dir: '..' escape rejected",
              rejects(os.path.join(fake_runs_dir, "..", "evil"), "x", fake_runs_dir))
        check("ensure_run_dir: absolute path outside runs_dir rejected",
              rejects(os.path.join(scratch, "elsewhere"), "x", fake_runs_dir))
        check("ensure_run_dir: nested a/b label rejected",
              rejects(None, "a/b", fake_runs_dir))

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    if p.parse_args().selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")
