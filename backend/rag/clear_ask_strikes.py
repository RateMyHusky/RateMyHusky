"""
One-off ops script: inspect and clear ask_log abuse strikes.

WHY: the abuse ladder (chat_abuse.py) treats classifier fail-closed results and
false-positives as 'strikes'. Accumulated strikes cap/ban an account on the daily
question limit even when no real question ever went through. This script lets you
see the strike rows per account and clear them for a specific account.

Reads ORACLE_DATABASE_URL from backend/.env and wraps connect() in a DNS-retry
loop. Never prints the connection string.

USAGE (from backend/):
  python rag/clear_ask_strikes.py --show                       # list strikes per account
  python rag/clear_ask_strikes.py --show --account <sub>       # detail for one account
  python rag/clear_ask_strikes.py --clear  --account <sub>     # delete that account's strike rows
  python rag/clear_ask_strikes.py --clear  --account <sub> --dry-run
  python rag/clear_ask_strikes.py --purge-account <sub>        # delete ALL of one account's rows (data-erasure)
  python rag/clear_ask_strikes.py --purge-account <sub> --dry-run

The account id (<sub>) is the JWT 'sub' (server.py:764) — the value used as session_token.
"""
import os, sys, time, argparse
from dotenv import load_dotenv
import psycopg2

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
URL = os.getenv("ORACLE_DATABASE_URL")
if not URL:
    sys.exit("Need ORACLE_DATABASE_URL in backend/.env")

STRIKE_STATUSES = ("injection_blocked", "off_topic", "defamation_framing")


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


def show(cur, account=None):
    if account:
        cur.execute(
            "SELECT result_status, count(*) AS c, min(created_at) AS first, max(created_at) AS last "
            "FROM ask_log WHERE session_token = %s AND result_status = ANY(%s) "
            "GROUP BY result_status ORDER BY c DESC",
            (account, list(STRIKE_STATUSES)))
        rows = cur.fetchall()
        total = sum(r[1] for r in rows)
        print(f"\nAccount {account!r}: {total} strike(s) "
              f"({'BANNED' if total >= 6 else 'CAPPED' if total >= 3 else 'clear'})")
        for status, c, first, last in rows:
            print(f"  {status:20} {c:4}   first={first}  last={last}")
        # also show today's question count (what the daily cap measures against)
        cur.execute(
            "SELECT count(*) FROM ask_log WHERE session_token = %s AND mode = 'question' "
            "AND date_trunc('day', created_at) = current_date", (account,))
        print(f"  questions logged today: {cur.fetchone()[0]}")
        return

    cur.execute(
        "SELECT session_token, count(*) AS c FROM ask_log WHERE result_status = ANY(%s) "
        "GROUP BY session_token ORDER BY c DESC LIMIT 50",
        (list(STRIKE_STATUSES),))
    print("\n=== strikes per account (top 50; >=3 capped, >=6 banned) ===")
    for tok, c in cur.fetchall():
        flag = "BANNED" if c >= 6 else "CAPPED" if c >= 3 else ""
        print(f"  {tok!r:42} {c:4}  {flag}")


def clear(conn, cur, account, dry_run):
    cur.execute(
        "SELECT count(*) FROM ask_log WHERE session_token = %s AND result_status = ANY(%s)",
        (account, list(STRIKE_STATUSES)))
    n = cur.fetchone()[0]
    if dry_run:
        print(f"[dry-run] would delete {n} strike row(s) for {account!r}")
        return
    cur.execute(
        "DELETE FROM ask_log WHERE session_token = %s AND result_status = ANY(%s)",
        (account, list(STRIKE_STATUSES)))
    conn.commit()
    print(f"Deleted {cur.rowcount} strike row(s) for {account!r}. Account is now clear.")


def purge_account(conn, cur, account, dry_run):
    """Data-erasure: delete EVERY ask_log row for one account (query text, answer_text,
    ip_hash, all statuses) — not just strikes — plus the account's bookmarks. Use for a
    user's 'remove my tracked data' request. Also resets that account's strikes/daily-cap
    as a side effect."""
    cur.execute("SELECT count(*) FROM ask_log WHERE session_token = %s", (account,))
    n = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM bookmarks WHERE user_sub = %s", (account,))
    nb = cur.fetchone()[0]
    if dry_run:
        print(f"[dry-run] would delete ALL {n} ask_log row(s) and {nb} bookmark row(s) "
              f"for {account!r}")
        return
    cur.execute("DELETE FROM ask_log WHERE session_token = %s", (account,))
    n_deleted = cur.rowcount
    cur.execute("DELETE FROM bookmarks WHERE user_sub = %s", (account,))
    conn.commit()
    print(f"Deleted {n_deleted} ask_log row(s) and {cur.rowcount} bookmark row(s) for "
          f"{account!r}. All tracked data for this account is removed.")


def main():
    p = argparse.ArgumentParser(description="Inspect/clear ask_log abuse strikes or purge an account.")
    p.add_argument("--show", action="store_true")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--purge-account", metavar="SUB",
                   help="delete ALL ask_log rows for this account (data-erasure, not just strikes)")
    p.add_argument("--account", help="JWT sub / session_token of the account")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not (args.show or args.clear or args.purge_account):
        p.error("pass --show, --clear, or --purge-account")
    if args.clear and not args.account:
        p.error("--clear requires --account")

    conn = connect()
    cur = conn.cursor()
    if args.show:
        show(cur, args.account)
    if args.clear:
        clear(conn, cur, args.account, args.dry_run)
    if args.purge_account:
        purge_account(conn, cur, args.purge_account, args.dry_run)
    cur.close(); conn.close()


if __name__ == "__main__":
    main()
