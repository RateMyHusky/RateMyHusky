"""Comment moderation. this is where the scores go.
"""

import os
from collections import namedtuple

MODEL = "omni-moderation-latest"
BATCH_SIZE = 100


Verdict = namedtuple("Verdict", ["action", "reason", "scores"])


class ModerationUnavailable(Exception):
    """Fail closed — leave the row unscored rather than letting a network blip
    look like a clean verdict."""


# we can always change these thresholds. This is important. these thresholds are high on purpose, or else everything would be filtered

BLOCK_THRESHOLDS = {
    "harassment/threatening": 0.50,
    "hate": 0.50,
    "hate/threatening": 0.25,
    "violence": 0.70,
    "violence/graphic": 0.80,
    "sexual": 0.80,
    "sexual/minors": 0.20,
    "self-harm/instructions": 0.50,
    "illicit/violent": 0.50,
}

# borderline 
REVIEW_THRESHOLDS = {
    "harassment": 0.90,
    "harassment/threatening": 0.25,
    "hate": 0.25,
    "violence": 0.40,
    "sexual": 0.50,
}

REVIEW_HIDES = False


def classify(scores: dict) -> Verdict:
    if not scores:
        return Verdict("allow", "", {})

    tripped = [c for c, t in BLOCK_THRESHOLDS.items() if scores.get(c, 0.0) >= t]
    if tripped:
        return Verdict("block", ",".join(sorted(tripped)), scores)

    flagged = [c for c, t in REVIEW_THRESHOLDS.items() if scores.get(c, 0.0) >= t]
    if flagged:
        return Verdict("review", ",".join(sorted(flagged)), scores)

    return Verdict("allow", "", scores)


def is_published(action: str) -> bool:
    """Keep sql_filter() in step with this."""
    if action == "block":
        return False
    if action == "review":
        return not REVIEW_HIDES
    return True


# Off by default: turning it on before the backfill finishes hides every comment
# on the site. Backfill first, then set MODERATION_ENFORCE=true.
def enforcing() -> bool:
    return os.getenv("MODERATION_ENFORCE", "false").strip().lower() in ("1", "true", "yes")


def sql_filter(alias: str = "") -> str:
    """Comes back starting with AND, or empty when enforcement is off, so
    callers can drop it into a WHERE clause without branching."""
    if not enforcing():
        return ""
    p = f"{alias}." if alias else ""
    hidden = ["'block'"] if not REVIEW_HIDES else ["'block'", "'review'"]
    # unscored rows don't publish either, so a half-finished backfill shows too
    # little rather than leaking something nobody looked at
    return (f" AND {p}mod_checked_at IS NOT NULL"
            f" AND coalesce({p}mod_action, 'allow') NOT IN ({', '.join(hidden)})")


def _default_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ModerationUnavailable("OPENAI_API_KEY is not set")
    # same `openai` package the Groq adapter uses, just without the base_url
    # override — so this costs us no new dependency
    from openai import OpenAI
    return OpenAI(api_key=api_key, timeout=30)


def score_texts(texts, client=None):
    """One Verdict per input, order preserved. Pass `client` in tests to stay
    off the network."""
    if not texts:
        return []

    client = client or _default_client()
    verdicts = []

    for start in range(0, len(texts), BATCH_SIZE):
        chunk = [t or "" for t in texts[start:start + BATCH_SIZE]]
        try:
            resp = client.moderations.create(model=MODEL, input=chunk)
        except Exception as exc:
            raise ModerationUnavailable(f"moderation API call failed: {exc}") from exc

        results = getattr(resp, "results", None) or []
        if len(results) != len(chunk):
            raise ModerationUnavailable(
                f"moderation API returned {len(results)} results for {len(chunk)} inputs"
            )

        for r in results:
            raw = getattr(r, "category_scores", None) or {}
            # SDK hands back a pydantic model, tests hand back a dict.
            # by_alias is load-bearing: the model's field names are underscored
            # (harassment_threatening) and the thresholds below use the API's
            # slashed names, so dumping without it silently zeroes every
            # severe category.
            scores = raw if isinstance(raw, dict) else raw.model_dump(by_alias=True)
            verdicts.append(classify(scores))

    return verdicts


# ── selftest:  python backend/moderation.py ──

def selftest():
    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)
        print(("  ok  " if cond else "  FAIL") + "  " + label)

    print("moderation.selftest")

    # ── classify: thresholds ──
    check("clean scores allow", classify({"harassment": 0.01}).action == "allow")
    check("empty scores allow", classify({}).action == "allow")
    check("threat blocks", classify({"harassment/threatening": 0.9}).action == "block")
    check("hate blocks", classify({"hate": 0.7}).action == "block")
    check("block reports category", "hate" in classify({"hate": 0.7}).reason)

    check("plain harassment does not block",
          classify({"harassment": 0.75}).action != "block")
    check("harsh review stays published",
          is_published(classify({"harassment": 0.75}).action))

    check("borderline lands in review",
          classify({"harassment": 0.95}).action == "review")
    check("review published per REVIEW_HIDES",
          is_published("review") is (not REVIEW_HIDES))
    check("block is never published", is_published("block") is False)

    # ── read-path enforcement ──
    _prev = os.environ.get("MODERATION_ENFORCE")
    try:
        os.environ["MODERATION_ENFORCE"] = "false"
        check("enforcement off by default", enforcing() is False)
        check("filter is empty when not enforcing", sql_filter() == "")
        check("filter is empty with alias too", sql_filter("r") == "")

        os.environ["MODERATION_ENFORCE"] = "true"
        check("enforcement flag read", enforcing() is True)
        f = sql_filter()
        check("filter starts with AND", f.lstrip().startswith("AND"))
        check("filter excludes blocked", "'block'" in f)
        check("filter is fail-closed on unscored", "mod_checked_at IS NOT NULL" in f)
        check("filter respects REVIEW_HIDES",
              ("'review'" in f) is REVIEW_HIDES)
        check("filter applies alias", "r.mod_action" in sql_filter("r"))
    finally:
        if _prev is None:
            os.environ.pop("MODERATION_ENFORCE", None)
        else:
            os.environ["MODERATION_ENFORCE"] = _prev

    # ── score_texts, fake client, no network ──
    class _FakeResult:
        def __init__(self, scores):
            self.category_scores = scores

    class _FakeClient:
        def __init__(self, per_text):
            self.per_text = per_text
            self.calls = 0

        class _Mod:
            def __init__(self, outer):
                self.outer = outer

            def create(self, model, input):
                self.outer.calls += 1
                return type("R", (), {
                    "results": [_FakeResult(self.outer.per_text(t)) for t in input]
                })()

        @property
        def moderations(self):
            return _FakeClient._Mod(self)

    fake = _FakeClient(lambda t: {"hate": 0.9} if "slur" in t else {"hate": 0.0})
    out = score_texts(["fine", "slur here", "also fine"], client=fake)
    check("one verdict per input", len(out) == 3)
    check("order preserved", [v.action for v in out] == ["allow", "block", "allow"])
    check("single batched call", fake.calls == 1)
    check("empty input needs no call", score_texts([], client=fake) == [])

    class _BrokenClient:
        @property
        def moderations(self):
            raise RuntimeError("network down")

    try:
        score_texts(["x"], client=_BrokenClient())
        check("transport failure raises", False)
    except ModerationUnavailable:
        check("transport failure raises", True)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all passed'}")
    return not failures


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
