-- Indexes, unique indexes, CHECK constraints and foreign keys.
-- Run as appuser AFTER the data load:
--   psql "$PG_URL" -v ON_ERROR_STOP=1 -f 03_constraints.sql
-- INVERTED INDEX on TSVECTOR columns -> GIN index.
-- The final VALIDATE CONSTRAINT line from CockroachDB is unnecessary:
-- PostgreSQL validates the foreign key when it is added.

-- ask_log
CREATE INDEX al_session ON public.ask_log (session_token ASC, created_at DESC);
CREATE INDEX al_status  ON public.ask_log (result_status ASC, created_at DESC);
CREATE INDEX al_created ON public.ask_log (created_at DESC);

-- bookmarks
CREATE UNIQUE INDEX bookmarks_user_sub_item_type_item_key_key ON public.bookmarks (user_sub, item_type, item_key);
CREATE INDEX idx_bookmarks_user ON public.bookmarks (user_sub ASC, created_at DESC);
ALTER TABLE public.bookmarks ADD CONSTRAINT check_item_type CHECK (item_type IN ('professor', 'course'));

-- evidence
CREATE INDEX ev_tsv    ON public.evidence USING GIN (body_tsv);
CREATE INDEX ev_prof   ON public.evidence (professor_slug);
CREATE INDEX ev_course ON public.evidence (course_code);
CREATE UNIQUE INDEX ev_dedupe ON public.evidence (source, source_ref, professor_slug, course_code);

-- professor_photos
CREATE UNIQUE INDEX uq_professor_photos ON public.professor_photos (name, source_page);

-- professor_tags
CREATE INDEX professor_tags_tag ON public.professor_tags (tag ASC, review_count DESC);

-- professor_teaching
CREATE INDEX pt_slug ON public.professor_teaching (professor_slug);

-- reddit_mentions
CREATE INDEX rm_slug     ON public.reddit_mentions (professor_slug);
CREATE INDEX rm_name_key ON public.reddit_mentions (name_key);

-- reddit_sentiment
CREATE INDEX rs_slug ON public.reddit_sentiment (professor_slug);

-- reddit_text
CREATE INDEX rt_tsv ON public.reddit_text USING GIN (body_tsv);

-- rmp_professors
CREATE UNIQUE INDEX uq_rmp_professors ON public.rmp_professors (name, department);

-- rmp_reviews
CREATE INDEX idx_rr_name_key    ON public.rmp_reviews (name_key);
CREATE INDEX idx_rr_course_code ON public.rmp_reviews (course_code);
-- NOTE: PostgreSQL limits a single B-tree index entry to roughly 2.7 KB.
-- If any review comment is very long, this line fails with
-- "index row size ... exceeds btree version 4 maximum". Production's rows fit today.
-- If it fails, find the rows with
--   SELECT id, length(comment) FROM public.rmp_reviews WHERE length(comment) > 2000;
-- An md5(comment) expression index is not a drop-in fix: load_rmp.py's
-- ON CONFLICT (professor_name, course, date, comment) needs this exact column list.
CREATE UNIQUE INDEX uq_rmp_reviews ON public.rmp_reviews (professor_name, course, date, comment);

-- banner_sections
CREATE INDEX bsec_course ON public.banner_sections (subject_course);

-- banner_section_instructors
CREATE INDEX bsi_instructor ON public.banner_section_instructors (instructor_key);

-- banner_course_instructors
CREATE INDEX bci_slug ON public.banner_course_instructors (professor_slug);

-- professors
CREATE INDEX professors_name_key ON public.professors (name_key);

-- rmp_links
CREATE INDEX rmp_links_slug ON public.rmp_links (slug);
ALTER TABLE public.rmp_links ADD CONSTRAINT check_match_method
    CHECK (match_method IN ('frozen', 'exact', 'manual'));

-- catalog_courses
CREATE INDEX cc_subject    ON public.catalog_courses (subject);
CREATE INDEX cc_department ON public.catalog_courses (department);
CREATE INDEX cc_real       ON public.catalog_courses (is_placeholder);

-- catalog_nupath
CREATE INDEX cn_attribute ON public.catalog_nupath (attribute);

-- professors_catalog
CREATE INDEX idx_pc_name_key ON public.professors_catalog (name_key);
CREATE INDEX idx_pc_college  ON public.professors_catalog (college);
CREATE INDEX idx_pc_dept     ON public.professors_catalog (department);

-- course_catalog
CREATE INDEX idx_cc_dept ON public.course_catalog (department);

-- source_summary
CREATE INDEX source_summary_course ON public.source_summary (course_code, professor_slug);
ALTER TABLE public.source_summary ADD CONSTRAINT check_professor_slug_course_code
    CHECK ((professor_slug <> '') OR (course_code <> ''));

-- Foreign keys
ALTER TABLE public.evidence_embeddings
    ADD CONSTRAINT evidence_embeddings_evidence_id_fkey
    FOREIGN KEY (evidence_id) REFERENCES public.evidence (id) ON DELETE CASCADE;
