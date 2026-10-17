"""
Local-only Flask admin app for viewing ask_log in the PostgreSQL database.

WHY: chat_abuse/chat_throttle logic is hard to reason about from raw SQL one-offs
(clear_ask_strikes.py). This gives a browsable view of ask_log — questions, users,
usage — without leaving the local machine. Never imported by server.py; not part
of any deploy path.

Reads ORACLE_DATABASE_URL from backend/.env, using the same DNS-retry connect()
as clear_ask_strikes.py.

Run: python backend/rag/ask_admin.py -> http://127.0.0.1:5051
"""
import os
import sys
import time
import uuid
import datetime
import os.path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rag.chat_abuse import STRIKE_STATUSES, _CAPS

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
URL = os.getenv("ORACLE_DATABASE_URL")
if not URL:
    sys.exit("Need ORACLE_DATABASE_URL in backend/.env")

ALL_STATUSES = (
    "ok", "ok_cached", "kill_switch", "rate_limited", "off_topic",
    "injection_blocked", "too_long", "gate_error", "ambiguous", "out_of_scope",
    "thin_data", "llm_error", "validation_failed",
)

app = Flask(__name__)


def connect(attempts=20):
    last = None
    for i in range(1, attempts + 1):
        try:
            return psycopg2.connect(URL, sslmode="require", options="-c timezone=UTC")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e):
                raise
            last = str(e)
            print(f"  DNS lookup flaked; retrying ({i}/{attempts})...")
            time.sleep(3)
    sys.exit(f"Could not resolve the database host after {attempts} attempts.\n{last}")


conn = connect()


def _serialize(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _recover(exc):
    """On any psycopg2 exception, leave `conn` usable again before the caller
    retries: for a dead connection (Operational/InterfaceError), reconnect;
    otherwise the connection is alive but its transaction is aborted, so just
    roll it back (itself wrapped in case the connection died some other way)."""
    global conn
    if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        conn = connect()
        return
    try:
        conn.rollback()
    except psycopg2.Error:
        conn = connect()


def query(sql, params=()):
    """Run a SELECT with %s params, returning a list of dicts. On any
    psycopg2 error, recovers the shared connection (rollback, or reconnect if
    it died) and retries once."""
    global conn
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except psycopg2.Error as e:
        _recover(e)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [{k: _serialize(v) for k, v in dict(row).items()} for row in rows]


def execute(sql, params=()):
    """Run a write statement with %s params, committing. On any psycopg2
    error, recovers the shared connection (rollback, or reconnect if it died)
    and retries once. Returns the row count."""
    global conn
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rowcount = cur.rowcount
        conn.commit()
    except psycopg2.Error as e:
        _recover(e)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rowcount = cur.rowcount
        conn.commit()
    return rowcount


def ladder_state(strikes_7d):
    """OK / WARNED / CAPPED(n) / BANNED per chat_abuse.abuse_check's ladder."""
    if strikes_7d >= 6:
        return "BANNED"
    if strikes_7d >= 3:
        return f"CAPPED({_CAPS[min(strikes_7d, 5)]})"
    if strikes_7d >= 1:
        return "WARNED"
    return "OK"


@app.route("/")
def index():
    html_path = os.path.join(os.path.dirname(__file__), "ask_admin.html")
    if not os.path.exists(html_path):
        return "ask_admin.html not built yet", 200
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200


@app.route("/api/logs")
def api_logs():
    where = []
    params = []

    date_from = request.args.get("from")
    date_to = request.args.get("to")
    if date_from:
        where.append("created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("created_at < %s::date + INTERVAL '1 day'")
        params.append(date_to)

    user = request.args.get("user")
    if user:
        where.append("session_token = %s")
        params.append(user)

    status = request.args.get("status")
    if status:
        statuses = [s for s in status.split(",") if s]
        if statuses:
            where.append("result_status = ANY(%s)")
            params.append(statuses)

    flagged = request.args.get("flagged")
    if flagged is not None and flagged != "":
        where.append("flagged = %s")
        params.append(flagged.lower() == "true")

    q = request.args.get("q")
    if q:
        where.append("query ILIKE %s")
        params.append(f"%{q}%")

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", 50))
    except ValueError:
        page_size = 50
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    try:
        total_rows = query(f"SELECT count(*) AS c FROM ask_log {where_sql}", params)
        total = total_rows[0]["c"] if total_rows else 0

        rows = query(
            f"SELECT * FROM ask_log {where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
    except (psycopg2.errors.InvalidTextRepresentation, psycopg2.errors.InvalidDatetimeFormat, psycopg2.DataError):
        return jsonify({"rows": [], "total": 0})

    return jsonify({"rows": rows, "total": total})


def _date_range_where(alias=""):
    """Build the from/to WHERE clause pieces for /api/users, same semantics as /api/logs."""
    col = f"{alias}created_at" if alias else "created_at"
    where = []
    params = []
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    if date_from:
        where.append(f"{col} >= %s")
        params.append(date_from)
    if date_to:
        where.append(f"{col} < %s::date + INTERVAL '1 day'")
        params.append(date_to)
    return where, params


@app.route("/api/users")
def api_users():
    where, params = _date_range_where()
    where.append("session_token IS NOT NULL")
    where_sql = f"WHERE {' AND '.join(where)}"

    try:
        rows = query(
            f"""
            SELECT
                session_token,
                count(*) AS total,
                count(*) FILTER (WHERE result_status IN ('ok', 'ok_cached')) AS ok_count,
                count(*) FILTER (WHERE result_status = ANY(%s)) AS strike_count_range,
                coalesce(sum(tokens_used), 0) AS tokens_used,
                max(created_at) AS last_seen,
                array_agg(DISTINCT ip_hash) FILTER (WHERE ip_hash IS NOT NULL) AS ip_hashes
            FROM ask_log
            {where_sql}
            GROUP BY session_token
            """,
            [list(STRIKE_STATUSES)] + params,
        )

        strikes_rows = query(
            "SELECT session_token, count(*) AS c FROM ask_log "
            "WHERE session_token IS NOT NULL AND result_status = ANY(%s) "
            "AND created_at > now() - INTERVAL '7 days' "
            "GROUP BY session_token",
            (list(STRIKE_STATUSES),),
        )
    except (psycopg2.errors.InvalidTextRepresentation, psycopg2.errors.InvalidDatetimeFormat, psycopg2.DataError):
        return jsonify({"rows": []})

    strikes_7d_by_token = {r["session_token"]: r["c"] for r in strikes_rows}

    for row in rows:
        strikes_7d = strikes_7d_by_token.get(row["session_token"], 0)
        row["strikes_7d"] = strikes_7d
        row["state"] = ladder_state(strikes_7d)

    rows.sort(key=lambda r: (r["strikes_7d"], r["total"]), reverse=True)

    return jsonify({"rows": rows})


@app.route("/api/users/<sub>")
def api_user_detail(sub):
    breakdown = query(
        "SELECT result_status, count(*) AS c, min(created_at) AS first, max(created_at) AS last "
        "FROM ask_log WHERE session_token = %s GROUP BY result_status ORDER BY c DESC",
        (sub,),
    )

    today_rows = query(
        "SELECT count(*) AS c FROM ask_log WHERE session_token = %s AND mode = 'question' "
        "AND created_at >= date_trunc('day', now())",
        (sub,),
    )
    questions_today = today_rows[0]["c"] if today_rows else 0

    strikes_rows = query(
        "SELECT count(*) AS c FROM ask_log WHERE session_token = %s AND result_status = ANY(%s) "
        "AND created_at > now() - INTERVAL '7 days'",
        (sub, list(STRIKE_STATUSES)),
    )
    strikes_7d = strikes_rows[0]["c"] if strikes_rows else 0

    return jsonify({
        "session_token": sub,
        "breakdown": breakdown,
        "questions_today": questions_today,
        "strikes_7d": strikes_7d,
        "state": ladder_state(strikes_7d),
    })


def _dry_run_from_body():
    """Fail safe: dry-run unless the body carries an explicit JSON boolean false."""
    body = request.get_json(silent=True) or {}
    return body.get("dry_run") is not False


@app.route("/api/users/<sub>/clear_strikes", methods=["POST"])
def api_clear_strikes(sub):
    dry_run = _dry_run_from_body()
    if dry_run:
        rows = query(
            "SELECT count(*) AS c FROM ask_log WHERE session_token = %s AND result_status = ANY(%s)",
            (sub, list(STRIKE_STATUSES)),
        )
        return jsonify({"deleted": rows[0]["c"] if rows else 0})

    n = execute(
        "DELETE FROM ask_log WHERE session_token=%s AND result_status = ANY(%s)",
        (sub, list(STRIKE_STATUSES)),
    )
    return jsonify({"deleted": n})


@app.route("/api/users/<sub>/purge", methods=["POST"])
def api_purge(sub):
    dry_run = _dry_run_from_body()
    if dry_run:
        rows = query("SELECT count(*) AS c FROM ask_log WHERE session_token = %s", (sub,))
        brows = query("SELECT count(*) AS c FROM bookmarks WHERE user_sub = %s", (sub,))
        return jsonify({"deleted": rows[0]["c"] if rows else 0,
                        "bookmarks_deleted": brows[0]["c"] if brows else 0})

    n = execute("DELETE FROM ask_log WHERE session_token=%s", (sub,))
    nb = execute("DELETE FROM bookmarks WHERE user_sub=%s", (sub,))
    return jsonify({"deleted": n, "bookmarks_deleted": nb})


def _num_groq_keys():
    keys = os.getenv("GROQ_API_KEYS")
    if not keys:
        return 0
    return len([k for k in keys.split(",") if k.strip()])


@app.route("/api/usage")
def api_usage():
    where, params = _date_range_where()
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    day_rows = query(
        f"""
        SELECT
            date_trunc('day', created_at) AS day,
            result_status,
            count(*) AS c,
            coalesce(sum(tokens_used), 0) AS tokens,
            avg(response_ms) FILTER (WHERE result_status = 'ok') AS avg_response_ms
        FROM ask_log
        {where_sql}
        GROUP BY day, result_status
        """,
        params,
    )

    # Per-day distinct users must be counted over the whole day; summing the
    # per-(day,status) groups would double-count a user seen under 2+ statuses.
    user_rows = query(
        f"""
        SELECT
            date_trunc('day', created_at) AS day,
            count(DISTINCT session_token) FILTER (WHERE session_token IS NOT NULL) AS unique_users
        FROM ask_log
        {where_sql}
        GROUP BY day
        """,
        params,
    )
    users_by_day = {r["day"]: r["unique_users"] for r in user_rows}

    days_by_date = {}
    for row in day_rows:
        d = days_by_date.setdefault(row["day"], {
            "date": row["day"],
            "statuses": {},
            "tokens": 0,
            "avg_response_ms": None,
            "unique_users": users_by_day.get(row["day"], 0),
        })
        d["statuses"][row["result_status"]] = row["c"]
        d["tokens"] += row["tokens"]
        if row["result_status"] == "ok":
            d["avg_response_ms"] = float(row["avg_response_ms"]) if row["avg_response_ms"] is not None else None

    days = sorted(days_by_date.values(), key=lambda d: d["date"])

    num_keys = _num_groq_keys()
    daily_budget = 80 * num_keys if num_keys else None
    token_ceiling = 200_000 * num_keys if num_keys else None

    today_row = query(
        "SELECT "
        "count(*) FILTER (WHERE result_status = 'ok') AS ok_count, "
        "coalesce(sum(tokens_used), 0) AS tokens "
        "FROM ask_log WHERE created_at >= date_trunc('day', now())"
    )
    ok_count = today_row[0]["ok_count"] if today_row else 0
    today_tokens = today_row[0]["tokens"] if today_row else 0

    minute_row = query(
        "SELECT extract(hour FROM now())::int * 60 + extract(minute FROM now())::int AS m"
    )
    minute_of_day = minute_row[0]["m"] if minute_row else 0
    projection = None
    if minute_of_day >= 30:
        projection = int((ok_count / minute_of_day) * 1440)

    top_users_where = where + ["session_token IS NOT NULL"]
    top_users = query(
        f"""
        SELECT session_token, count(*) FILTER (WHERE result_status = 'ok') AS ok_count
        FROM ask_log
        WHERE {' AND '.join(top_users_where)}
        GROUP BY session_token
        ORDER BY ok_count DESC
        LIMIT 10
        """,
        params,
    )

    status_totals = query(
        f"SELECT result_status, count(*) AS c FROM ask_log {where_sql} GROUP BY result_status ORDER BY c DESC",
        params,
    )

    return jsonify({
        "days": days,
        "today": {
            "ok_count": ok_count,
            "daily_budget": daily_budget,
            "tokens": today_tokens,
            "token_ceiling": token_ceiling,
            "projection": projection,
        },
        "top_users": top_users,
        "status_totals": status_totals,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5051, debug=False)
