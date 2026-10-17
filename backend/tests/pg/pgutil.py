"""Helpers shared by the PostgreSQL integration tests."""

import psycopg2.extras


def truncate(conn, *tables):
    """Empty `tables` (and anything referencing them), resetting identity counters."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
    conn.commit()


def rows(conn, sql, params=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        result = cur.fetchall()
    conn.commit()
    return result


def scalar(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        value = cur.fetchone()[0]
    conn.commit()
    return value


def query_fn(conn):
    """The (sql, params) -> list[dict] callable the rag/ modules take."""
    def q(sql, params=None):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    return q


def schema_snapshot(conn):
    """Columns, indexes and constraints of the public schema, for drift checks."""
    columns = rows(conn, """
        SELECT table_name, column_name, data_type, is_nullable, column_default, is_identity
        FROM information_schema.columns WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position""")
    indexes = rows(conn, """
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' ORDER BY indexname""")
    constraints = rows(conn, """
        SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS def
        FROM pg_constraint WHERE connamespace = 'public'::regnamespace
        ORDER BY conname""")
    return columns, indexes, constraints
