"""Measures whether moderation_groq.check can publish rating comments on its own.

Runs a local test set (written `live`, `hold` and `either` comments) plus a frozen
random sample of real approved comments through moderation_groq.check exactly as
prod calls it, and writes a markdown report. The bar: at least 90% of the real
sample gets ALLOW, and no clearly-bad `hold` comment gets ALLOW in any run.

Keys: calls go on the groq2..groqN keys from backend/.env in turn, never on groq1,
which prod's comment check uses. Each key must belong to its own Groq org (account),
not groq1's, or a run spends prod's daily tokens anyway. Quota: Groq's free plan gives this model 3 requests and 2,000
tokens a minute, 200,000 tokens a day per org, so calls go about 2 a minute and the
run stops before 170,000 tokens in 24 hours. A stopped run resumes the next day without
redoing finished calls: results are saved after every call.

It writes nothing to prod: a read-only session draws the real sample once, and no
call is logged to moderation_calls. The set, results and reports live only in
backend/reports/, which git ignores, since the `hold` examples include threats and
slurs.

    python moderation_eval.py plan|run|report [--variant baseline] [--half all|tune|held|fresh|...]
        [--policy-file F] [--model M] [--effort E] [--token-cap N]
"""

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from collections import Counter
from itertools import cycle
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import moderation_groq
from rating_checks import rule_block

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
SET_PATH = REPORTS_DIR / "moderation_eval_set.json"
RESULTS_PATH = REPORTS_DIR / "moderation_eval_results.json"
TOKEN_CAP = 170_000
CALL_CEILING = 1_000  # what a call without usage counts toward the cap
SPACING_SECONDS = 30
RETRY_WAIT_SECONDS = 60
MAX_FAILURES = 3
MAX_429S = 10
MAX_UNAVAILABLE = 3  # comments in a row: a bad key, --model or --effort, not an outage
REAL_SAMPLE = 60
SAMPLE_SEED = "groq-eval-1"
BAR = 0.90

LABELS = ("live", "hold", "either")
DECIDED = ("allow", "review", "block")
ESTIMATE_TOKENS = 700

REAL_SAMPLE_SQL = """SELECT id::text AS id, comment FROM survey_ratings
WHERE comment_status = 'approved' AND comment IS NOT NULL AND btrim(comment) <> ''
ORDER BY md5(id::text || %s) LIMIT %s"""


def load_set(path):
    """The written items in `path`, checked: a bad item raises ValueError naming its id."""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for it in items:
        id = it.get("id")
        if not id or id in seen:
            raise ValueError(f"missing or duplicate id: {id!r}")
        seen.add(id)
        if it.get("label") not in LABELS:
            raise ValueError(f"{id}: label must be one of {LABELS}")
        if not it.get("category"):
            raise ValueError(f"{id}: no category")
        if it.get("severity") not in ("clear", "subtle", None):
            raise ValueError(f"{id}: severity must be clear, subtle or null")
        if it["label"] == "hold" and it.get("severity") is None:
            raise ValueError(f"{id}: a hold item needs a severity")
        if not it.get("half") or it["half"] == "all":
            raise ValueError(f"{id}: half must be a name such as tune or held, not empty or all")
        if not str(it.get("text") or "").strip():
            raise ValueError(f"{id}: empty text")
    return items


def real_sample(cur, n=REAL_SAMPLE, seed=SAMPLE_SEED):
    """`n` approved comments in a fixed random order, minus any the free rules catch
    (prod never sends those to the model)."""
    cur.execute(REAL_SAMPLE_SQL, (seed, n * 2))
    picked = [(id, comment) for id, comment in cur.fetchall() if rule_block(comment) is None][:n]
    return [{"id": "real-" + id[:8], "label": "live", "category": "real", "severity": None,
             "half": None, "text": comment} for id, comment in picked]


def setup_of(policy, model, effort):
    return {"model": model, "effort": effort,
            "policy_sha": hashlib.sha256(policy.encode("utf-8")).hexdigest()[:12]}


def apply_setup(policy, model, effort):
    moderation_groq.POLICY, moderation_groq.MODEL, moderation_groq.EFFORT = policy, model, effort


def in_half(item, half):
    return half == "all" or item["half"] is None or item["half"] == half


def groq_keys():
    """The groq2, groq3, ... keys from the environment, stopping at the first gap.
    Never groq1: prod's comment check runs on it, on this same model."""
    keys = []
    while os.getenv(f"groq{len(keys) + 2}", "").strip():
        keys.append(os.environ[f"groq{len(keys) + 2}"].strip())
    return keys


def rotating(*clients):
    """A client that sends each call on the next of `clients` in turn."""
    turn = cycle(clients)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: next(turn).chat.completions.create(**kw))))


def _client(key):
    """Built like moderation_groq.client(): 3 s and no retries."""
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=moderation_groq.BASE_URL,
                  timeout=moderation_groq.TIMEOUT, max_retries=0)


def _latest(records, variant):
    """{(id, run): action} from the variant's records, the latest record winning."""
    return {(r["id"], r["run"]): r["action"] for r in records if r["variant"] == variant}


def pending_calls(items, records, variant):
    """[(item, run)] still to do: all run-1 calls in set order, then run-2 calls."""
    done = _latest(records, variant)
    first, second = [], []
    for it in items:
        one = done.get((it["id"], 1))
        if one in (None, "unavailable"):
            first.append((it, 1))
            continue
        if one == "rules" or done.get((it["id"], 2), "unavailable") != "unavailable":
            continue
        if it["label"] == "hold" or (it["label"] == "live" and one in ("review", "block")):
            second.append((it, 2))
    return first + second


def tokens_last_day(records, model, now):
    since = now - timedelta(hours=24)
    return sum(CALL_CEILING if r["tokens"] is None else r["tokens"] for r in records
               if r["model"] == model and datetime.fromisoformat(r["at"]) > since)


def run(items, records, groq, variant, setup, save, token_cap=TOKEN_CAP, now=None, sleep=time.sleep):
    """Make the variant's pending calls, appending a record and calling save(records)
    after each. Returns a one-line summary of what it did and why it stopped."""
    if any({k: r[k] for k in setup} != setup for r in records if r["variant"] == variant):
        raise ValueError(f"variant {variant!r} was run with another policy, model or effort; "
                         "pick a new --variant name")
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))

    def add(it, n, action, tokens):
        records.append({"variant": variant, **setup, "id": it["id"], "run": n, "action": action,
                        "tokens": tokens, "at": clock().isoformat()})
        save(records)

    made, tried, stopped, dead = 0, set(), "nothing left", 0
    for it, n in pending_calls(items, records, variant):
        if n == 1 and rule_block(it["text"]):
            add(it, 1, "rules", 0)
    for phase in (1, 2):
        for it, n in pending_calls(items, records, variant):
            if n != phase or (it["id"], n) in tried:
                continue
            if tokens_last_day(records, setup["model"], clock()) + CALL_CEILING > token_cap:
                stopped = f"stopped at the token cap ({token_cap:,}); rerun tomorrow to resume"
                break
            tried.add((it["id"], n))
            if made:
                sleep(SPACING_SECONDS)
            failures = limited = 0
            while True:
                action, reason, tokens = moderation_groq.check(it["text"], groq)
                if reason == "groq_rate_limited":
                    limited += 1
                    if limited >= MAX_429S:
                        break
                elif reason == "groq_unavailable":
                    failures += 1
                    if failures >= MAX_FAILURES:
                        break
                else:
                    break
                sleep(RETRY_WAIT_SECONDS)
            made += 1
            if limited >= MAX_429S:
                stopped = f"stopped after {MAX_429S} 429s in a row"
                break
            add(it, n, action, tokens)
            dead = dead + 1 if action == "unavailable" else 0
            if dead >= MAX_UNAVAILABLE:
                stopped = (f"stopped after {MAX_UNAVAILABLE} comments in a row failed every attempt; "
                           "check the keys, --model and --effort")
                break
        else:
            continue
        break
    used = tokens_last_day(records, setup["model"], clock())
    return f"{made} calls made, {used:,} tokens used in the last 24 h, {stopped}"


def _pct(part, whole):
    return f"{part / whole:.0%} ({part}/{whole})" if whole else "n/a (0)"


def report(items, records, variant, half):
    """Markdown starting with PASS, FAIL or INCOMPLETE, then the numbers and every mistake."""
    items = [it for it in items if in_half(it, half)]
    done = _latest(records, variant)
    one = {it["id"]: done.get((it["id"], 1)) for it in items}
    two = {it["id"]: done.get((it["id"], 2)) for it in items}
    by = {k: [it for it in items if it["label"] == k] for k in LABELS}
    real = [it for it in by["live"] if it["category"] == "real"]
    written = [it for it in by["live"] if it["category"] != "real"]

    real_decided = [it for it in real if one[it["id"]] in DECIDED]
    real_allowed = sum(one[it["id"]] == "allow" for it in real_decided)
    share = real_allowed / len(real_decided) if real_decided else 0.0
    held_allowed = [it for it in by["hold"] if "allow" in (one[it["id"]], two[it["id"]])]
    clear_allowed = [it for it in held_allowed if it["severity"] == "clear"]

    if pending_calls(items, records, variant):
        verdict = "INCOMPLETE: calls are still pending; resume the run"
    elif share >= BAR and not clear_allowed:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    def allow_share(group):
        decided = [it for it in group if one[it["id"]] in DECIDED]
        return _pct(sum(one[it["id"]] == "allow" for it in decided), len(decided))

    lines = [f"{verdict}", "", f"Variant `{variant}`, half `{half}`, bar {BAR:.0%} real ALLOW and no clear hold allowed.", ""]
    lines += ["## Real live comments (run 1)", "",
              f"- ALLOW: {_pct(real_allowed, len(real_decided))}",
              f"- Unavailable: {sum(one[it['id']] == 'unavailable' for it in real)}", ""]
    lines += ["## Written live comments (run 1, no bar)", "", f"- Overall ALLOW: {allow_share(written)}"]
    for cat in sorted({it["category"] for it in written}):
        lines.append(f"- {cat}: {allow_share([it for it in written if it['category'] == cat])}")
    lines += ["", "## Hold comments allowed in any run", ""]
    for sev in ("clear", "subtle"):
        group = [it for it in by["hold"] if it["severity"] == sev]
        lines.append(f"- {sev}: {sum(it in held_allowed for it in group)} of {len(group)}")
    lines.append(f"- Caught by the free rules: {sum(one[it['id']] == 'rules' for it in by['hold'])}")
    lines += ["", "## Either comments (run 1)", ""]
    counts = Counter(one[it["id"]] for it in by["either"])
    lines.append("- " + (", ".join(f"{a}: {c}" for a, c in sorted(counts.items(), key=lambda x: str(x[0]))) or "none"))
    run_one = [a for a in one.values() if a in DECIDED]
    calls = [r for r in records if r["variant"] == variant and r["action"] != "rules"]
    lines += ["", "## Usage", "",
              f"- REVIEW rate over run-1 answers: {_pct(run_one.count('review'), len(run_one))}",
              f"- Calls: {len(calls)}",
              f"- Tokens: {sum(r['tokens'] or 0 for r in calls):,}"
              f" ({sum(r['tokens'] is None for r in calls)} calls without usage)", ""]
    mistakes = [it for it in by["live"] if one[it["id"]] in ("review", "block")] + held_allowed
    lines += [f"## Mistakes ({len(mistakes)})", ""]
    for it in mistakes:
        lines += [f"### {it['id']} ({it['label']}, {it['category']}, {it['severity'] or 'no severity'})", "",
                  f"Answers: {one[it['id']] or '-'} / {two[it['id']] or '-'}", "", "> " + it["text"].replace("\n", "\n> "), ""]
    return "\n".join(lines)


def load_results():
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {"records": []}


def save_results(results):
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(RESULTS_PATH) + ".tmp")
    tmp.write_text(json.dumps(results, indent=1), encoding="utf-8")
    os.replace(tmp, RESULTS_PATH)


def _connect():
    """A read-only cursor on the database in DATABASE_URL."""
    from pipeline.db import connect
    conn = connect()
    conn.set_session(readonly=True)
    return conn.cursor()


@contextlib.contextmanager
def results_lock():
    """Refuses a second run while one is writing the results file, since each
    would overwrite the other's records."""
    lock = Path(str(RESULTS_PATH) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise RuntimeError(f"a run is already running ({lock}); delete the file if none is") from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def load_items(connect=True):
    """(written set + real sample, results). Draws and freezes the real sample on the
    first call that may connect; afterwards the results file's copy is used."""
    results = load_results()
    if "real_sample" not in results and connect:
        results["real_sample"] = real_sample(_connect())
        save_results(results)
    return load_set(SET_PATH) + results.get("real_sample", []), results


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
    p = argparse.ArgumentParser(description="Evaluate Groq comment checks on the local test set.")
    p.add_argument("command", choices=("plan", "run", "report"))
    p.add_argument("--variant", default="baseline")
    p.add_argument("--half", default="all", help="all, or a half named in the set (tune, held, fresh, ...)")
    p.add_argument("--policy-file")
    p.add_argument("--model", default=moderation_groq.MODEL)
    p.add_argument("--effort", default=moderation_groq.EFFORT)
    p.add_argument("--token-cap", type=int, default=TOKEN_CAP)
    args = p.parse_args(argv)
    with results_lock() if args.command == "run" else contextlib.nullcontext():
        return _command(args)


def _command(args):
    items, results = load_items(connect=args.command != "report")
    items = [it for it in items if in_half(it, args.half)]
    records = results["records"]

    if args.command == "plan":
        for key in ("label", "category", "severity", "half"):
            print(f"{key}: " + ", ".join(f"{k}={c}" for k, c in sorted(Counter(str(it[key]) for it in items).items())))
        caught = [it["id"] for it in items if rule_block(it["text"])]
        print("free rules catch: " + (", ".join(caught) or "none"))
        pending = [(it, n) for it, n in pending_calls(items, records, args.variant) if it["id"] not in caught]
        reruns = sum(1 for it, n in pending if n == 1 and it["label"] == "hold")
        left = len(pending) + reruns
        print(f"calls left: at least {left}, about {left * ESTIMATE_TOKENS:,} tokens at {ESTIMATE_TOKENS} a call")
        return 0

    if args.command == "run":
        policy = Path(args.policy_file).read_text(encoding="utf-8") if args.policy_file else moderation_groq.POLICY
        apply_setup(policy, args.model, args.effort)
        keys = groq_keys()
        if not keys:
            print("No groq2..groqN keys in backend/.env (groq1 is prod's).", file=sys.stderr)
            return 1

        def save(recs):
            results["records"] = recs
            save_results(results)
        print(run(items, records, rotating(*map(_client, keys)), args.variant,
                  setup_of(policy, args.model, args.effort), save, token_cap=args.token_cap))
        return 0

    text = report(items, records, args.variant, args.half)
    out = REPORTS_DIR / f"moderation_eval_{args.variant}_{args.half}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text.splitlines()[0])
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
