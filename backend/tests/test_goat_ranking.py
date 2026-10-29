"""Tests for the GOATED leaderboard's Bayesian ranking.

Ranking by raw avg_rating let a 5.00 from 3 reviews outrank a 4.9 from 500 --
551 professors sit at exactly 5.00 and 97% of them have fewer than 15 reviews.
The board now sorts on a shrunk posterior mean instead, while still *displaying*
avg_rating.
"""

import os

import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
import server

# An arbitrary but realistic prior for the arithmetic below. It is NOT the live
# value and must not be read as one: measured on the 2026-08-03 corpus the prior
# is 4.452, and it moves whenever the corpus is re-scraped or the blend changes
# (this constant said 4.169 before single-source calibration raised every RMP-only
# rating). ranking_prior() reads the real one; nothing here should hardcode it.
C = 4.169


def rank(profs):
    """Order professors the way the SQL does: shrunk score desc, reviews desc."""
    return sorted(
        profs,
        key=lambda p: (server.shrunk_score(p[1], p[2], C), p[2]),
        reverse=True,
    )


# ── the maths ───────────────────────────────────────────────────────────────

def test_low_n_perfect_score_is_dragged_toward_the_mean():
    # 5.00 from 3 reviews carries almost no evidence.
    assert server.shrunk_score(5.0, 3, C) == pytest.approx(4.216, abs=0.001)


def test_high_n_score_barely_moves():
    # 4.96 from 454 reviews is well evidenced, so it should stay near 4.96.
    assert server.shrunk_score(4.96, 454, C) == pytest.approx(4.882, abs=0.001)


def test_more_reviews_means_less_shrinkage():
    a = server.shrunk_score(4.9, 20, C)
    b = server.shrunk_score(4.9, 500, C)
    assert b > a, "the better-evidenced professor must score higher"


def test_zero_reviews_collapses_to_the_prior():
    assert server.shrunk_score(4.9, 0, C) == pytest.approx(C)


def test_none_rating_returns_none():
    assert server.shrunk_score(None, 100, C) is None


def test_null_review_count_is_treated_as_zero():
    assert server.shrunk_score(4.9, None, C) == pytest.approx(C)


# ── the ranking this exists to fix ──────────────────────────────────────────

def test_three_review_five_star_no_longer_beats_a_well_reviewed_professor():
    # (name, avg_rating, total_reviews) — the exact Law/ProfStudies failure.
    ghost = ("Perfect, 3 reviews", 5.0, 3)
    real = ("Excellent, 500 reviews", 4.90, 500)
    assert rank([ghost, real])[0] is real


def test_ordering_among_well_reviewed_professors_is_preserved():
    # Shrinkage must not reshuffle professors who all have plenty of evidence.
    profs = [("a", 4.96, 454), ("b", 4.90, 400), ("c", 4.85, 300)]
    assert [p[0] for p in rank(profs)] == ["a", "b", "c"]


def test_a_slightly_lower_but_far_better_evidenced_score_can_win():
    # 4.81 from 1518 reviews outranks 4.89 from 224 — the intended correction.
    low_n = ("4.89 / 224", 4.89, 224)
    high_n = ("4.81 / 1518", 4.81, 1518)
    assert rank([low_n, high_n])[0] is high_n


def test_shrinkage_cannot_widen_the_top_band():
    # It is a contraction: for equal n the gap shrinks by n/(n+m). This is why
    # the fix is the sort key and not the displayed number.
    raw_gap = 4.96 - 4.85
    shrunk_gap = server.shrunk_score(4.96, 400, C) - server.shrunk_score(4.85, 400, C)
    assert shrunk_gap < raw_gap


# ── wiring ──────────────────────────────────────────────────────────────────

def test_ranking_sql_is_used_by_the_leaderboard_query():
    src = server.goat_professors.__doc__ or ""
    import inspect
    body = inspect.getsource(server.goat_professors)
    assert "RANKING_SCORE_SQL" in body, "leaderboard must sort on the shrunk score"
    assert "ORDER BY avg_rating" not in body, "raw avg_rating ordering must be gone"


def test_ranking_sql_reads_the_prior_from_the_data():
    # Hardcoding C would drift every time the corpus is re-scraped.
    assert str(server.SHRINKAGE_M) in server.RANKING_SCORE_SQL


# ── the prior, measured over professors who actually have a measurement ─────
#
# C was avg(avg_rating) over the whole catalog, which is mostly professors with a
# handful of responses: their ratings are noise, and averaging noise gives a
# number that describes the noise, not the professors. The prior of a ranking
# should be the mean of the quantity being ranked, so it is measured over
# professors whose rating is actually pinned down.

CATALOG = [   # (avg_rating, total_reviews)
    (5.00, 2), (5.00, 3), (1.00, 1), (5.00, 4),     # thin: noise, not measurements
    (4.20, 300), (4.30, 250), (4.10, 400),          # well evidenced
]


def prior_query_one(sql, params):
    """Stands in for the DB, honouring the review floor the query passes."""
    floor = params[0]
    kept = [rating for rating, n in CATALOG if n >= floor]
    return {"prior": sum(kept) / len(kept)} if kept else {"prior": None}


def test_prior_ignores_professors_with_too_little_evidence():
    # The well-evidenced mean is 4.20; the whole-catalog mean is 4.09 and is
    # decided by four professors with ten responses between them.
    assert server.ranking_prior(prior_query_one) == pytest.approx(4.20, abs=0.005)


def test_prior_passes_its_evidence_floor_to_the_query():
    seen = {}

    def spy(sql, params):
        seen["params"] = params
        return {"prior": 4.2}

    server.ranking_prior(spy)
    assert seen["params"] == (server.RANKING_PRIOR_MIN_REVIEWS,)


def test_prior_falls_back_when_nothing_is_well_evidenced():
    # An empty or brand-new catalog must not divide by zero or rank on None.
    assert server.ranking_prior(lambda sql, params: {"prior": None}) == \
        pytest.approx(server.FALLBACK_PRIOR)
    assert server.ranking_prior(lambda sql, params: None) == \
        pytest.approx(server.FALLBACK_PRIOR)


def test_prior_is_not_college_specific():
    # A per-college prior ranks professors against their own college, which is
    # department-relative ranking under another name — considered and rejected;
    # the board is a class-picking tool, not a per-department award.
    import inspect
    body = inspect.getsource(server.ranking_prior)
    assert "college" not in body


def test_leaderboard_measures_the_prior_rather_than_averaging_the_column():
    import inspect
    body = inspect.getsource(server.goat_professors)
    assert "ranking_prior(" in body
    assert "avg(avg_rating)" not in server.RANKING_SCORE_SQL, \
        "the prior is measured separately, not averaged inside the sort"


def test_leaderboard_returns_total_reviews():
    import inspect
    body = inspect.getsource(server.goat_professors)
    assert '"totalReviews"' in body, "Reviews column needs rated-response counts"


def test_cache_key_was_versioned():
    # A stale entry would serve the previous ordering after deploy — bumped for
    # the shrunk score, again when the prior changed, again for the single review
    # floor plus the name tiebreak, again for the Law/Professional Studies floor.
    import inspect
    assert 'goat:v6:' in inspect.getsource(server.goat_professors)


# ── the review floor ────────────────────────────────────────────────────────
#
# One floor for every college at the same 30 the prior uses. A board short of
# 10 at 30 is filled from professors with 5, ranked below everyone at 30.


def test_board_floor_matches_the_prior_floor():
    # Ranking someone the prior refuses to learn from is incoherent.
    assert server.BOARD_MIN_REVIEWS == server.RANKING_PRIOR_MIN_REVIEWS


def _board_params(monkeypatch, college):
    seen = []
    monkeypatch.setattr(server, "query", lambda sql, params: seen.append((sql, params)) or [])
    monkeypatch.setattr(server, "query_one", lambda sql, params: {"prior": C})
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, val: None)
    with server.app.test_request_context(f"/api/goat-professors?college={college}"):
        server.goat_professors()
    return seen


@pytest.mark.parametrize("college", ["Khoury", "Business", "Health Sciences"])
def test_every_college_gets_the_same_fill_rule(monkeypatch, college):
    # No per-college floors: a short board fills from 5 wherever it is short.
    [(_, params)] = _board_params(monkeypatch, college)
    assert params == (college, server.BOARD_FILL_MIN_REVIEWS, C, server.BOARD_MIN_REVIEWS, C, 10)


def test_the_fill_ranks_below_every_well_measured_professor(monkeypatch):
    # Shrinkage alone puts 5.00 on 20 ratings above 4.50 on 30.
    assert server.shrunk_score(5.0, 20, C) > server.shrunk_score(4.50, 30, C)
    [(sql, _)] = _board_params(monkeypatch, "Health Sciences")
    order = " ".join(sql.split()).split("ORDER BY ")[1]
    assert order.startswith("total_reviews >= %s DESC,"), "the 30+ tier must sort first"


@pytest.mark.parametrize("college", ["Law", "Professional Studies"])
def test_law_and_professional_studies_have_no_board(monkeypatch, college):
    assert college not in server.BOARD_COLLEGES
    assert _board_params(monkeypatch, college) == []


def test_every_other_college_has_a_board():
    assert server.BOARD_COLLEGES == set(server.COLLEGE_MAP.values()) - {"Law", "Professional Studies"}


def test_a_below_average_rating_is_off_the_board(monkeypatch):
    # A 2.86 on 250 ratings sat at Health Sciences #5 before this.
    [(sql, params)] = _board_params(monkeypatch, "Health Sciences")
    assert "avg_rating >= %s" in " ".join(sql.split())
    assert params[2] == C, "the cutoff is the same prior the score shrinks toward"


def test_the_fill_floor_is_below_the_board_floor():
    assert server.BOARD_FILL_MIN_REVIEWS < server.BOARD_MIN_REVIEWS


def test_floor_defaults_to_the_constant_not_a_literal():
    import inspect
    body = inspect.getsource(server.goat_professors)
    assert "BOARD_MIN_REVIEWS" in body
    assert '"100"' not in body, "the old 100 default must be gone"


def test_thin_professors_reach_a_board_only_as_fill(monkeypatch):
    # 7 reviews clear the fill floor but not the board floor, so a perfect 5.00
    # on 7 sorts below every professor at 30. Within the fill, shrinkage still
    # sinks it below real evidence.
    assert server.BOARD_FILL_MIN_REVIEWS <= 7 < server.BOARD_MIN_REVIEWS
    [(sql, params)] = _board_params(monkeypatch, "Khoury")
    order = " ".join(sql.split()).split("ORDER BY ")[1]
    assert order.startswith("total_reviews >= %s DESC,")
    assert params[3] == server.BOARD_MIN_REVIEWS, "the tier splits at the board floor"
    thin = server.shrunk_score(5.0, 7, C)
    real = server.shrunk_score(4.68, 96, C)
    assert real > thin, "96 reviews at 4.68 outweigh 7 at a perfect 5.00"


def test_the_floor_is_low_enough_not_to_be_the_thing_doing_the_excluding():
    # 100 excluded people the score already excluded. At 30 the score has to earn
    # it: a professor at the floor with a perfect 5.00 must still land below a
    # well-evidenced 4.9, or the floor is load-bearing again.
    at_floor = server.shrunk_score(5.0, server.BOARD_MIN_REVIEWS, C)
    established = server.shrunk_score(4.90, 500, C)
    assert established > at_floor


# ── determinism ─────────────────────────────────────────────────────────────

def test_ordering_breaks_ties_by_name():
    # Equal score and equal review count left the order to the scan, so a board
    # could reshuffle between two identical requests.
    import inspect
    body = inspect.getsource(server.goat_professors)
    assert "total_reviews DESC, name" in body


# ── comment counts ──────────────────────────────────────────────────────────

ROW = {"slug": "olin-guha", "name": "Olin Guha", "department": "Khoury",
       "name_key": "olin guha", "rmp_rating": 4.1, "avg_rating": 4.1,
       "total_reviews": 250, "total_comments": 30}


def _run_leaderboard(monkeypatch, catalog_rows):
    seen = []

    def query(sql, params):
        s = " ".join(sql.split())
        seen.append(s)
        if "FROM professors_catalog" in s:
            return catalog_rows
        raise AssertionError(f"unexpected query: {s}")

    monkeypatch.setattr(server, "query", query)
    monkeypatch.setattr(server, "query_one", lambda sql, params: {"prior": C})
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, val: None)
    with server.app.test_request_context("/api/goat-professors?college=Khoury"):
        resp = server.goat_professors()
    return {p["name"]: p for p in resp.get_json()}, seen


def test_board_reads_the_stored_comment_count(monkeypatch):
    out, _ = _run_leaderboard(monkeypatch, [ROW])
    assert out["Olin Guha"]["totalComments"] == 30


def test_board_row_has_exactly_these_keys(monkeypatch):
    out, _ = _run_leaderboard(monkeypatch, [ROW])
    assert set(out["Olin Guha"]) == {"name", "dept", "rmpRating", "avgRating",
                                     "totalReviews", "totalComments"}


def test_board_is_one_statement(monkeypatch):
    _, seen = _run_leaderboard(monkeypatch, [ROW])
    assert len(seen) == 1   # the prior goes through query_one, so GOAT is two statements in all


def test_an_empty_board_is_served_from_cache(monkeypatch):
    # A college with no professor over the floor caches []; it must not re-run the queries.
    monkeypatch.setattr(server, "cache_get", lambda key: [])
    monkeypatch.setattr(server, "query", lambda *a: pytest.fail("cached board re-queried"))
    monkeypatch.setattr(server, "query_one", lambda *a: pytest.fail("cached board re-queried"))
    with server.app.test_request_context("/api/goat-professors?college=Khoury"):
        assert server.goat_professors().get_json() == []


def test_an_unknown_college_is_not_queried_or_cached(monkeypatch):
    monkeypatch.setattr(server, "cache_get", lambda key: pytest.fail("unknown college read the cache"))
    monkeypatch.setattr(server, "cache_set", lambda *a: pytest.fail("unknown college cached"))
    monkeypatch.setattr(server, "query", lambda *a: pytest.fail("unknown college queried"))
    monkeypatch.setattr(server, "query_one", lambda *a: pytest.fail("unknown college queried"))
    with server.app.test_request_context("/api/goat-professors?college=xyz"):
        assert server.goat_professors().get_json() == []


@pytest.mark.parametrize("args, limit", [("limit=-5", 1), ("limit=500", 50), ("limit=x", 10)])
def test_the_limit_is_clamped_and_the_floor_is_not_a_parameter(monkeypatch, args, limit):
    # Free values would each store a cache entry, and LIMIT -5 is a Postgres error.
    seen = []
    monkeypatch.setattr(server, "query", lambda sql, params: seen.append(params) or [])
    monkeypatch.setattr(server, "query_one", lambda sql, params: {"prior": C})
    monkeypatch.setattr(server, "cache_get", lambda key: seen.append(key) and None)
    monkeypatch.setattr(server, "cache_set", lambda key, val: None)
    with server.app.test_request_context(f"/api/goat-professors?college=Khoury&{args}&min_reviews=1"):
        server.goat_professors()
    assert seen == [f"goat:v6:Khoury:{limit}",
                    ("Khoury", server.BOARD_FILL_MIN_REVIEWS, C, server.BOARD_MIN_REVIEWS, C, limit)]
