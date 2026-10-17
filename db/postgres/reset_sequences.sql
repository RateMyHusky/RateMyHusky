-- Moves every identity counter past the highest existing value.
-- Run as appuser after the data load: psql "$PG_URL" -f reset_sequences.sql
SELECT format(
  'SELECT setval(pg_get_serial_sequence(%L, %L), COALESCE((SELECT MAX(%I) FROM %I), 0) + 1, false);',
  table_name, column_name, column_name, table_name
)
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (is_identity = 'YES' OR column_default LIKE 'nextval%')
\gexec
