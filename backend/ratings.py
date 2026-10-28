"""Injectable SQL layer for the no-login rating form.

Pure functions that take `query`/`query_one` (read) and `write` (execute+commit,
never fetches) so they can be unit-tested without a live DB. server.py wires
these to the real helpers and owns all HTTP concerns. Every `now` is a
timezone-aware UTC datetime.
"""

import uuid
from datetime import datetime, timedelta, timezone

import rating_checks
from prof_aliases import rmp_link_key

# The burst thresholds count prior ratings in the window: the route counts before it saves.
PAIR_BURST = 5  # prior new-device ratings for one professor + course in an hour
PAIR_PACE_FACTOR = 3  # ...and this many times the pair's 30-day mean hourly count
PROF_BURST = 10  # prior ratings for one professor in an hour, any device or course; same pace factor
COURSE_BURST = 20  # prior ratings for one course in an hour, any professor or device; same pace factor
PROF_DAY_BURST = 30  # prior ratings for one professor in a day, no pace factor: a steady drip can't raise it
BURST_PAUSE_HOURS = 72  # a burst still awaiting review holds every new rating in its scope this long
IP_BURST = 10  # prior ratings from one IP hash in an hour
PREFIX_BURST = 25  # prior ratings from one /24 or /64 hash in an hour
COUNTER_MIN = 25  # the "huskies this term" counter is hidden below this
IP_HASH_DAYS = 30
NEAR_DUPLICATE_DAYS = 30  # how far back a comment can be a near copy of one on the same professor
# skew_week thresholds are starting values to tune against real traffic.
SKEW_DAYS = 7  # the window of new-device ratings for one professor
SKEW_MIN_RATINGS = 8  # at least this many in it, counting the new one
SKEW_DROP = 1.5  # ...averaging this far below the professor's blended mean
SKEW_MAX_STDEV = 1.0  # ...and agreeing this tightly (population stdev)
TERM_START_MONTHS = (1, 5, 9)

# Every survey_ratings column except created_at / updated_at.
RATING_COLUMNS = (
    "id", "professor_slug", "pending_professor_id", "course_code",
    "pending_course_id", "term_label", "rating", "hours", "grade", "comment",
    "comment_hash", "status", "hold_reasons", "device_hash", "new_device",
    "ip_hash", "ip_prefix_hash", "network_type", "fill_seconds", "collection", "difficulty",
)

_KEY_COLUMNS = ("professor_slug", "pending_professor_id", "course_code", "pending_course_id")
_KEY_MATCH = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in _KEY_COLUMNS)
_PROF_MATCH = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in _KEY_COLUMNS[:2])
_COURSE_MATCH = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in _KEY_COLUMNS[2:])
_NO_NETWORK_BURST = ("campus", "relay")
# Shared networks: one abusive student must not silence the rest of campus, a relay,
# or a carrier, which shares IPv4 addresses across many subscribers.
FLAG_EXEMPT_NETWORKS = (*_NO_NETWORK_BURST, "mobile")
_BURST_REASONS = ("burst_pair", "burst_prof", "burst_prof_day", "burst_course", "burst_ip", "burst_prefix")
# A held row from a pair burst pauses that pair; a professor or course burst, all of it.
_PAUSE_SQL = (
    "SELECT 1 FROM survey_ratings WHERE status = 'held' AND updated_at >= %s AND ("
    f"(string_to_array(hold_reasons, ',') && ARRAY['burst_pair'] AND {_KEY_MATCH}) OR "
    f"(string_to_array(hold_reasons, ',') && ARRAY['burst_prof', 'burst_prof_day'] AND {_PROF_MATCH}) OR "
    f"(string_to_array(hold_reasons, ',') && ARRAY['burst_course'] AND {_COURSE_MATCH})) LIMIT 1"
)


def term_start(now):
    """The latest Jan 1 / May 1 / Sep 1 00:00 UTC at or before `now`."""
    month = max(m for m in TERM_START_MONTHS if m <= now.month)
    return datetime(now.year, month, 1, tzinfo=timezone.utc)


def huskies_this_term(query_one, now):
    """Ratings submitted this term (accepted and held), or None below COUNTER_MIN."""
    row = query_one("SELECT count(*) AS cnt FROM survey_ratings WHERE created_at >= %s",
                    (term_start(now),))
    count = row["cnt"] if row else 0
    return count if count >= COUNTER_MIN else None


def professor_exists(slug, query_one):
    return query_one("SELECT 1 FROM professors_catalog WHERE slug = %s", (slug,)) is not None


def course_exists(code, query_one):
    """In the catalog, in Banner, or approved since the last pipeline run rebuilt the catalog."""
    for sql in ("SELECT 1 FROM course_catalog WHERE code = %s",
                "SELECT 1 FROM banner_course_offerings WHERE subject_course = %s",
                "SELECT 1 FROM survey_pending_courses WHERE code = %s AND status = 'approved'"):
        if query_one(sql, (code,)) is not None:
            return True
    return False


# Banner has the professor teaching the course, RMP has reviews of them in it, or a
# reviewer approved a rating held as unverified_pair (an approval keeps its hold_reasons).
# A professor or course approved from the form is in neither source, so that approval is
# the only way its pairs become taught. {code} and {slug} are SQL expressions.
TAUGHT_SQL = (
    "(EXISTS (SELECT 1 FROM banner_course_instructors WHERE subject_course = {code} AND professor_slug = {slug}) "
    "OR EXISTS (SELECT 1 FROM source_summary WHERE course_code = {code} AND professor_slug = {slug} "
    "AND source = 'rmp') "
    "OR EXISTS (SELECT 1 FROM survey_ratings WHERE course_code = {code} AND professor_slug = {slug} "
    "AND status = 'accepted' AND string_to_array(hold_reasons, ',') @> ARRAY['unverified_pair']))"
)


def pair_taught(slug, code, query_one):
    row = query_one(f"SELECT {TAUGHT_SQL.format(code='%s', slug='%s')} AS taught", (code, slug) * 3)
    return bool(row and row["taught"])


# The insert is a no-op when a pending row already exists: a partial unique index
# allows one pending row per name_key / code, so two racing submits share one row.
def pending_professor(name, department, query_one, write):
    """(id, created): reuse a pending row with the same name_key as professors use, else insert."""
    name_key = rmp_link_key(name)[0]
    new_id = str(uuid.uuid4())
    write("INSERT INTO survey_pending_professors (id, name, name_key, department) "
          "VALUES (%s, %s, %s, %s) ON CONFLICT (name_key) WHERE status = 'pending' DO NOTHING",
          (new_id, name, name_key, department))
    row = query_one(
        "SELECT id FROM survey_pending_professors WHERE name_key = %s AND status = 'pending'",
        (name_key,))
    return str(row["id"]), str(row["id"]) == new_id


def pending_course(code, name, query_one, write):
    """(id, created): reuse a pending row with the same code, else insert."""
    new_id = str(uuid.uuid4())
    write("INSERT INTO survey_pending_courses (id, code, name) VALUES (%s, %s, %s) "
          "ON CONFLICT (code) WHERE status = 'pending' DO NOTHING", (new_id, code, name))
    row = query_one(
        "SELECT id FROM survey_pending_courses WHERE code = %s AND status = 'pending'", (code,))
    return str(row["id"]), str(row["id"]) == new_id


def rating_key(clean, pending_professor_id, pending_course_id):
    """The four columns that, with the device, identify one rating."""
    return {
        "professor_slug": None if pending_professor_id else clean.get("professor_slug"),
        "pending_professor_id": pending_professor_id,
        "course_code": None if pending_course_id else clean.get("course_code"),
        "pending_course_id": pending_course_id,
    }


def _key_params(key):
    return tuple(key[c] for c in _KEY_COLUMNS)


def existing_rating(device_hash, key, query_one):
    return query_one(
        f"SELECT id, status, hold_reasons FROM survey_ratings WHERE device_hash = %s AND {_KEY_MATCH}",
        (device_hash, *_key_params(key)))


def device_seen(device_hash, query_one):
    """True when this device already has a rating, so its token isn't one a client made up."""
    return query_one("SELECT 1 FROM survey_ratings WHERE device_hash = %s LIMIT 1", (device_hash,)) is not None


def duplicate_comment(comment_hash, exclude_id, query_one):
    """True when another rating already carries this comment hash."""
    if comment_hash is None:
        return False
    row = query_one(
        "SELECT 1 FROM survey_ratings WHERE comment_hash = %s AND id IS DISTINCT FROM %s LIMIT 1",
        (comment_hash, exclude_id))
    return row is not None


def near_duplicate_ids(comment, key, exclude_id, query, now):
    """Ids of the professor's ratings from the last NEAR_DUPLICATE_DAYS whose comment
    is a near copy of this one, held and accepted alike. Any course: a template gets
    reused across a professor's courses. Short comments never match."""
    if len(rating_checks.normalize_comment(comment or "")) < rating_checks.MIN_DUPLICATE_CHARS:
        return []
    rows = query(
        f"SELECT id, comment FROM survey_ratings WHERE {_PROF_MATCH} AND created_at >= %s "
        "AND comment IS NOT NULL AND id IS DISTINCT FROM %s",
        (*_key_params(key)[:2], now - timedelta(days=NEAR_DUPLICATE_DAYS), exclude_id))
    mine = rating_checks.shingles(comment)
    return [str(r["id"]) for r in rows
            if rating_checks.shingle_similarity(mine, rating_checks.shingles(r["comment"]))
            >= rating_checks.NEAR_DUPLICATE]


def _add_reason(reason, condition, params, write):
    """Add `reason` to the held rows matching `condition` that don't list it. The
    agent's escalate predates the new reason, so it is cleared for a re-review; a
    reject stays, since only a human clears one. Doesn't bump updated_at, which the
    burst windows count."""
    write(
        "UPDATE survey_ratings SET hold_reasons = hold_reasons || %s, "
        "agent_decision = CASE WHEN agent_decision = 'reject' THEN agent_decision END, "
        "agent_reason = CASE WHEN agent_decision = 'reject' THEN agent_reason END, "
        "agent_reviewed_at = CASE WHEN agent_decision = 'reject' THEN agent_reviewed_at END "
        "WHERE status = 'held' AND hold_reasons IS NOT NULL "
        f"AND NOT (%s = ANY(string_to_array(hold_reasons, ','))) AND {condition}",
        ("," + reason, reason, *params))


def hold_matches(ids, reason, write):
    """Hold the accepted rows among `ids` for `reason`, and add it to held rows that
    don't list it. A row a reviewer approved keeps its hold_reasons, so
    `hold_reasons IS NULL` leaves approvals alone. All on one professor, whose
    page the route already drops, so there is nothing to return."""
    if not ids:
        return
    write(
        "UPDATE survey_ratings SET status = 'held', hold_reasons = %s "
        "WHERE status = 'accepted' AND hold_reasons IS NULL AND id::text = ANY(%s)",
        (reason, ids))
    _add_reason(reason, "id::text = ANY(%s)", (ids,), write)


# The week's new-device ratings as count, sum and sum of squares. A row a reviewer
# approved keeps its hold_reasons, so it is left out and can't re-trip the check.
_SKEW_WEEK_SQL = (
    "SELECT count(*) AS n, COALESCE(sum(rating), 0) AS total, "
    "COALESCE(sum(rating * rating), 0) AS squares FROM survey_ratings "
    f"WHERE {_PROF_MATCH} AND new_device = true AND created_at >= %s "
    "AND NOT (status = 'accepted' AND hold_reasons IS NOT NULL)")


def skew_week(key, rating, new_device, query_one, now):
    """True when the professor's last SKEW_DAYS of new-device ratings, with this one,
    are at least SKEW_MIN_RATINGS, average SKEW_DROP below the professor's
    blended mean (professors_catalog.avg_rating, so RMP carries it in the first
    weeks) and have a population stdev under SKEW_MAX_STDEV: a slow drip the
    hourly bursts miss. Approved rows don't count: a reviewer-approved week would
    otherwise re-trip on every later rating. A returning device, a pending
    professor and a professor with no prior make no check."""
    if not new_device or not key["professor_slug"]:
        return False
    week = query_one(_SKEW_WEEK_SQL, (*_key_params(key)[:2], now - timedelta(days=SKEW_DAYS)))
    n = (week["n"] if week else 0) + 1
    if n < SKEW_MIN_RATINGS:
        return False
    prior = query_one("SELECT avg_rating FROM professors_catalog WHERE slug = %s", (key["professor_slug"],))
    if not prior or prior["avg_rating"] is None:
        return False
    # sum(bigint) is a Decimal and avg_rating a float, so convert before mixing them.
    total, squares = float(week["total"]) + rating, float(week["squares"]) + rating * rating
    mean = total / n
    variance = max(squares / n - mean * mean, 0)
    return prior["avg_rating"] - mean >= SKEW_DROP and variance ** 0.5 < SKEW_MAX_STDEV


def hold_skew_week(key, write, now):
    """Hold the professor's unreviewed new-device ratings from the last SKEW_DAYS
    for skew_week, and add it to held ones the agent could otherwise approve one by
    one on a soft flag, so it groups them. A row held for an escalate-only reason or
    carrying the agent's reject goes to a human anyway, so it stays out of the group.
    All on one professor, whose page the route already drops, so there is nothing
    to return."""
    condition = f"new_device = true AND created_at >= %s AND {_PROF_MATCH}"
    params = (now - timedelta(days=SKEW_DAYS), *_key_params(key)[:2])
    write(
        "UPDATE survey_ratings SET status = 'held', hold_reasons = 'skew_week' "
        f"WHERE status = 'accepted' AND hold_reasons IS NULL AND {condition}",
        params)
    _add_reason(
        "skew_week",
        f"{condition} AND string_to_array(hold_reasons, ',') <@ %s::text[] "
        "AND agent_decision IS DISTINCT FROM 'reject'",
        (*params, sorted(rating_checks.APPROVABLE | rating_checks.APPROVABLE_IF_VARIED)), write)


def _paced(row, hour, month, limit):
    """At least `limit` in the hour and PAIR_PACE_FACTOR times the 30-day mean hourly count."""
    return row[hour] >= limit and row[hour] >= PAIR_PACE_FACTOR * row[month] / 720


def burst_reasons(key, ip_hash, prefix_hash, network_type, query_one, now):
    """Which of the burst triggers, or burst_pause, this submission trips.

    burst_prof and burst_course count every device on every network: devices that
    rated something else first, invented course codes, and one course spread over
    many professors all get past the pair count. burst_prof_day has no pace factor,
    so a drip just under the hourly limit can't raise its own ceiling. Every window
    is on updated_at, so a wave of edits to old ratings counts like new ones.
    """
    hour_ago, month_ago = now - timedelta(hours=1), now - timedelta(days=30)
    kp = _key_params(key)
    reasons = []
    # One scan of the professor's month covers the pair, hourly and daily counts.
    prof = query_one(
        "SELECT count(*) FILTER (WHERE updated_at >= %s) AS hour, count(*) AS month, "
        "count(*) FILTER (WHERE updated_at >= %s) AS day, "
        f"count(*) FILTER (WHERE new_device = true AND updated_at >= %s AND {_COURSE_MATCH}) AS pair_hour, "
        f"count(*) FILTER (WHERE new_device = true AND {_COURSE_MATCH}) AS pair_month "
        f"FROM survey_ratings WHERE updated_at >= %s AND {_PROF_MATCH}",
        (hour_ago, now - timedelta(days=1), hour_ago, *kp[2:], *kp[2:], month_ago, *kp[:2]))
    course = query_one(
        "SELECT count(*) FILTER (WHERE updated_at >= %s) AS hour, count(*) AS month "
        f"FROM survey_ratings WHERE updated_at >= %s AND {_COURSE_MATCH}",
        (hour_ago, month_ago, *kp[2:]))
    if prof and _paced(prof, "pair_hour", "pair_month", PAIR_BURST):
        reasons.append("burst_pair")
    if prof and _paced(prof, "hour", "month", PROF_BURST):
        reasons.append("burst_prof")
    if course and _paced(course, "hour", "month", COURSE_BURST):
        reasons.append("burst_course")
    if prof and prof["day"] >= PROF_DAY_BURST:
        reasons.append("burst_prof_day")
    if query_one(_PAUSE_SQL, (now - timedelta(hours=BURST_PAUSE_HOURS), *kp, *kp[:2], *kp[2:])):
        reasons.append("burst_pause")
    if network_type not in _NO_NETWORK_BURST:
        for reason, column, value, limit in (
            ("burst_ip", "ip_hash", ip_hash, IP_BURST),
            ("burst_prefix", "ip_prefix_hash", prefix_hash, PREFIX_BURST),
        ):
            if value is None:
                continue
            row = query_one(
                f"SELECT count(*) AS cnt FROM survey_ratings WHERE {column} = %s AND updated_at >= %s",
                (value, hour_ago))
            if row and row["cnt"] >= limit:
                reasons.append(reason)
    return reasons


def hold_burst(reasons, key, ip_hash, prefix_hash, write, now):
    """Hold the accepted rows in each tripped trigger's window (a day for
    burst_prof_day, else the last hour) that match it; return the professor
    slugs of the rows it held, whose pages must drop them.

    burst_pair holds only new-device rows, the ones burst_reasons counts. A row a
    reviewer approved keeps its hold_reasons, so `hold_reasons IS NULL` leaves
    approvals alone. burst_ip and burst_prefix hold rows for any professor.
    burst_pause holds only the new rating, so it isn't listed here.
    """
    kp = _key_params(key)
    where = {
        "burst_pair": (f"new_device = true AND {_KEY_MATCH}", kp),
        "burst_prof": (_PROF_MATCH, kp[:2]),
        "burst_prof_day": (_PROF_MATCH, kp[:2]),
        "burst_course": (_COURSE_MATCH, kp[2:]),
        "burst_ip": ("ip_hash = %s", (ip_hash,)),
        "burst_prefix": ("ip_prefix_hash = %s", (prefix_hash,)),
    }
    held = set()
    for reason in _BURST_REASONS:
        if reason not in reasons:
            continue
        condition, params = where[reason]
        since = now - (timedelta(days=1) if reason == "burst_prof_day" else timedelta(hours=1))
        rows = write(
            "UPDATE survey_ratings SET status = 'held', hold_reasons = %s "
            "WHERE status = 'accepted' AND hold_reasons IS NULL AND updated_at >= %s "
            f"AND {condition} RETURNING professor_slug",
            (reason, since, *params))
        held.update(r["professor_slug"] for r in rows or () if r["professor_slug"])
    return held


# The conflict target (device_hash + the four key columns) is never updated;
# status has its own held-stays-held rule below, and a clean resubmit keeps the
# row's hold_reasons, so a reviewer's approval stays out of the burst and surge
# counts. new_device keeps its first value, so an edit can't take a row out of
# the burst_pair count. A page still on the form from before the difficulty
# question sends none, so an edit from it keeps the stored difficulty (temporary,
# see rating_checks.validate_submission).
_INSERT_COLUMNS = tuple(c for c in RATING_COLUMNS if c != "id")
_SET_COLUMNS = tuple(
    c for c in _INSERT_COLUMNS
    if c not in ("status", "hold_reasons", "device_hash", "new_device", "difficulty", *_KEY_COLUMNS))
_UPSERT_SQL = (
    f"INSERT INTO survey_ratings (id, {', '.join(_INSERT_COLUMNS)}) "
    f"VALUES (%s, {', '.join(['%s'] * len(_INSERT_COLUMNS))}) "
    "ON CONFLICT (device_hash, professor_slug, pending_professor_id, course_code, "
    "pending_course_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _SET_COLUMNS)
    + ", status = CASE WHEN survey_ratings.status = 'held' THEN 'held' ELSE EXCLUDED.status END"
    ", hold_reasons = COALESCE(EXCLUDED.hold_reasons, survey_ratings.hold_reasons)"
    ", difficulty = COALESCE(EXCLUDED.difficulty, survey_ratings.difficulty)"
    ", updated_at = now()"
)


def save_rating(row, existing, write):
    """Insert or replace this device's rating in one statement; return its id.

    The unique index on (device, key) is the conflict target, so two racing
    submits still leave one row, and a held row stays held. A resubmit adds the
    new hold reasons to the old ones, or keeps the old ones when it has none.
    """
    if existing and existing["hold_reasons"] and row["hold_reasons"]:
        old = existing["hold_reasons"].split(",")
        row = {**row, "hold_reasons": ",".join(
            old + [r for r in row["hold_reasons"].split(",") if r not in old])}
    new_id = str(uuid.uuid4())
    write(_UPSERT_SQL, (new_id, *(row[c] for c in _INSERT_COLUMNS)))
    return existing["id"] if existing else new_id


def professor_context(slug, device_hash, query):
    """The form's course step: this device's earlier answers per rated course.

    A course still awaiting review comes back as `pending`, so the form resends it
    as a new course and the submit reuses its pending row instead of adding a rating.

    Accepted risk: the answers, comment included, go to whoever holds the device token,
    so the next person on a shared browser sees them. That person could already
    overwrite the rating, since the device is the identity.
    """
    if device_hash is None:
        return {"ratedCourses": []}
    rows = query(
        "SELECT COALESCE(r.course_code, pc.code) AS code, COALESCE(c.name, pc.name) AS name, "
        "r.course_code IS NULL AS pending, r.term_label, r.rating, r.difficulty, r.hours, r.grade, r.comment "
        "FROM survey_ratings r LEFT JOIN course_catalog c ON c.code = r.course_code "
        "LEFT JOIN survey_pending_courses pc ON pc.id = r.pending_course_id AND pc.status = 'pending' "
        "WHERE r.device_hash = %s AND r.professor_slug = %s "
        "AND (r.course_code IS NOT NULL OR pc.id IS NOT NULL) "
        "ORDER BY code", (device_hash, slug))
    return {"ratedCourses": [
        {"code": r["code"], "name": r["name"], "pending": r["pending"], "term": r["term_label"],
         "rating": r["rating"], "difficulty": r["difficulty"], "hours": r["hours"], "grade": r["grade"],
         "comment": r["comment"] or ""} for r in rows]}


def flagged(device_hash, ip_hash, network_type, query_one, now):
    """Whether a reviewer flagged this device (for good) or this IP (for IP_HASH_DAYS,
    never on a shared network: campus, relay or mobile)."""
    sql = "SELECT 1 FROM rating_flags WHERE (kind = 'device' AND value_hash = %s)"
    params = [device_hash]
    if ip_hash and network_type not in FLAG_EXEMPT_NETWORKS:
        sql += " OR (kind = 'ip' AND value_hash = %s AND created_at >= %s)"
        params += [ip_hash, now - timedelta(days=IP_HASH_DAYS)]
    return query_one(sql + " LIMIT 1", tuple(params)) is not None


def purge_ip_hashes(write, now):
    """Clear IP and prefix hashes, and IP flags, once they are older than IP_HASH_DAYS."""
    cutoff = now - timedelta(days=IP_HASH_DAYS)
    write("UPDATE survey_ratings SET ip_hash = NULL, ip_prefix_hash = NULL "
          "WHERE created_at < %s AND ip_hash IS NOT NULL", (cutoff,))
    write("DELETE FROM rating_flags WHERE kind = 'ip' AND created_at < %s", (cutoff,))
