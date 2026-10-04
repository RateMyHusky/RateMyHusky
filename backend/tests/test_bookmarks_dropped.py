"""A bookmark whose professor left the roster is omitted, not an error."""

import datetime

import bookmarks


def test_bookmarks_for_dropped_professors_are_omitted():
    created = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)

    def query(sql, params):
        if "FROM bookmarks" in sql:
            return [{"item_type": "professor", "item_key": "kept", "created_at": created},
                    {"item_type": "professor", "item_key": "dropped", "created_at": created}]
        if "FROM professors_catalog" in sql:
            return [{"name": "Kept", "slug": "kept", "department": "CS", "college": "Khoury",
                     "avg_rating": 4.0, "rmp_rating": 4.0, "total_reviews": 3, "total_comments": 1,
                     "would_take_again_pct": None, "image_url": None, "focus_x": None, "focus_y": None}]
        return []

    out = bookmarks.list_bookmarks("user", query)
    assert [p["slug"] for p in out["professors"]] == ["kept"]
