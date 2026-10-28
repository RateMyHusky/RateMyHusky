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
tags added three tables, after the production database was loaded; the term-track
colleges added `banner_course_instructors.instructor_keys`. `02_tables.sql` already declares them (the
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
ALTER TABLE public.banner_course_instructors ADD COLUMN IF NOT EXISTS instructor_keys TEXT;
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
ALTER TABLE public.professors ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'rmp';
```

Banner-only professors record which source first created each professor in `professors.origin` (`'rmp'`, `'banner'`, or `'survey'`, created by `review_ratings.py approve-professor`). It is never updated, so a Banner-created professor that later gains an RMP link keeps `'banner'`. Run the ALTER before deploying: without the column the new `pipeline.run` fails at the Banner insert, after `apply_roster` has already committed.

Until they run, the course-history query in `backend/teaching_history.py` fails
on the missing columns, the Banner loader and matcher stop at start-up naming
the missing table or column, and the tags routes and `pipeline.review_tags` fail
on the missing tag tables.

The student rating form added three tables: `survey_ratings`, plus
`survey_pending_professors` and `survey_pending_courses` for professors and
courses a student typed in that aren't in the catalog yet. `02_tables.sql` and
`03_constraints.sql` declare them. Run this once before deploying. The CHECKs use
plain `ADD CONSTRAINT`, which has no `IF NOT EXISTS`, so a second run fails on the
first CHECK that already exists. `NULLS NOT DISTINCT` needs PostgreSQL 15 or later.

Deploy order:

1. Run the SQL below as `appuser` (or after `SET ROLE appuser`) with
   `psql -1 -v ON_ERROR_STOP=1`. The `ADD CONSTRAINT` lines aren't rerunnable
   after a partial failure.
2. Confirm `PROXY_SECRET`, `TURNSTILE_SECRET_KEY` and `OPENAI_API_KEY` are set on
   Railway. Without `PROXY_SECRET` every student shares Vercel's edge address, so
   the IP bursts add up across everyone and ratings get held. `OPENAI_API_KEY`
   runs on OpenAI's free tier, which in practice allows about 3,300 tokens a day
   (see the top of `backend/moderation.py`). Don't bulk-test against it: while it's empty,
   every rating with a comment is held as `moderation_unavailable`.
3. Set `IPINFO_TOKEN`.
4. Set `RATING_SECRET` last. Until it's set, the rating routes return 503.

```sql
CREATE TABLE IF NOT EXISTS public.survey_ratings (
    id UUID NOT NULL,
    professor_slug TEXT NULL,
    pending_professor_id UUID NULL,
    course_code TEXT NULL,
    pending_course_id UUID NULL,
    term_label TEXT NULL,
    rating BIGINT NOT NULL,
    hours TEXT NOT NULL,
    grade TEXT NULL,
    comment TEXT NULL,
    comment_hash TEXT NULL,
    status TEXT NOT NULL,
    hold_reasons TEXT NULL,
    device_hash TEXT NOT NULL,
    new_device BOOLEAN NOT NULL,
    ip_hash TEXT NULL,
    ip_prefix_hash TEXT NULL,
    network_type TEXT NOT NULL,
    fill_seconds BIGINT NULL,
    collection TEXT NOT NULL DEFAULT 'turnstile+device',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT survey_ratings_pkey PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS public.survey_pending_professors (
    id UUID NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    department TEXT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_slug TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT survey_pending_professors_pkey PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS public.survey_pending_courses (
    id UUID NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_code TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT survey_pending_courses_pkey PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS survey_ratings_pair    ON public.survey_ratings (professor_slug, course_code);
CREATE INDEX IF NOT EXISTS survey_ratings_created ON public.survey_ratings (created_at);
CREATE INDEX IF NOT EXISTS survey_ratings_ip      ON public.survey_ratings (ip_hash);
CREATE INDEX IF NOT EXISTS survey_ratings_prefix  ON public.survey_ratings (ip_prefix_hash);
CREATE INDEX IF NOT EXISTS survey_ratings_comment ON public.survey_ratings (comment_hash);
CREATE UNIQUE INDEX IF NOT EXISTS survey_ratings_one_per_device ON public.survey_ratings
    (device_hash, professor_slug, pending_professor_id, course_code, pending_course_id) NULLS NOT DISTINCT;
ALTER TABLE public.survey_ratings ADD CONSTRAINT check_survey_rating CHECK (rating BETWEEN 1 AND 5);
ALTER TABLE public.survey_ratings ADD CONSTRAINT check_survey_status CHECK (status IN ('accepted', 'held'));
ALTER TABLE public.survey_ratings ADD CONSTRAINT check_survey_professor
    CHECK (professor_slug IS NOT NULL OR pending_professor_id IS NOT NULL);
ALTER TABLE public.survey_ratings ADD CONSTRAINT check_survey_course
    CHECK (course_code IS NOT NULL OR pending_course_id IS NOT NULL);
CREATE INDEX IF NOT EXISTS survey_pending_professors_key ON public.survey_pending_professors (name_key);
CREATE UNIQUE INDEX IF NOT EXISTS survey_pending_professors_one_pending ON public.survey_pending_professors (name_key)
    WHERE status = 'pending';
ALTER TABLE public.survey_pending_professors ADD CONSTRAINT check_survey_pending_professor_status
    CHECK (status IN ('pending', 'approved', 'merged', 'rejected'));
CREATE INDEX IF NOT EXISTS survey_pending_courses_code ON public.survey_pending_courses (code);
CREATE UNIQUE INDEX IF NOT EXISTS survey_pending_courses_one_pending ON public.survey_pending_courses (code)
    WHERE status = 'pending';
ALTER TABLE public.survey_pending_courses ADD CONSTRAINT check_survey_pending_course_status
    CHECK (status IN ('pending', 'approved', 'merged', 'rejected'));
```

If the three tables already exist, run just the two partial unique indexes
before deploying. They allow one pending row per name key and per course code,
and the rating route's `ON CONFLICT` needs them, so without them every rating
for a new professor or course fails. Both are rerunnable:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS survey_pending_professors_one_pending ON public.survey_pending_professors (name_key)
    WHERE status = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS survey_pending_courses_one_pending ON public.survey_pending_courses (code)
    WHERE status = 'pending';
```

The form's difficulty question added one nullable column. Run this before
deploying the backend that asks it, or every rating fails on the missing
column. Ratings from before stay NULL and don't count toward the average.
Both are rerunnable:

```sql
ALTER TABLE public.survey_ratings ADD COLUMN IF NOT EXISTS difficulty BIGINT NULL;
DO $$ BEGIN
    ALTER TABLE public.survey_ratings ADD CONSTRAINT check_survey_difficulty CHECK (difficulty BETWEEN 1 AND 5);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

Flagging abusive raters added the `rating_flags` table. Run this as `appuser`
(or after `SET ROLE appuser`), since the table's owner otherwise lacks access
and every `/api/rate` call fails. Run it before deploying the backend that
reads it, or every rating fails on the missing table. Both are rerunnable:

```sql
CREATE TABLE IF NOT EXISTS public.rating_flags (
    kind TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, value_hash)
);
DO $$ BEGIN
    ALTER TABLE public.rating_flags ADD CONSTRAINT check_rating_flag_kind CHECK (kind IN ('device', 'ip'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

The daily review agent added three nullable columns to each of `survey_ratings`,
`survey_pending_professors` and `survey_pending_courses`. The rate form keeps
working without them, but `review_agent.py`, `review_ratings.py list` and the
digest need them, so run this before deploying. The block is rerunnable:

```sql
ALTER TABLE public.survey_ratings
    ADD COLUMN IF NOT EXISTS agent_decision TEXT NULL,
    ADD COLUMN IF NOT EXISTS agent_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS agent_reviewed_at TIMESTAMPTZ NULL;
ALTER TABLE public.survey_pending_professors
    ADD COLUMN IF NOT EXISTS agent_decision TEXT NULL,
    ADD COLUMN IF NOT EXISTS agent_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS agent_reviewed_at TIMESTAMPTZ NULL;
ALTER TABLE public.survey_pending_courses
    ADD COLUMN IF NOT EXISTS agent_decision TEXT NULL,
    ADD COLUMN IF NOT EXISTS agent_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS agent_reviewed_at TIMESTAMPTZ NULL;
DO $$ BEGIN
    ALTER TABLE public.survey_ratings ADD CONSTRAINT check_survey_agent_decision
        CHECK (agent_decision IN ('approve', 'escalate', 'reject'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE public.survey_pending_professors ADD CONSTRAINT check_survey_pending_professor_agent_decision
        CHECK (agent_decision IN ('merge', 'escalate'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE public.survey_pending_courses ADD CONSTRAINT check_survey_pending_course_agent_decision
        CHECK (agent_decision IN ('merge', 'escalate'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

To undo a wrong flag, run `DELETE FROM rating_flags WHERE kind = 'device' AND value_hash = '...'`
(or `kind = 'ip'`). The hash is the rejected rating's `device_hash` (`ip_hash` for an
IP), which `reject-rating --abuse` deletes with the row, so a reviewer should note it
from the held row before rejecting.

### Optional cleanup (destructive; take a backup first)

`02_tables.sql` no longer declares the old backup tables or the tables nothing
reads. Production does not need these drops to be compatible with the code; they
only remove dead tables, and they cannot be undone. After taking a backup:

```sql
DROP TABLE public.course_catalog_bak_20260803, public.professors_catalog_bak_20260803,
           public.prof_identity, public.prof_rmp_summary, public.prof_rmp_link,
           public.rating_meta;
```
