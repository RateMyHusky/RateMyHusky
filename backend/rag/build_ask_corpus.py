"""
One-off ops script: rebuild the Ask corpus and embed it, from this machine.

WHY: Ask retrieval searches `evidence` (RMP reviews + Reddit comments) with full-text
search and pgvector. The weekly data refresh keeps both current once this branch is
merged, but testing the chat system against the real database before that needs one
run by hand. This does the same two steps the workflow does, in the same order:

  1. scraper/load_evidence.py --build-evidence --prune   rebuild `evidence` from the
     source tables; the prune refuses to delete more than 5% of a source's rows
  2. scraper/embed_evidence.py --embed                    embed new or changed rows into
     `evidence_embeddings` (BGE-small, local ONNX; the first run embeds all ~50k rows)

Both scripts are idempotent, so re-running only redoes what changed. This WRITES to
whatever database ORACLE_DATABASE_URL in backend/.env names, so it shows the host and
asks before writing. Never prints the connection string.

Needs the embedding packages, pinned to the versions the weekly job uses:
  pip install "onnxruntime>=1.31,<1.32" "tokenizers>=0.23,<0.24" "huggingface_hub>=2.4,<2.5"
The first embed downloads the model (tens of MB) into the Hugging Face cache.

USAGE (from backend/):
  python rag/build_ask_corpus.py --status        # read-only: corpus and embedding counts
  python rag/build_ask_corpus.py                 # rebuild + embed (asks first)
  python rag/build_ask_corpus.py --embed-only    # skip the rebuild, just embed
  python rag/build_ask_corpus.py --threads 6     # embed with more CPU threads (default 3)
  python rag/build_ask_corpus.py --yes           # don't ask (for scripted runs)
"""
import os, sys, time, argparse, subprocess, importlib.util
from urllib.parse import urlsplit

RAG_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_DIR = os.path.normpath(os.path.join(RAG_DIR, "..", "..", "scraper"))


def _scraper_module(name):
    """Load scraper/<name>.py by path: scraper/ isn't a package, and a sys.path insert
    leaves editors unable to resolve the import."""
    if name in sys.modules:
        return sys.modules[name]
    path = os.path.join(SCRAPER_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        sys.exit(f"Can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load_evidence = _scraper_module("load_evidence")  # loads backend/.env
connect, URL = _load_evidence.connect, _load_evidence.URL
MODEL_VERSION = _scraper_module("embed_evidence").MODEL_VERSION

if not URL:
    sys.exit("Need ORACLE_DATABASE_URL in backend/.env")

EMBED_PACKAGES = ("onnxruntime", "tokenizers", "huggingface_hub")
# Same floor as the weekly workflow's post-write check.
MIN_COVERAGE = 0.95


def target():
    """host:port/dbname, without the user or password."""
    u = urlsplit(URL)
    return f"{u.hostname}:{u.port or 5432}{u.path or ''}"


def status(conn):
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT source, count(*) FROM evidence GROUP BY source ORDER BY source")
        by_source = cur.fetchall()
        cur.execute(
            "SELECT count(*), "
            "count(ee.evidence_id) FILTER (WHERE ee.model_version = %s "
            "AND ee.body_sha IS NOT DISTINCT FROM e.body_sha) "
            "FROM evidence e LEFT JOIN evidence_embeddings ee ON ee.evidence_id = e.id",
            (MODEL_VERSION,))
        total, current = cur.fetchone()
    conn.rollback()
    return by_source, total, current


def print_status(label, conn):
    by_source, total, current = status(conn)
    sources = ", ".join(f"{s} {n:,}" for s, n in by_source) or "none"
    share = current / total if total else 0.0
    print(f"{label}: evidence {total:,} rows ({sources}); "
          f"embedded with {MODEL_VERSION}: {current:,} ({share:.1%}); "
          f"to embed: {total - current:,}")
    return total, current


def missing_packages():
    missing = []
    for name in EMBED_PACKAGES:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    return missing


def run_step(label, script, args, env):
    print(f"\n== {label}: python {script} {' '.join(args)}", flush=True)
    started = time.time()
    code = subprocess.call([sys.executable, script, *args], cwd=SCRAPER_DIR, env=env)
    if code != 0:
        sys.exit(f"{label} failed (exit {code}). Nothing after it ran; fix the error and re-run "
                 "this script: both steps are idempotent.")
    print(f"== {label} finished in {(time.time() - started) / 60:.1f} min", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Rebuild and embed the Ask corpus from this machine")
    parser.add_argument("--status", action="store_true", help="Print counts and exit (read-only)")
    parser.add_argument("--embed-only", action="store_true", help="Skip the evidence rebuild")
    parser.add_argument("--threads", type=int, default=None,
                        help="CPU threads for embedding (EMBED_THREADS, default 3)")
    parser.add_argument("--yes", action="store_true", help="Don't ask before writing")
    args = parser.parse_args()

    print(f"Database: {target()}")
    conn = connect()
    try:
        print_status("Now", conn)
    finally:
        conn.close()
    if args.status:
        return

    missing = missing_packages()
    if missing:
        sys.exit(f"Missing embedding packages: {', '.join(missing)}. Install them with:\n"
                 '  pip install "onnxruntime>=1.31,<1.32" "tokenizers>=0.23,<0.24" '
                 '"huggingface_hub>=2.4,<2.5"')

    steps = "embed" if args.embed_only else "rebuild + prune `evidence`, then embed"
    if not args.yes:
        answer = input(f"\nThis will {steps} on {target()}. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            sys.exit("Stopped; nothing was written.")

    env = dict(os.environ)
    if args.threads:
        env["EMBED_THREADS"] = str(args.threads)
    if not args.embed_only:
        run_step("Rebuild corpus", "load_evidence.py", ["--build-evidence", "--prune"], env)
    run_step("Embed corpus", "embed_evidence.py", ["--embed"], env)

    print()
    conn = connect()
    try:
        total, current = print_status("After", conn)
    finally:
        conn.close()
    if total and current / total < MIN_COVERAGE:
        sys.exit(f"Embedding coverage is below {MIN_COVERAGE:.0%}; re-run to finish the remaining rows.")
    print("Ask corpus is ready.")


if __name__ == "__main__":
    main()
