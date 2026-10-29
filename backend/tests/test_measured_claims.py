"""Guards the measured numbers that are written into comments.

Several comments around the leaderboard quote numbers measured off the live
corpus -- how many professors sit at exactly 5.00, how long each college's board
is at the review floor, how many ties the name tiebreak settles. They are load-bearing:
each one is the evidence for a design decision sitting right next to it, and a
reader who re-measures and gets something different has to work out whether the
code broke or the comment rotted.

They rot silently. Every one of them is a function of `professors_catalog`, which
`precompute.py` rebuilds wholesale, so a single precompute run can invalidate a
dozen comments in files nobody touched. That is exactly what happened on
2026-08-03: the total_reviews redefinition left six numbers wrong across
server.py and Homepage.tsx, one of them ("798 professors with no written RMP
review", actually 1,907) off by more than 2x.

So each claim is parsed back out of the source and re-measured here.

Two deliberate choices:

  - Tolerances are loose, and per claim. The failure being caught is "a reader
    would draw a different conclusion", not "the corpus moved". A comment saying
    276 when the answer is 277 misleads nobody, and a test that fails on it gets
    switched off, taking the 2x errors down with it.
  - The patterns are anchored on the surrounding prose, and each must match
    exactly once (test_every_claim_is_locatable). Rewording a guarded comment
    fails the suite rather than silently un-guarding it -- the alternative,
    matching a bare number, would quietly follow along to whatever else it hit.

Skips cleanly with no database, so CI without credentials is unaffected.
"""

import os
import pathlib
import re

import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
import server

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVER_PY = REPO / "backend" / "server.py"
HOMEPAGE_TSX = REPO / "frontend" / "src" / "pages" / "Homepage.tsx"
GOAT_TEST = REPO / "backend" / "tests" / "test_goat_ranking.py"


# ── database ────────────────────────────────────────────────────────────────

def _live_url():
    """The real connection string, read from .env rather than the environment.

    Every DB-touching test module pins os.environ["ORACLE_DATABASE_URL"] to
    "postgresql://stub" via setdefault, and modules are collected alphabetically,
    so by the time this one runs the variable is almost always the stub --
    load_dotenv() will not override an existing value. dotenv_values() parses the
    file without touching os.environ, which keeps that stub intact for everyone
    else while still letting this module reach the real corpus.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    url = dotenv_values(REPO / "backend" / ".env").get("ORACLE_DATABASE_URL")
    if url:
        return url
    env_url = os.getenv("ORACLE_DATABASE_URL")
    return None if env_url == "postgresql://stub" else env_url


class Corpus:
    """Thin query helper, plus the derived quantities claims are measured against."""

    def __init__(self, conn):
        import psycopg2.extras
        self._cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def rows(self, sql, params=None):
        self._cur.execute(sql, params)
        return self._cur.fetchall()

    def one(self, sql, params=None):
        rows = self.rows(sql, params)
        return rows[0] if rows else None

    def val(self, sql, params=None):
        row = self.one(sql, params)
        return None if row is None else next(iter(row.values()))

    @property
    def prior(self):
        # server's own function, so the test ranks the way production ranks
        # instead of re-deriving a formula that could drift away from it.
        if not hasattr(self, "_prior"):
            self._prior = server.ranking_prior(self.one)
        return self._prior

    @property
    def colleges(self):
        """Colleges that have a board."""
        return [r["college"] for r in self.rows(
            "SELECT DISTINCT college FROM professors_catalog "
            "WHERE college IS NOT NULL ORDER BY college")
            if r["college"] in server.BOARD_COLLEGES]

    def board(self, college, floor=None, limit=10):
        """The board as served when floor is None: the professors at
        BOARD_MIN_REVIEWS first, filled from BOARD_FILL_MIN_REVIEWS. Otherwise
        the board a floor of `floor` with no fill would serve. Both drop ratings
        below the prior, as the endpoint does, so a hypothetical floor is
        measured under the same rules as the real one."""
        # Cached: several claims read the same board, each a round trip to a
        # remote database otherwise. Keyed on the floor as passed, so the served
        # board (None) never shares an entry with a plain board at 5.
        if not hasattr(self, "_boards"):
            self._boards = {}
        key = (college, floor, limit)
        if key not in self._boards:
            served = floor is None
            lowest = server.BOARD_FILL_MIN_REVIEWS if served else floor
            tier = server.BOARD_MIN_REVIEWS if served else floor
            self._boards[key] = self.rows(
                f"SELECT * FROM professors_catalog WHERE college = %s "
                f"AND total_reviews >= %s AND avg_rating >= %s "
                f"ORDER BY total_reviews >= %s DESC, {server.RANKING_SCORE_SQL} DESC, "
                f"total_reviews DESC, name LIMIT %s",
                (college, lowest, self.prior, tier, self.prior, limit))
        return self._boards[key]

    @property
    def all_board_rows(self):
        if not hasattr(self, "_rows"):
            self._rows = [r for c in self.colleges for r in self.board(c)]
        return self._rows

    def rating_inversions(self, college):
        """Adjacent pairs where the displayed rating goes up as rank goes down."""
        board = self.board(college)
        return sum(1 for a, b in zip(board, board[1:])
                   if (a["avg_rating"] or 0) < (b["avg_rating"] or 0))

    def full_boards(self):
        """(names at the floor, names at a floor of 100) for each board that fills
        at the floor. A board full at the floor never reaches the fill, so the
        first list is the board as served."""
        at_30 = server.BOARD_MIN_REVIEWS
        return [([r["name"] for r in self.board(x, floor=at_30)],
                 [r["name"] for r in self.board(x, floor=100)])
                for x in self.colleges if len(self.board(x, floor=at_30)) == 10]

    def eligible_at_five(self):
        """Law and Professional Studies professors the old floor of 5 ranked."""
        return self.rows(
            f"SELECT total_reviews, {server.RANKING_SCORE_SQL} s FROM professors_catalog "
            f"WHERE college IN ('Law', 'Professional Studies') "
            f"AND avg_rating IS NOT NULL AND total_reviews >= 5", (self.prior,))


@pytest.fixture(scope="module")
def corpus():
    url = _live_url()
    if not url:
        pytest.skip("no ORACLE_DATABASE_URL in backend/.env -- claims unverified")
    try:
        import psycopg2
        conn = psycopg2.connect(url, sslmode="require", connect_timeout=15)
        # Autocommit because the connection is shared by every claim in the
        # module and all of this is read-only. Without it one failing query
        # aborts the transaction and every subsequent claim dies with
        # InFailedSqlTransaction instead of its own result, which turns a single
        # broken measurement into twenty identical unhelpful failures.
        conn.autocommit = True
    except Exception as exc:                      # noqa: BLE001 - any failure skips
        pytest.skip(f"database unreachable -- claims unverified ({exc})")
    try:
        yield Corpus(conn)
    finally:
        conn.close()


# ── the claims ──────────────────────────────────────────────────────────────
# (label, file, pattern with one capture group, measure, tolerance)
#
# Tolerance is ("rel", fraction) or ("abs", amount). Percentages and small
# multiples take absolute tolerances: 5% of "95%" is nearly five points, which
# would wave through a genuinely misleading number.

CLAIMS = [
    ("professors at exactly 5.00", SERVER_PY,
     r"\b(\d+) professors sit at exactly 5\.00",
     lambda c: c.val("SELECT count(*) FROM professors_catalog WHERE avg_rating = 5.0"),
     ("rel", 0.10)),

    ("share of those under 15 reviews", SERVER_PY,
     r"and (\d+)% of them have under 15 reviews",
     lambda c: 100.0 * c.val(
         # Both sides cast: count(*) is BIGINT, and integer division would
         # truncate the share to 0.
         "SELECT count(*) FILTER (WHERE total_reviews < 15)::float "
         "     / count(*)::float "
         "FROM professors_catalog WHERE avg_rating = 5.0"),
     ("abs", 3)),

    ("reviews needed to reach Khoury rank 10", SERVER_PY,
     r"rank-10 score needs ~(\d+)\s*\n#\s*reviews",
     lambda c: _reviews_to_reach(c, "Khoury"),
     ("rel", 0.15)),

    ("Law professors eligible at a floor of 5", SERVER_PY,
     r"Law had (\d+) eligible at that floor",
     lambda c: c.val("SELECT count(*) FROM professors_catalog WHERE college = 'Law' "
                     "AND avg_rating IS NOT NULL AND total_reviews >= 5"),
     ("abs", 2)),

    ("Professional Studies eligible at a floor of 5", SERVER_PY,
     r"and Professional\s*\n#\s*Studies (\d+), so",
     lambda c: c.val("SELECT count(*) FROM professors_catalog "
                     "WHERE college = 'Professional Studies' "
                     "AND avg_rating IS NOT NULL AND total_reviews >= 5"),
     ("abs", 3)),

    ("most ratings among those", SERVER_PY,
     r"\bto (\d+) ratings each",
     lambda c: max(r["total_reviews"] for r in c.eligible_at_five()),
     ("abs", 3)),

    ("furthest of those from the prior", SERVER_PY,
     r"scoring within (0\.\d+) of the prior",
     lambda c: max(abs(float(r["s"]) - c.prior) for r in c.eligible_at_five()),
     ("abs", 0.05)),

    # Names, not lengths: a 10-row board can keep its length at 100 and still
    # change who is on it.
    ("full boards a floor of 100 would change", SERVER_PY,
     r"all (\d+) of the boards that fill at 30 change members",
     lambda c: sum(1 for at_30, at_100 in c.full_boards() if at_30 != at_100),
     ("abs", 1)),

    ("full boards a floor of 100 would shorten", SERVER_PY,
     r"change members, (\d+) of them lose rows",
     lambda c: sum(1 for at_30, at_100 in c.full_boards() if len(at_100) < len(at_30)),
     ("abs", 1)),

    ("length of the Engineering board at 100", SERVER_PY,
     r"and Engineering's drops to (\d+)\.",
     lambda c: len(c.board("Engineering", floor=100)),
     ("abs", 1)),

    ("score/review-count tie groups", SERVER_PY,
     r"\b(\d+) such groups across the catalog",
     lambda c: _tie_groups(c)[0],
     ("abs", 2)),

    ("professors involved in those ties", SERVER_PY,
     r"covering (\d+) professors",
     lambda c: _tie_groups(c)[1],
     ("abs", 4)),

    # Exact at the low end: a board with two or more rows and no inversion
    # makes "every board" false.
    ("fewest rating inversions on a board", HOMEPAGE_TSX,
     r"moves backwards between adjacent rows, (\d+)-\d+ times per board",
     lambda c: min(_inversions(c), default=None),
     ("abs", 0)),

    ("most rating inversions on a board", HOMEPAGE_TSX,
     r"moves backwards between adjacent rows, \d+-(\d+) times per board",
     lambda c: max(_inversions(c), default=None),
     ("abs", 1)),

    ("professors at exactly 5.00 (goat test docstring)", GOAT_TEST,
     r"\b(\d+) professors sit at exactly 5\.00",
     lambda c: c.val("SELECT count(*) FROM professors_catalog WHERE avg_rating = 5.0"),
     ("rel", 0.10)),
]


def _inversions(corpus):
    """Rating inversions per board, over boards with two or more rows, as the
    Homepage comment counts them."""
    return [corpus.rating_inversions(x) for x in corpus.colleges if len(corpus.board(x)) > 1]


def _reviews_to_reach(corpus, college):
    """How many reviews a flawless 5.00 needs to reach a board's rank-10 score.

    Rank 10 of the board at the floor, not the served one: on a short board the
    served rank 10 is a fill professor, and the claim is about the floor."""
    board = corpus.board(college, floor=server.BOARD_MIN_REVIEWS)
    if len(board) < 10:
        return 0
    target = server.shrunk_score(
        board[9]["avg_rating"], board[9]["total_reviews"], corpus.prior)
    n = 1
    while server.shrunk_score(5.0, n, corpus.prior) < target:
        n += 1
        if n > 100_000:                            # unreachable target
            return n
    return n


def _tie_group_sizes(corpus, college=None):
    """One row per group tied on both score and review count, so `name` decides.

    Grouped by college as well as by score and review count, because each board
    is a single college: two professors in different colleges never compete for a
    slot, so a tie between them is not a tie the `name` tiebreak has to settle.
    Grouping globally would also count ties between professors on different
    boards.

    Deliberately not wrapped in an outer count(*): that returns a single row
    holding the number of groups, which reads as one group of that size and gets
    the two numbers backwards.
    """
    where = "total_reviews >= %s AND avg_rating IS NOT NULL"
    params = [corpus.prior, server.BOARD_MIN_REVIEWS]
    if college is not None:
        where += " AND college = %s"
        params.append(college)
    return corpus.rows(
        f"SELECT count(*) c FROM ("
        f"  SELECT college, {server.RANKING_SCORE_SQL} s, total_reviews "
        f"  FROM professors_catalog WHERE {where}"
        f") t GROUP BY college, s, total_reviews HAVING count(*) > 1",
        tuple(params))


def _tie_groups(corpus):
    """(groups, professors involved)."""
    rows = _tie_group_sizes(corpus)
    return len(rows), sum(int(r["c"]) for r in rows)


def _find(path, pattern):
    """(stated number, line) for a pattern that must appear exactly once."""
    text = path.read_text()
    matches = list(re.finditer(pattern, text))
    assert len(matches) == 1, (
        f"{path.name}: expected exactly 1 match for {pattern!r}, found "
        f"{len(matches)}. The guarded comment was reworded or removed -- update "
        f"the pattern in CLAIMS so the number stays guarded.")
    m = matches[0]
    return float(m.group(1).replace(",", "")), text[:m.start(1)].count("\n") + 1


IDS = [c[0] for c in CLAIMS]


@pytest.mark.parametrize("label,path,pattern,measure,tol", CLAIMS, ids=IDS)
def test_every_claim_is_locatable(label, path, pattern, measure, tol):
    """Fails on a reworded comment even with no database to check it against."""
    _find(path, pattern)


@pytest.mark.parametrize("label,path,pattern,measure,tol", CLAIMS, ids=IDS)
def test_claim_still_matches_the_corpus(label, path, pattern, measure, tol, corpus):
    stated, line = _find(path, pattern)
    actual = measure(corpus)
    assert actual is not None, f"{label}: measured nothing"

    kind, amount = tol
    slack = amount if kind == "abs" else abs(actual) * amount
    assert abs(stated - actual) <= slack, (
        f"\n{path.relative_to(REPO)}:{line} is stale.\n"
        f"  claim:    {label}\n"
        f"  says:     {stated:g}\n"
        f"  measured: {actual:g}\n"
        f"  tolerance: +/-{slack:g}\n"
        f"Rewrite the comment with the measured value. If precompute.py has just "
        f"run, expect several of these together.")


def test_no_tie_group_reaches_a_board_top_ten(corpus):
    """The claim that survives a refresh: ties exist, but none are visible.

    This replaced a per-college assertion (that Law had none) which failed on
    data drift alone the first time total_reviews moved — the comment it guarded
    even predicted that, and still named the college. Which college holds a tie
    is not a property of the code; whether a tie can reorder a board a reader
    actually sees is.

    Measured the way the endpoint measures it: the same ORDER BY, per college,
    limited to the same 10.
    """
    ranked = (f"{server.RANKING_SCORE_SQL} DESC, total_reviews DESC, name")
    visible = []
    for college in corpus.colleges:
        top = corpus.rows(
            f"SELECT name, {server.RANKING_SCORE_SQL} s, total_reviews "
            f"FROM professors_catalog WHERE college = %s AND total_reviews >= %s "
            f"AND avg_rating >= %s "
            f"ORDER BY total_reviews >= %s DESC, {ranked} LIMIT 10",
            (corpus.prior, college, server.BOARD_FILL_MIN_REVIEWS, corpus.prior,
             server.BOARD_MIN_REVIEWS, corpus.prior))
        seen = {}
        for r in top:
            seen.setdefault((r["s"], r["total_reviews"]), []).append(r["name"])
        for names in seen.values():
            if len(names) > 1:
                visible.append((college, sorted(names)))
    assert not visible, (
        f"a tie now decides a visible board position: {visible}. The name "
        f"tiebreak keeps the order stable, but server.py claims no tie reaches "
        f"a top 10 — re-measure that claim.")
