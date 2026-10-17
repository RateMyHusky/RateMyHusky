-- Run as the postgres superuser, NOT appuser:
--   sudo -u postgres psql -d appdb -v ON_ERROR_STOP=1 -f 00_extensions.sql
-- Requires the pgvector package: sudo apt install -y postgresql-16-pgvector
CREATE EXTENSION IF NOT EXISTS vector;
