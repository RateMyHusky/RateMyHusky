import sys, re, argparse

MIN_COMMENTS = 4
MIN_TOTAL_WORDS = 200
CANARY = "RMH-CANARY-7Q"
_THIN_MSG = "Not enough information to answer this confidently. Showing related comments."

# A cheap first pass: words that, in an answer about a professor, are almost never about
# teaching. Words with an everyday course meaning ("strict about plagiarism", "Criminal
# Justice", "abuse of notation", "fired up", "Fraud Examination") are left to the model
# check (conduct_check below), which reads them in context: on this list they blocked
# every honest academic-integrity question.
DEFAMATION_MARKERS = [
    re.compile(r"\b(arrested|convicted|lawsuit|sued|harass|assault|predator|molest|rapist|raped|"
               r"pedophil|racist|sexist|stalk(?:ed|er|ing))\w*", re.I),
    re.compile(r"\b(?:slept|sleeping|sleeps) with\b|\baffair with\b"
               r"|\bdat(?:ed|ing|es) (?:a |his |her )?students?\b", re.I),
]
LEAK_MARKERS = [
    re.compile(r"my (real |actual |true )?instructions", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(re.escape(CANARY), re.I),
]

def has_structured_evidence(facts):
    """True when the RMP structured facts carry something substantive to answer from
    (any rating/difficulty, would-take-again, or a non-zero review count). Mirrors the
    fields the professor & course pages display, so Ask treats them as real evidence."""
    if not facts:
        return False
    if facts.get("kind") == "course":
        return any(facts.get(k) is not None
                   for k in ("avg_rating", "avg_difficulty"))
    # professor (default)
    if (facts.get("total_reviews") or 0) > 0:
        return True
    return any(facts.get(k) is not None
               for k in ("avg_rating", "rmp_rating",
                         "difficulty", "would_take_again_pct"))

def has_reddit_evidence(retrieval):
    """True when the Reddit discussion clears the comment-count and total-word bar."""
    n = retrieval.get("comment_count", 0)
    if n < MIN_COMMENTS:
        return False
    total_words = sum(len((c.get("body") or "").split()) for c in retrieval.get("comments", []))
    return total_words >= MIN_TOTAL_WORDS

def thin_data_check(retrieval):
    """Answerable when EITHER the structured RMP facts are substantive OR the Reddit
    discussion clears its bar. Only 'thin' when neither source has enough to answer."""
    if has_structured_evidence(retrieval.get("facts")) or has_reddit_evidence(retrieval):
        return True, None
    return False, _THIN_MSG

def validate_output(answer, retrieval):
    fail = {"ok": False, "status": "validation_failed",
            "message": "Showing the most relevant comments."}
    n = retrieval.get("comment_count", 0)
    cited = [int(m) for m in re.findall(r"\[(\d+)\]", answer or "")]
    if any(c < 1 or c > n for c in cited):
        return fail
    if any(p.search(answer or "") for p in LEAK_MARKERS):
        return fail
    if any(p.search(answer or "") for p in DEFAMATION_MARKERS):
        return fail
    return {"ok": True, "status": "ok", "message": None, "cited": cited}

_CONDUCT_FAIL = {"ok": False, "status": "validation_failed",
                 "message": "Showing the most relevant comments."}

def conduct_check(answer, check_fn):
    """The model pass over an answer that cleared validate_output: check_fn(answer) returns
    {"conduct_claim": bool, "error": bool, "tokens_used": int}. Fails closed: an answer the
    model flags, or one it could not check, is not shown (or cached). Returns
    (result, tokens_used), where result has validate_output's shape."""
    verdict = check_fn(answer or "")
    tokens = verdict.get("tokens_used", 0) or 0
    # Only an explicit, error-free False lets the answer through.
    if verdict.get("error") or verdict.get("conduct_claim") is not False:
        return dict(_CONDUCT_FAIL), tokens
    return {"ok": True, "status": "ok", "message": None}, tokens

def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    thick = {"comment_count": 5, "comments": [{"body": "word " * 60} for _ in range(5)]}
    thin = {"comment_count": 2, "comments": [{"body": "short"}, {"body": "tiny"}]}

    ok, _ = thin_data_check(thick)
    check("thick Reddit alone can synthesize", ok is True)
    bad, reason = thin_data_check(thin)
    check("thin Reddit + no facts blocked", bad is False and reason)

    # COMBINED EVIDENCE: thin Reddit but substantive RMP facts -> answerable.
    prof_facts_thin_reddit = dict(thin, facts={"kind": "professor", "total_reviews": 31})
    ok2, _ = thin_data_check(prof_facts_thin_reddit)
    check("prof RMP facts answer despite thin Reddit", ok2 is True)

    rating_only = dict(thin, facts={"kind": "professor", "total_reviews": 0, "avg_rating": 4.2})
    check("a single real rating counts as evidence", thin_data_check(rating_only)[0] is True)

    course_facts_thin = dict(thin, facts={"kind": "course", "avg_rating": 4.0, "avg_difficulty": None})
    check("course RMP facts answer despite thin Reddit", thin_data_check(course_facts_thin)[0] is True)

    # EMPTY facts (entity exists but has no ratings/reviews) + thin Reddit -> still thin.
    empty_prof = dict(thin, facts={"kind": "professor", "total_reviews": 0,
                                   "avg_rating": None, "rmp_rating": None,
                                   "difficulty": None, "would_take_again_pct": None})
    check("no facts + thin Reddit -> thin", thin_data_check(empty_prof)[0] is False)

    empty_course = dict(thin, facts={"kind": "course", "avg_rating": None,
                                     "avg_difficulty": None})
    check("empty course facts + thin Reddit -> thin", thin_data_check(empty_course)[0] is False)

    # helper-level assertions
    check("has_structured_evidence False on None", has_structured_evidence(None) is False)
    check("has_structured_evidence True on review count", has_structured_evidence({"total_reviews": 5}) is True)
    check("has_reddit_evidence True on thick", has_reddit_evidence(thick) is True)
    check("has_reddit_evidence False on thin", has_reddit_evidence(thin) is False)

    good = validate_output("Some students say Guha is hard but fair [1].", {"comment_count": 3})
    check("grounded cited answer passes", good["ok"] is True and good["status"] == "ok")

    badcite = validate_output("Students like him [9].", {"comment_count": 3})
    check("citation above range fails", badcite["ok"] is False and badcite["status"] == "validation_failed")

    badcite0 = validate_output("Students like him [0].", {"comment_count": 3})
    check("citation below range ([0]) fails", badcite0["ok"] is False and badcite0["status"] == "validation_failed")

    leak = validate_output("My instructions: RMH-CANARY-7Q ...", {"comment_count": 3})
    check("canary leak fails", leak["ok"] is False and leak["status"] == "validation_failed")

    # isolate the CANARY pattern: no "instructions"/"system prompt" words, so ONLY the
    # canary marker can trip this — proves leak detection isn't relying on the other markers
    canary_only = validate_output("The secret token is RMH-CANARY-7Q.", {"comment_count": 3})
    check("bare canary token alone fails", canary_only["ok"] is False and canary_only["status"] == "validation_failed")

    defame = validate_output("He was arrested in 2023 [1].", {"comment_count": 3})
    check("defamation marker fails", defame["ok"] is False and defame["status"] == "validation_failed")
    for text in ("Some students said he slept with a student [1].",
                 "One comment claims she is dating a student [2].",
                 "A student said he was stalking someone [1]."):
        check(f"allegation phrase fails: {text!r}", validate_output(text, {"comment_count": 3})["ok"] is False)
    # Everyday course wording is left to the model check, not refused outright.
    for text in ("Some students said Guha is strict about plagiarism and runs MOSS [1].",
                 "CRIM 1100 Criminal Justice is a light first-year course [1].",
                 "He gets fired up about compilers [1].",
                 "Expect some abuse of notation in the proofs [2]."):
        check(f"course wording passes the stems: {text!r}",
              validate_output(text, {"comment_count": 3})["ok"] is True)

    ok_v, t = conduct_check("fine", lambda a: {"conduct_claim": False, "error": False, "tokens_used": 120})
    check("conduct check passes a clean answer and reports tokens", ok_v["ok"] is True and t == 120)
    flagged, _ = conduct_check("x", lambda a: {"conduct_claim": True, "error": False, "tokens_used": 90})
    check("conduct check blocks a flagged answer",
          flagged["ok"] is False and flagged["status"] == "validation_failed")
    errored, _ = conduct_check("x", lambda a: {"conduct_claim": False, "error": True, "tokens_used": 0})
    check("conduct check fails closed on an error", errored["ok"] is False)

    # Issue 15: after chat_answer expands grouped citations ([1, 2] -> [1] [2]) before
    # validation sees the text, validate_output must extract both ids into "cited".
    grouped = validate_output("good prof [1] [2].", {"comment_count": 3})
    check("validate_output extracts a multi-citation set", grouped["ok"] is True
          and set(grouped["cited"]) == {1, 2})
    single = validate_output("Some students say Guha is hard but fair [1].", {"comment_count": 3})
    check("validate_output still extracts a single citation", set(single["cited"]) == {1})

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0

def main():
    p = argparse.ArgumentParser(description="Question-path output gate (anti-defamation).")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")

if __name__ == "__main__":
    main()
