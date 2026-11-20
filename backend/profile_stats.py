"""
Ops report: how many student profiles, page views and grad-year ratings have been collected.

USAGE (from backend/):
  python profile_stats.py                      # ratings counted since the earliest profile
  python profile_stats.py --since 2026-11-01

Reads ORACLE_DATABASE_URL from backend/.env through rag/clear_ask_strikes.connect().

Rule for any future public use of these numbers: a grad-year, course or professor
group is shown only once it has at least 10 ratings.
"""
import argparse
from datetime import datetime, timezone


def collect(query, since):
    """`query(sql, params=()) -> list[dict]`. `since=None` means no date filter on ratings."""
    one = lambda sql, params=(): query(sql, params)[0]
    profiles = one("SELECT count(*) AS n, count(*) FILTER (WHERE tracking_opt_out) AS opted_out, "
                   "count(*) FILTER (WHERE NOT tracking_opt_out) AS answered "
                   "FROM student_profiles")
    by_year = query(
        "SELECT CASE WHEN grad_year IS NULL THEN 'grad student' ELSE grad_year::text END AS k, "
        "count(*) AS n FROM student_profiles WHERE NOT tracking_opt_out GROUP BY k")
    by_major = query(
        "SELECT m AS k, count(*) AS n FROM student_profiles, unnest(majors) AS m "
        "WHERE NOT tracking_opt_out GROUP BY m")
    views = one("SELECT count(*) AS views, count(DISTINCT user_sub) AS students, "
                "count(DISTINCT item_key) FILTER (WHERE item_type = 'professor') AS professors, "
                "count(DISTINCT item_key) FILTER (WHERE item_type = 'course') AS courses "
                "FROM page_views")
    ratings = one("SELECT count(*) FILTER (WHERE rater_grad_year IS NOT NULL) AS with_year, "
                  "count(*) FILTER (WHERE rater_grad_year IS NULL) AS without_year "
                  "FROM survey_ratings WHERE (%s::timestamptz IS NULL OR created_at >= %s)",
                  (since, since))
    return {
        "profiles": profiles["n"], "opted_out": profiles["opted_out"],
        "answered": profiles["answered"],
        "by_grad_year": {r["k"]: r["n"] for r in by_year},
        "by_major": {r["k"]: r["n"] for r in by_major},
        "views": views["views"], "view_students": views["students"],
        "view_professors": views["professors"], "view_courses": views["courses"],
        "views_per_student": round(views["views"] / views["students"], 1) if views["students"] else 0,
        "since": since,
        "ratings_with_year": ratings["with_year"], "ratings_without_year": ratings["without_year"],
    }


def format_report(stats):
    lines = [f"profile rows (incl. opted out): {stats['profiles']}",
             f"answered profiles: {stats['answered']}", f"opted out: {stats['opted_out']}",
             "", "by grad year (opted out excluded):"]
    lines += [f"  {k}: {n}" for k, n in sorted(stats["by_grad_year"].items())]
    lines += ["", "by major (opted out excluded):"]
    lines += [f"  {k}: {n}" for k, n in sorted(stats["by_major"].items(), key=lambda kv: (-kv[1], kv[0]))]
    lines += ["", f"page views: {stats['views']}",
              f"distinct students: {stats['view_students']}",
              f"distinct professors: {stats['view_professors']}",
              f"distinct courses: {stats['view_courses']}",
              f"views per student: {stats['views_per_student']}",
              "", f"all submitted ratings (any status) since {stats['since'] or 'the start'}:",
              f"  with grad year: {stats['ratings_with_year']}",
              f"  without grad year: {stats['ratings_without_year']}"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Report student profile signal counts.")
    ap.add_argument("--since", help="YYYY-MM-DD; default is the earliest profile's created_at")
    args = ap.parse_args()

    from psycopg2.extras import RealDictCursor
    from rag.clear_ask_strikes import connect
    conn = connect()

    def query(sql, params=()):
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        since = query("SELECT min(created_at) AS m FROM student_profiles")[0]["m"]
    print(format_report(collect(query, since)))
    conn.close()


if __name__ == "__main__":
    main()
