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
  python rag/clear_ask_strikes.py --delete-data <sub>          # data deletion: Ask standing (ban) stays
  python rag/clear_ask_strikes.py --delete-account <sub>       # account deletion: everything, ban included
  python rag/clear_ask_strikes.py --delete-data <sub> --dry-run

The account id (<sub>) is the JWT 'sub' (server.py:764) — the value used as session_token.
"""
import os, sys, time, argparse
from dotenv import load_dotenv
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rag.chat_abuse import STRIKE_STATUSES, account_data_counts, delete_account_data

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
URL = os.getenv("ORACLE_DATABASE_URL")
if not URL:
    sys.exit("Need ORACLE_DATABASE_URL in backend/.env")


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


def delete_for(conn, cur, account, keep_standing, dry_run):
    """keep_standing=True: a data deletion (questions and bookmarks go; the strikes that
    still count stay, text removed, so a ban survives). False: an account deletion
    (every row goes, any ban included)."""
    if dry_run:
        c = account_data_counts(cur, account)
        kept = c["live_strikes"] if keep_standing else 0
        print(f"[dry-run] would delete {c['ask_rows'] - kept} ask_log row(s) and "
              f"{c['bookmarks']} bookmark row(s) for {account!r}"
              + (f", keeping {kept} live strike(s) without their text" if kept else ""))
        return
    r = delete_account_data(cur, account, keep_standing)
    conn.commit()
    print(f"Deleted {r['deleted']} ask_log row(s) and {r['bookmarks_deleted']} bookmark row(s) "
          f"for {account!r}."
          + (f" Kept {r['kept_strikes']} live strike(s) without their text: Ask standing unchanged."
             if keep_standing else " Account removed, strikes and any ban included."))


def main():
    p = argparse.ArgumentParser(description="Inspect/clear ask_log abuse strikes or purge an account.")
    p.add_argument("--show", action="store_true")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--delete-data", metavar="SUB",
                   help="data deletion: delete the account's questions and bookmarks, keep its Ask standing")
    p.add_argument("--delete-account", metavar="SUB",
                   help="account deletion: delete every row for the account, strikes and any ban included")
    p.add_argument("--account", help="JWT sub / session_token of the account")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not (args.show or args.clear or args.delete_data or args.delete_account):
        p.error("pass --show, --clear, --delete-data or --delete-account")
    if args.clear and not args.account:
        p.error("--clear requires --account")

    conn = connect()
    cur = conn.cursor()
    if args.show:
        show(cur, args.account)
    if args.clear:
        clear(conn, cur, args.account, args.dry_run)
    if args.delete_data:
        delete_for(conn, cur, args.delete_data, True, args.dry_run)
    if args.delete_account:
        delete_for(conn, cur, args.delete_account, False, args.dry_run)
    cur.close(); conn.close()


if __name__ == "__main__":
    main()
