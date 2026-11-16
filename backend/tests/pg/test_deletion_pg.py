"""Data deletion keeps an Ask ban; account deletion removes it (chat_abuse.delete_account_data)."""

from rag.chat_abuse import DELETED_TEXT, abuse_check, delete_account_data
from tests.pg.pgutil import query_fn, rows, scalar, truncate

BANNED, OTHER = "user-banned", "user-other"


def seed(conn):
    truncate(conn, "ask_log", "bookmarks")
    with conn.cursor() as cur:
        # Six strikes this week: banned.
        for i in range(6):
            cur.execute("INSERT INTO ask_log (session_token, query, mode, result_status, answer_text, "
                        "professor_slug, created_at) VALUES (%s, %s, 'question', 'off_topic', 'no', "
                        "'guha', now() - %s * INTERVAL '1 hour')", (BANNED, f"strike {i}", i))
        # A strike that has aged out, an answered question, and a row with no created_at.
        cur.execute("INSERT INTO ask_log (session_token, query, mode, result_status, created_at) "
                    "VALUES (%s, 'old strike', 'question', 'off_topic', now() - INTERVAL '10 days')", (BANNED,))
        cur.execute("INSERT INTO ask_log (session_token, query, mode, result_status, answer_text) "
                    "VALUES (%s, 'is Guha hard', 'question', 'ok', 'fair')", (BANNED,))
        cur.execute("INSERT INTO ask_log (session_token, query, mode, result_status, created_at) "
                    "VALUES (%s, 'undated', 'question', 'ok', NULL)", (BANNED,))
        cur.execute("INSERT INTO ask_log (session_token, query, mode, result_status) "
                    "VALUES (%s, 'someone else', 'question', 'off_topic')", (OTHER,))
        for sub in (BANNED, OTHER):
            cur.execute("INSERT INTO bookmarks (user_sub, item_type, item_key) VALUES (%s, 'professor', 'guha')",
                        (sub,))
    conn.commit()


def query_one(conn):
    q = query_fn(conn)
    return lambda sql, params=None: (q(sql, params) or [None])[0]


def run(conn, keep_standing):
    with conn.cursor() as cur:
        result = delete_account_data(cur, BANNED, keep_standing)
    conn.commit()
    return result


def test_data_deletion_keeps_the_ban_but_not_the_text(pg):
    seed(pg)
    assert abuse_check(BANNED, query_one(pg))["banned"] is True
    result = run(pg, keep_standing=True)
    assert result == {"deleted": 3, "kept_strikes": 6, "bookmarks_deleted": 1}
    assert abuse_check(BANNED, query_one(pg))["banned"] is True
    kept = rows(pg, "SELECT query, answer_text, professor_slug, result_status FROM ask_log "
                    "WHERE session_token = %s", (BANNED,))
    assert len(kept) == 6
    assert all(r["query"] == DELETED_TEXT and r["answer_text"] is None and r["professor_slug"] is None
               and r["result_status"] == "off_topic" for r in kept)
    # Nobody else's rows are touched.
    assert scalar(pg, "SELECT count(*) FROM ask_log WHERE session_token = %s", (OTHER,)) == 1
    assert scalar(pg, "SELECT count(*) FROM bookmarks WHERE user_sub = %s", (OTHER,)) == 1


def test_account_deletion_removes_the_ban(pg):
    seed(pg)
    result = run(pg, keep_standing=False)
    assert result == {"deleted": 9, "kept_strikes": 0, "bookmarks_deleted": 1}
    assert scalar(pg, "SELECT count(*) FROM ask_log WHERE session_token = %s", (BANNED,)) == 0
    assert abuse_check(BANNED, query_one(pg)) == {"allowed": True, "banned": False, "message": None}
    assert scalar(pg, "SELECT count(*) FROM ask_log WHERE session_token = %s", (OTHER,)) == 1
