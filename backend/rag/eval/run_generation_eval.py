"""Runs the FULL Ask pipeline (real gate + retrieval + Groq synthesis) over the eval questions
and saves answers for hand-grading. Throttle/abuse/cache are neutralized; nothing is written
to ask_log. answers.json contains evidence bodies -> gitignored, never committed.

Run: python backend/rag/eval/run_generation_eval.py --run --label baseline [--run-dir backend/rag/eval/runs/<dir>]"""
import sys, os, re, time, types, argparse, datetime

from eval_common import (connect, make_query_fns, make_prof_search, load_json,
                         save_json_atomic, git_sha, ensure_run_dir, QUESTIONS_PATH)

_CITATION_RE = re.compile(r"\[(\d+)\]")
DATAMARK = "▁"


def deterministic_checks(record, num_sources):
    answer = record.get("answer") or ""
    expected = record.get("expected_status", "ok")
    cited_nums = [int(n) for n in _CITATION_RE.findall(answer)] + list(record.get("cited") or [])
    return {
        "status_ok": record.get("status") == expected,
        "answer_nonempty": bool(answer.strip()) if expected == "ok" else True,
        "citations_in_range": all(1 <= n <= num_sources for n in cited_nums),
        "no_datamark": DATAMARK not in answer,
    }


def build_deps(query_fn, query_one_fn, prof_search, adapter, num_keys, log_calls, last_gen):
    from rag.chat_gate import gate
    from rag.chat_retrieve import retrieve
    from rag.chat_answer import generate, generate_course_list, generate_course_ranking
    from rag.query_embedder import embed_query

    def generate_fn(qq, blocks):
        out = generate(qq, blocks, adapter)
        last_gen["gen"] = out
        return out

    return types.SimpleNamespace(
        chat_enabled=True,
        num_keys=num_keys,
        query_fn=query_fn,
        query_one_fn=query_one_fn,
        prof_search_fn=prof_search,
        cache_get_fn=lambda k: None,          # never serve cached answers in an eval
        cache_set_fn=lambda k, v: None,       # never poison the (in-memory) cache either
        keyword_search_fn=lambda qq: {"comments": [], "professors": []},
        gate_fn=lambda qq: gate(qq, adapter),
        retrieve_fn=lambda qq, hint: retrieve(qq, hint, query_fn, query_one_fn,
                                              prof_search, embed_query_fn=embed_query),
        generate_fn=generate_fn,
        generate_course_list_fn=lambda t, c: generate_course_list(t, c, adapter),
        generate_course_ranking_fn=lambda s, m, d, c: generate_course_ranking(s, m, d, c, adapter),
        log_fn=lambda sql, params: log_calls.append(params),  # capture, never write ask_log
    )


def neutralize_throttle():
    """handle_question imported these names into its own namespace; patch THERE. Keeps the
    eval exempt from daily/minute budgets, the abuse ladder, and the answer cache — an eval
    run must never rate-limit itself or count against production budgets."""
    from rag import chat_question
    chat_question.abuse_check = lambda session, q1: {"allowed": True, "message": None}
    chat_question.global_budget_hit = lambda *a, **k: False
    chat_question.session_allowed = lambda *a, **k: (True, None)
    chat_question.minute_capacity_ok = lambda *a, **k: True
    chat_question.today_ok_count = lambda q1: 0
    chat_question.release_reservation = lambda *a, **k: None
    chat_question.get_cached = lambda *a, **k: None
    chat_question.set_cached = lambda *a, **k: None
    return chat_question


def run(questions, label, run_dir_arg):
    from rag.llm_adapter import GroqAdapter
    from rag.key_pool import KeyPool
    # Resolve + create the run dir BEFORE the (paid, ~30-call) Groq loop, not after: a
    # typo'd/relative --run-dir or a mid-loop exception must not throw away a full run.
    run_dir = ensure_run_dir(run_dir_arg, label)
    conn = connect()  # also load_dotenv's backend/.env, so groq keys are in os.environ
    query_fn, query_one_fn = make_query_fns(conn)
    prof_search = make_prof_search(query_fn)
    pool = KeyPool()
    if not pool.entries:
        sys.exit("No Groq keys found (groq1.. / GROQ_API_KEY in backend/.env)")
    adapter = GroqAdapter(pool)
    chat_question = neutralize_throttle()

    log_calls, last_gen = [], {}
    deps = build_deps(query_fn, query_one_fn, prof_search, adapter,
                      len(pool.entries) or 1, log_calls, last_gen)
    answers = []
    try:
        for q in questions:
            last_gen.clear()
            t0 = time.monotonic()
            payload, http = chat_question.handle_question(q["question"], "eval-runner", "eval-ip", deps)
            latency_ms = int((time.monotonic() - t0) * 1000)
            status = log_calls[-1][3] if log_calls else "no_log"   # params[3] = result_status
            tokens = log_calls[-1][6] if log_calls else 0          # params[6] = tokens_used
            gen = last_gen.get("gen") or {}
            num_sources = gen.get("num_sources", 0)
            sources = []
            for i, c in enumerate(gen.get("sources_comments", [])[:num_sources]):
                tag = (gen.get("source_entities") or [{}] * num_sources)[i]
                sources.append({"n": i + 1, "evidence_id": str(c.get("source_id")),
                                "source": c.get("source"), "body": c.get("body", ""),
                                "professor_slug": tag.get("professor_slug"),
                                "course_code": tag.get("course_code")})
            record = {"question_id": q["id"], "question": q["question"], "mode": q["mode"],
                      "expected_status": q.get("expected_status", "ok"),
                      "status": status, "http": http, "payload_mode": payload.get("mode"),
                      "answer": payload.get("answer", ""), "cited": payload.get("cited", []),
                      "latency_ms": latency_ms, "tokens_used": tokens, "sources": sources}
            record["checks"] = deterministic_checks(record, num_sources)
            record["checks_passed"] = all(record["checks"].values())
            answers.append(record)
            flag = "" if record["checks_passed"] else "  <-- CHECK FAILED"
            print(f"  {q['id']}: {status} {latency_ms}ms{flag}")
            time.sleep(1)  # be gentle to the Groq free tier
    finally:
        # Always write whatever answers were collected, even if handle_question raised
        # mid-loop (e.g. the DB connection drops) -- otherwise a failure
        # at question N discards N completed, paid Groq answers with nothing on disk.
        save_json_atomic(os.path.join(run_dir, "answers.json"),
                         {"created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                          "git_sha": git_sha(),
                          "models": {"classify": GroqAdapter.CLASSIFY_MODEL,
                                     "synth": GroqAdapter.SYNTH_MODEL},
                          "answers": answers})
        failed = [a["question_id"] for a in answers if not a["checks_passed"]]
        print(f"\nwrote {run_dir}/answers.json — {len(answers)} answers, "
              f"{len(failed)} failing checks{': ' + ', '.join(failed) if failed else ''}")

    print("grade them: python backend/rag/eval/eval_ui.py -> Grade tab")
    return 1 if failed else 0


def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    good = {"status": "ok", "expected_status": "ok", "answer": "Fair grader [1] [2].", "cited": [1, 2]}
    c = deterministic_checks(good, num_sources=4)
    check("all checks pass on a clean answer", all(c.values()))
    c2 = deterministic_checks({**good, "answer": "Out of range [9]."}, num_sources=4)
    check("citation beyond num_sources caught", c2["citations_in_range"] is False)
    c3 = deterministic_checks({**good, "status": "thin_data"}, num_sources=0)
    check("unexpected status caught", c3["status_ok"] is False)
    c4 = deterministic_checks({**good, "expected_status": "thin_data", "status": "thin_data", "answer": "", "cited": []}, 0)
    check("expected refusal passes with empty answer", c4["status_ok"] and c4["answer_nonempty"])
    c5 = deterministic_checks({**good, "answer": "leaky ▁marker [1]"}, 4)
    check("datamark leak caught", c5["no_datamark"] is False)
    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0


def main():
    p = argparse.ArgumentParser(description="Full-pipeline Ask generation eval runner.")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--label", default="run")
    p.add_argument("--run-dir")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.run:
        questions = load_json(QUESTIONS_PATH, None)
        if questions is None:
            sys.exit(f"missing {QUESTIONS_PATH}")
        sys.exit(run(questions, args.label, args.run_dir))
    print("use --run --label <name>, or --selftest")


if __name__ == "__main__":
    main()
