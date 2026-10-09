"""DDL for the source tables (spec §5.1). Idempotent.

    python -m pipeline.schema            # print the statements
    python -m pipeline.schema --apply    # run them; back up first (python backup_db.py)

catalog_courses / catalog_nupath are created by scraper/load_catalog_to_crdb.py.
"""

import argparse

from .db import connect

SOURCE_SUMMARY_DDL = """
CREATE TABLE {name} (
  professor_slug       TEXT NOT NULL DEFAULT '',
  course_code          TEXT NOT NULL DEFAULT '',
  source               TEXT NOT NULL,
  rating               FLOAT,
  difficulty           FLOAT,
  would_take_again_pct FLOAT,
  num_ratings          INT NOT NULL DEFAULT 0,
  num_comments         INT NOT NULL DEFAULT 0,
  hours_per_week       FLOAT,
  rating_distribution  JSONB,
  grade_distribution   JSONB,
  PRIMARY KEY (professor_slug, course_code, source),
  INDEX source_summary_course (course_code, professor_slug),
  CHECK (professor_slug <> '' OR course_code <> '')
)"""

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS professors (
      slug        TEXT PRIMARY KEY,
      name        TEXT NOT NULL,
      name_key    TEXT NOT NULL,
      department  TEXT,
      college     TEXT,
      image_url   TEXT,
      focus_x     FLOAT, focus_y FLOAT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      INDEX professors_name_key (name_key)
    )""",
    """CREATE TABLE IF NOT EXISTS rmp_links (
      rmp_id          INT8 PRIMARY KEY,
      rmp_name        TEXT NOT NULL,
      rmp_department  TEXT,
      professor_url   TEXT NOT NULL,
      slug            TEXT NOT NULL,
      match_method    TEXT NOT NULL CHECK (match_method IN ('frozen','exact','manual')),
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      INDEX rmp_links_slug (slug)
    )""",
    SOURCE_SUMMARY_DDL.format(name="IF NOT EXISTS source_summary"),
    "ALTER TABLE rmp_reviews ADD COLUMN IF NOT EXISTS course_code TEXT",
    "CREATE INDEX IF NOT EXISTS idx_rr_course_code ON rmp_reviews (course_code)",
    # review tags (pipeline/review_tags.py)
    """CREATE TABLE IF NOT EXISTS review_tags (
      source      TEXT NOT NULL,
      source_id   INT8 NOT NULL,
      tag         TEXT NOT NULL,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (source, source_id, tag)
    )""",
    # so reviews that got no tags don't get checked again every run
    """CREATE TABLE IF NOT EXISTS review_tags_processed (
      source        TEXT NOT NULL,
      source_id     INT8 NOT NULL,
      processed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (source, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS professor_tags (
      name_key      TEXT NOT NULL,
      tag           TEXT NOT NULL,
      review_count  INT NOT NULL DEFAULT 0,
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (name_key, tag),
      INDEX professor_tags_tag (tag, review_count DESC)
    )""",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    if not args.apply:
        for sql in STATEMENTS:
            print(sql.strip() + ";\n")
        print("dry run: nothing executed")
        return 0
    conn = connect()
    cur = conn.cursor()
    for sql in STATEMENTS:
        cur.execute(sql)
        conn.commit()
    print(f"applied {len(STATEMENTS)} statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
