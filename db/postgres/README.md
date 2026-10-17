# PostgreSQL schema

The production database is PostgreSQL 16 with the pgvector extension, on an
Oracle Cloud VM (US East – Ashburn). These files are the schema's single source
of truth: the application and the loaders never create or alter tables on
PostgreSQL. `scraper/load_banner.py`, `scraper/match_banner_instructors.py` and
`scraper/load_catalog.py` check that the tables and columns they use exist
(`scraper/schema_check.py`) and stop with a list of what is missing; they only
create tables on the SQLite stage files and in tests. The one exception is
`backend/moderate_backfill.py`, which adds the `mod_*` columns when run, so
running it against production changes the schema; update `02_tables.sql` if you do.

| File | Run as | When |
|---|---|---|
| `00_extensions.sql` | `postgres` superuser | first (needs `postgresql-16-pgvector`) |
| `02_tables.sql` | `appuser` | before loading data — columns and primary keys only |
| `03_constraints.sql` | `appuser` | after loading data — indexes, unique indexes, CHECKs, the FK |
| `reset_sequences.sql` | `appuser` | after loading data — moves every identity counter past `max(id)` |

Fresh server, in order:

```bash
sudo -u postgres psql -d appdb -v ON_ERROR_STOP=1 -f 00_extensions.sql
psql "$PG_URL" -v ON_ERROR_STOP=1 -f 02_tables.sql
python backend/restore_db.py <dump.sql.gz> --all --yes   # or another data load
psql "$PG_URL" -v ON_ERROR_STOP=1 -f 03_constraints.sql
psql "$PG_URL" -f reset_sequences.sql
```

`backend/tests/pg/` applies 00, 02 and 03 to a scratch database on every run, so
a change here is exercised by the integration tests.

## Browsing the database from VS Code

Developers get their own login, sent privately along with the server address.
Never put either in a file in this repo.

| Login | Can do | Use it for |
|---|---|---|
| `reader` | `SELECT` only; every transaction is read-only and a query stops after 30 s | browsing data, writing and checking queries |
| `writer` | everything `appuser` can, including `ALTER` and `DROP` | data fixes you have agreed with the team |

Both are the production database. Start with `reader`, and connect as `writer`
only for the change you need to make. Schema changes still go through the SQL
files in this folder, not through edits made by hand in VS Code.

1. Install the **PostgreSQL** extension from Microsoft (`ms-ossdata.vscode-pgsql`).
2. Open the PostgreSQL view in the Activity Bar, hover over the **Connections**
   header and click **+** (**Add New Connection**). You can also run
   **PGSQL: Add New Connection** from the Command Palette.
3. On the **Parameters** tab, fill in:
   - **Server name**: the server address you were sent
   - **Authentication Type**: Password
   - **User name** and **Password**: your login. Tick **Save Password** if you like:
     VS Code keeps it in your operating system's credential manager, not in a
     settings file.
   - **Database name**: `appdb`. Left blank, the extension connects to a default
     database, and the server refuses every database except `appdb`.
   - **Connection Name**: anything, for example `RateMyHusky (reader)`
4. Click **Advanced** and set:
   - **Scope**: **User**. Workspace scope writes the connection to
     `.vscode/settings.json`, which is checked into this repo.
   - **Port**: `5432`
   - **SSL** section → **SSL mode**: **Require**. The server refuses connections
     without SSL.
5. Click **Test Connection**, then **Save & Connect**. Expand the connection in
   the **Connections** tree to browse the tables in the `public` schema, and
   right-click it to open a query editor.

You can paste a connection string into the **Connection String** tab instead:
`postgresql://<user>@<server>:5432/appdb?sslmode=require`. Leave the password out
and type it when VS Code prompts you. Even then, check under **Advanced** that
Scope is User and SSL mode is Require.

The extension's Copilot integration can run SQL over an open connection. Use it
over a `reader` connection, not `writer`.

If the connection fails:

- `no pg_hba.conf entry ... database "postgres"`: **Database name** is blank or
  wrong. Set it to `appdb`.
- `no pg_hba.conf entry ... no encryption`: SSL is off. Set **SSL mode** to **Require**.
- `password authentication failed`: the user name or password is wrong. Ask for
  your login to be checked or reset.
- `canceling statement due to statement timeout` (as `reader`): the query took
  longer than 30 s. Add a `LIMIT` or a narrower `WHERE`.

## Schema changes since the migration

The NUBanner teaching-history code added a table and five columns, and review
tags added three tables, after the production database was loaded. `02_tables.sql` already declares them (the
columns last in their tables, where `ADD COLUMN` puts them). A database loaded
before this needs the following, which the loaders no longer run for you. Run it
once at cutover:

```sql
CREATE TABLE IF NOT EXISTS public.banner_roster_duplicates (
    term_code TEXT NOT NULL,
    instructor_key TEXT NOT NULL,
    CONSTRAINT banner_roster_duplicates_pkey PRIMARY KEY (term_code, instructor_key)
);
ALTER TABLE public.banner_sections ADD COLUMN IF NOT EXISTS part_of_term TEXT;
ALTER TABLE public.banner_course_offerings
    ADD COLUMN IF NOT EXISTS summer1_years BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS summer2_years BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS first_term_label TEXT,
    ADD COLUMN IF NOT EXISTS offering_years TEXT;
CREATE TABLE IF NOT EXISTS public.review_tags (
    source TEXT NOT NULL,
    source_id BIGINT NOT NULL,
    tag TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT review_tags_pkey PRIMARY KEY (source, source_id, tag)
);
CREATE TABLE IF NOT EXISTS public.review_tags_processed (
    source TEXT NOT NULL,
    source_id BIGINT NOT NULL,
    taxonomy_version BIGINT NOT NULL DEFAULT 1,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT review_tags_processed_pkey PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS public.professor_tags (
    name_key TEXT NOT NULL,
    tag TEXT NOT NULL,
    review_count BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT professor_tags_pkey PRIMARY KEY (name_key, tag)
);
CREATE INDEX IF NOT EXISTS professor_tags_tag ON public.professor_tags (tag ASC, review_count DESC);
```

Until they run, the course-history query in `backend/teaching_history.py` fails
on the missing columns, the Banner loader and matcher stop at start-up naming
the missing table or column, and the tags routes and `pipeline.review_tags` fail
on the missing tag tables.

### Optional cleanup (destructive; take a backup first)

`02_tables.sql` no longer declares the old backup tables or the tables nothing
reads. Production does not need these drops to be compatible with the code; they
only remove dead tables, and they cannot be undone. After taking a backup:

```sql
DROP TABLE public.course_catalog_bak_20260803, public.professors_catalog_bak_20260803,
           public.prof_identity, public.prof_rmp_summary, public.prof_rmp_link,
           public.rating_meta;
```
