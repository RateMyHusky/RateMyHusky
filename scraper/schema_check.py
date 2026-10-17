"""Check that PostgreSQL already has the tables and columns a loader writes.

db/postgres/ is the single source of truth for the schema; the loaders never
create or alter a table there. Each loader still carries the sqlite-flavoured
DDL it uses for staging files and tests, so this module turns that DDL into the
columns it implies (`expected_columns`) and compares them with the live
database (`require_columns`), failing before any write when the schema lags.
"""

import sqlite3

APPLY_HINT = ("Apply db/postgres/02_tables.sql to a new database, or run the SQL "
              "under 'Schema changes since the migration' in db/postgres/README.md "
              "on an existing one.")


def sqlite_flavour(stmt):
    """The same rewrites the loaders make to run their PostgreSQL DDL on sqlite."""
    return (stmt.replace("TIMESTAMPTZ", "TIMESTAMP")
                .replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP"))


def expected_columns(ddl_statements, added_columns=()):
    """{table: [column, ...]} the DDL defines, in column order.

    `ddl_statements` are CREATE TABLE (and other) statements; they are applied to
    a throwaway in-memory sqlite database and read back with PRAGMA table_info.
    `added_columns` are (table, column, decl) triples a loader adds to older
    tables; they count as expected too.
    """
    conn = sqlite3.connect(":memory:")
    try:
        cur = conn.cursor()
        for stmt in ddl_statements:
            if stmt.strip():
                cur.execute(sqlite_flavour(stmt))
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        found = {t: [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
                 for t in tables}
    finally:
        conn.close()
    for table, column, _decl in added_columns:
        cols = found.setdefault(table, [])
        if column not in cols:
            cols.append(column)
    return found


def require_columns(pg_cur, expected):
    """Raise RuntimeError naming every expected table or column PostgreSQL lacks."""
    pg_cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'")
    have = {}
    for row in pg_cur.fetchall():
        have.setdefault(row[0], set()).add(row[1])
    missing_tables = sorted(t for t in expected if t not in have)
    missing_columns = sorted(f"{t}.{c}" for t, cols in expected.items() if t in have
                             for c in cols if c not in have[t])
    if not missing_tables and not missing_columns:
        return
    lines = ["the database schema is behind the code:"]
    if missing_tables:
        lines.append("  missing tables: " + ", ".join(missing_tables))
    if missing_columns:
        lines.append("  missing columns: " + ", ".join(missing_columns))
    lines.append(APPLY_HINT)
    raise RuntimeError("\n".join(lines))
