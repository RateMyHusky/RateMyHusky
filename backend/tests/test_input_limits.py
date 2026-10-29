import pytest
import server


def _arg(fn, qs, *args):
    with server.app.test_request_context("/?" + qs):
        return fn(*args)


def test_int_arg_clamps_and_defaults():
    assert _arg(server.int_arg, "limit=0", "limit", 20, 1, 100) == 1
    assert _arg(server.int_arg, "limit=-5", "limit", 20, 1, 100) == 1
    assert _arg(server.int_arg, "limit=999999", "limit", 20, 1, 100) == 100
    assert _arg(server.int_arg, "limit=abc", "limit", 20, 1, 100) == 20
    assert _arg(server.int_arg, "", "limit", 20, 1, 100) == 20


def test_float_arg_rounds_so_near_values_share_a_cache_key():
    assert _arg(server.float_arg, "r=3.0001", "r", 0.0, 0.0, 5.0) == 3.0
    assert _arg(server.float_arg, "r=3.5", "r", 0.0, 0.0, 5.0) == 3.5
    assert _arg(server.float_arg, "r=nan", "r", 0.0, 0.0, 5.0) == 0.0
    assert _arg(server.float_arg, "r=99", "r", 0.0, 0.0, 5.0) == 5.0


def test_search_text_strips_wildcards_and_caps_length():
    assert server.search_text("100%_match") == "100match"
    assert server.search_text("a b c d e f g h") == "a b c d e f"
    assert len(server.search_text("x" * 500)) == server.SEARCH_MAX_CHARS


def test_catalog_limit_zero_is_not_a_500(monkeypatch):
    monkeypatch.setattr(server, "query_one", lambda *a, **k: {"cnt": 0})
    monkeypatch.setattr(server, "query", lambda *a, **k: [])
    monkeypatch.setattr(server, "data_version", lambda: 0)
    client = server.app.test_client()
    for path in ("/api/professors-catalog?limit=0&page=-3", "/api/courses-catalog?limit=0"):
        assert client.get(path).status_code == 200


def _served_limits(monkeypatch, rows=0):
    """The LIMIT each catalog page query ran with, for a catalog of `rows` rows."""
    limits = []
    monkeypatch.setattr(server, "query_one", lambda *a, **k: {"cnt": rows})
    monkeypatch.setattr(server, "query", lambda sql, params=(), **k: limits.append(params[-2]) or [])
    monkeypatch.setattr(server, "data_version", lambda: 0)
    server._cache.clear()
    return limits


@pytest.mark.parametrize("endpoint", ["professors-catalog", "courses-catalog"])
def test_only_the_sitemaps_request_gets_the_whole_catalog(monkeypatch, endpoint):
    limits = _served_limits(monkeypatch, rows=20000)
    client = server.app.test_client()
    # Filtered, sorted, later pages and in-between sizes are each built from scratch, so they're capped.
    for qs in ("limit=10000&sort=rating", "limit=10000&minRating=1.5", "limit=10000&page=2",
               "limit=101", "limit=9999"):
        client.get(f"/api/{endpoint}?{qs}")
    # limit=101 and limit=9999 are both the 100-row page, so the second is a cache hit.
    assert limits == [server.CACHEABLE_PAGE_LIMIT] * 4
    # Made-up sorts fall back to alpha, so they are the sitemap's request.
    for qs in ("limit=10000&page=1", "limit=10000&sort=x1", "limit=10000&sort=x2"):
        client.get(f"/api/{endpoint}?{qs}")
    assert limits[4:] == [server.CATALOG_FULL_LIMIT]
    server._cache.clear()


@pytest.mark.parametrize("endpoint", ["professors-catalog", "courses-catalog"])
def test_every_catalog_page_served_is_cached(monkeypatch, endpoint):
    limits = _served_limits(monkeypatch)
    client = server.app.test_client()
    for _ in range(2):
        client.get(f"/api/{endpoint}?limit=10000&sort=rating")
        client.get(f"/api/{endpoint}?limit=10000")
    assert len(limits) == 2 and len(server._cache) == 2
    server._cache.clear()


@pytest.mark.parametrize("endpoint", ["professors-catalog", "courses-catalog"])
def test_pages_past_the_end_share_the_last_pages_cache_entry(monkeypatch, endpoint):
    _served_limits(monkeypatch)
    client = server.app.test_client()
    for page in (1, 2, 50, 100000):
        assert client.get(f"/api/{endpoint}?page={page}").get_json()["page"] == 1
    assert len(server._cache) == 1
    server._cache.clear()


def test_unknown_sorts_share_alphas_cache_entry(monkeypatch):
    monkeypatch.setattr(server, "query_one", lambda *a, **k: {"cnt": 0})
    monkeypatch.setattr(server, "query", lambda *a, **k: [])
    monkeypatch.setattr(server, "data_version", lambda: 0)
    server._cache.clear()
    client = server.app.test_client()
    for sort in ("alpha", "x1", "x2"):
        client.get(f"/api/professors-catalog?sort={sort}")
        client.get(f"/api/courses-catalog?sort={sort}")
    assert len(server._cache) == 2
    server._cache.clear()


@pytest.mark.parametrize("typed, searched", [
    ("cs 3100", "cs3100"),          # course_catalog.search_text stores the code unspaced
    ("CS  3100", "cs3100"),
    ("cs3100", "cs3100"),
    ("math 1341 calc", "math1341 calc"),
    ("intro to cs", "intro to cs"),   # words only: nothing to join
    ("3100", "3100"),
])
def test_course_search_joins_a_spaced_course_code(typed, searched):
    assert server.course_search_text(typed) == searched


def _course_like_params(monkeypatch, path):
    seen = []
    monkeypatch.setattr(server, "query", lambda sql, params=(): seen.append(params) or [])
    monkeypatch.setattr(server, "query_one", lambda sql, params=(): {"cnt": 0, "total": 0})
    monkeypatch.setattr(server, "data_version", lambda: 0)
    server._cache.clear()
    server.limiter.reset()
    assert server.app.test_client().get(path, headers={"User-Agent": "Mozilla/5.0"}).status_code == 200
    return [p for params in seen for p in params if isinstance(p, str) and "%" in p]


@pytest.mark.parametrize("path", ["/api/search?type=Course&q=cs%203100",
                                  "/api/courses-catalog?q=cs%203100"])
def test_spaced_course_code_reaches_the_like_unspaced(monkeypatch, path):
    likes = _course_like_params(monkeypatch, path)
    assert likes and all("cs 3100" not in p for p in likes)
    assert any("cs3100" in p for p in likes)


def test_professor_search_keeps_its_spaces(monkeypatch):
    # Only course searches join: a professor query like "li 2" isn't a course code.
    assert server.search_text("cs 3100") == "cs 3100"


def _course_catalog(monkeypatch, qs, rows):
    seen = []
    monkeypatch.setattr(server, "query", lambda sql, params=(): seen.append(" ".join(sql.split())) or rows)
    monkeypatch.setattr(server, "query_one", lambda sql, params=(): {"cnt": len(rows)})
    monkeypatch.setattr(server, "data_version", lambda: 0)
    server._cache.clear()
    server.limiter.reset()
    resp = server.app.test_client().get("/api/courses-catalog?" + qs, headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200
    return resp.get_json(), seen


def test_course_catalog_rows_carry_the_rating_count(monkeypatch):
    row = {"code": "CS3100", "name": "PDI 2", "department": "Computer Science", "avg_rating": 3.456, "num_ratings": 41}
    out, _ = _course_catalog(monkeypatch, "", [row])
    assert out["courses"][0]["numRatings"] == 41


def test_course_catalog_has_a_most_rated_sort(monkeypatch):
    _, seen = _course_catalog(monkeypatch, "sort=ratings", [])
    assert any("ORDER BY num_ratings DESC NULLS LAST" in s for s in seen)
