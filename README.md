<div align="center">

<img src="frontend/public/neu-husky-icon.png" alt="RateMyHusky" width="90" />

# RateMyHusky

**Find the right professor, every semester.**

RateMyProfessors ratings, Reddit chatter, and Northeastern's course schedule for 3,800+ Northeastern professors — searchable and comparable in one place.

[![Live Site](https://img.shields.io/badge/Live-ratemyhusky.com-e63946?style=for-the-badge)](https://ratemyhusky.com)
[![React](https://img.shields.io/badge/React_19-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)](frontend)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](frontend)
[![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)](backend)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](#architecture)

[**Visit the site**](https://ratemyhusky.com) · [Features](#features) · [Architecture](#architecture) · [Getting Started](#getting-started)

<img src="frontend/public/ratemyhusky.png" alt="RateMyHusky" width="850" />

</div>

---

## Why RateMyHusky?

Choosing classes at Northeastern means juggling RateMyProfessors tabs and Reddit threads — each with a fragment of the picture. RateMyHusky unifies both, along with Northeastern's own course schedule, into a single profile per professor, then layers search and comparison on top. An AI question-answering mode is paused while it's being improved, and an on-site rating form is in testing.

| Source | Scale |
|---|---|
| RateMyProfessors | 43K+ ratings & reviews |
| Reddit (r/NEU and beyond) | ~9K verified professor mentions, sentiment-scored |
| Northeastern course schedule (NUBanner) | Who taught each course, every term since Fall 2021 |
| Northeastern course catalog | Course descriptions, credits, and NUpath attributes |
| Northeastern teaching awards | Award badges, each linked to its announcement |
| Professor profiles | 3,800+ professors, ~2,000 photos, courses they're reviewed for or taught |

## Features

### Explore
- **Professor catalog** — filter by college, department, rating, and review volume
- **Rich profile pages** — RMP ratings and department comparison, grade distributions, review feeds from RMP and Reddit with review tags, teaching award badges, and the courses and terms each professor taught
- **Schedule-built pages** — most instructors on the course schedule since Fall 2021 get a page even with no ratings yet
- **Course catalog** — course detail pages with ratings, catalog descriptions, when the course is offered, and who taught it each term
- **Department pages** — every department's professors in one place
- **Side-by-side compare** — stack any professors against each other
- **GOATED leaderboard** — top-rated professors by college
- **Search that keeps up** — instant autocomplete across professors and courses, plus a shuffle wheel for serendipity

### Ask (AI, paused)

Ask is turned off while it's being improved: `ASK_ENABLED` in `frontend/src/config.ts` and `CHAT_ENABLED` on the backend.

- **Ask a real question** — *"Is Rachlin a fair grader?"* — and get a cited, single-shot answer grounded in actual student reviews
- **Hybrid retrieval** — full-text search + 384-dim [BGE-small](https://huggingface.co/BAAI/bge-small-en-v1.5) embeddings fused with Reciprocal Rank Fusion over review excerpts from RMP and Reddit
- **Citations that jump** — every cited snippet pins, scrolls to, and highlights its source on the professor page
- **Guardrailed** — prompt-injection gate, topic classifier, output validation, per-user abuse strikes, adaptive rate limiting, and answer caching

### Account
- **Bookmarks** — one-click bookmark toggle on professor and course cards/profiles, backed by a global bookmarks context for instant, optimistic updates
- **Bookmarks page** — `/bookmarks` lists all bookmarked professors and courses, reusing the catalog's card layout
- Signed-out bookmark clicks prompt Google sign-in instead of failing silently

### Rate (in testing)
- **Student rating form** — `/rate` takes a professor and course rating with an optional comment, no sign-in needed, behind a Turnstile checkpoint; an accepted rating moves the professor page's numbers right away, while every comment, held ratings and new professors or courses are reviewed before they publish
- Live on dev (Vercel Preview) and locally only; `RATE_ENABLED` in `frontend/src/config.ts` hides it in production

### Polished throughout
- Dark mode, responsive layout, breadcrumb navigation
- Google OAuth sign-in for gated functionality
- FAQ for students and professors, and a Feedback tab for bug reports, data corrections, and professor removal requests
- Precomputed catalog aggregates and prerendered pages for fast loads and SEO

## Architecture

```mermaid
flowchart LR
    U["Student"] --> SPA["React 19 SPA on Vercel"]
    SPA --> API["Flask API on Railway<br/>catalog, profiles, compare, bookmarks"]
    API --> ASK["Ask pipeline: gate, hybrid retrieval, synthesis, validation"]
    API -. "sign-in redirect" .-> OAUTH["Google OAuth 2.0"]
    ASK --> AI["Groq LLMs and ONNX BGE-small embeddings"]
    API --> DB[("PostgreSQL 16 + pgvector<br/>Oracle Cloud VM")]
    ASK --> DB

    SCRAPE["Scrapers: RMP, Reddit, NUBanner schedule, NEU catalog"] --> INGEST["Match, score, dedupe"]
    INGEST --> PRECOMP["precompute - rebuilds the catalog tables the API reads"]
    PRECOMP --> EMBED["Evidence build + BGE-small embedding backfill"]
    PRECOMP --> DB
    EMBED --> DB
```

**AI stack:** Groq-hosted Llama 3.1 8B as the input gate/classifier, GPT-OSS-120B for answer synthesis, and BGE-small-en-v1.5 (INT8 ONNX, pure `onnxruntime` no torch) for query/document embeddings.

### Main technologies

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, React Router |
| Backend | Python, Flask, Flask-CORS, Flask-Limiter |
| Database | PostgreSQL 16 + pgvector (psycopg2), self-hosted on an Oracle Cloud VM |
| AI / Retrieval | Groq (Llama 3.1 8B, GPT-OSS-120B), ONNX Runtime, BGE-small-en-v1.5, RRF hybrid retrieval |
| Auth | Google OAuth 2.0, JWT |
| Data pipeline | Python scrapers, professor-mention matching, sentiment scoring, embedding backfill |
| Hosting | Vercel (frontend) · Railway (backend) |

### Repository layout

```text
.
├── frontend/                  # React 19 + TypeScript SPA (Vercel)
│   └── src/
│       ├── pages/             #   Homepage, catalogs, profiles, departments,
│       │   │                  #   compare, bookmarks, FAQ, legal pages
│       │   └── rate/          #   /rate student rating form steps
│       ├── components/        #   SearchBar (+ Ask mode), breadcrumbs,
│       │                      #   BookmarkButton, FeedbackTab, Navbar, ...
│       ├── context/           #   AuthContext, BookmarksContext
│       ├── api/               #   Typed backend client
│       ├── config.ts          #   Feature flags (ASK_ENABLED, RATE_ENABLED, ...)
│       └── utils/             #   Ask session persistence, citation pinning
├── backend/                   # Flask API (Railway)
│   ├── server.py              #   Routes, auth, connection pool
│   ├── bookmarks.py           #   Bookmark add/remove/list (pure functions)
│   ├── ratings.py             #   Rating form SQL layer
│   ├── pipeline/              #   Rebuilds everything the site reads
│   ├── rag/                   #   Ask pipeline: gate, retrieve, answer,
│   │   │                      #   validate, cache, throttle, abuse,
│   │   │                      #   ONNX BGE-small query embeddings
│   │   └── eval/              #   Retrieval eval sets + RAG metrics
│   └── Better_Scraper/        #   RMP scrapers + CSV outputs
├── db/postgres/               # PostgreSQL schema
├── extension/                 # Chrome extension popup (early shell)
└── scraper/                   # Reddit, NUBanner schedule, NEU catalog,
                               # evidence/embedding pipeline
```

## Getting Started

### Prerequisites

- Python 3.8+ · Node.js 18+ · a reachable PostgreSQL 16 database with the pgvector extension (schema in [`db/postgres/`](db/postgres))

### Backend

```bash
pip install -r backend/requirements.txt
```

Create `backend/.env`:

```env
# The value is a PostgreSQL URL (the database runs on an Oracle Cloud VM).
ORACLE_DATABASE_URL=postgresql://appuser:<password>@<host>:5432/appdb?sslmode=require
JWT_SECRET=<generate-with-openssl-rand-hex-32>

# Optional — Google OAuth login flow
GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
GOOGLE_CLIENT_SECRET=<your-google-oauth-client-secret>
FRONTEND_URL=http://localhost:5173

# Optional — browser extension. Load extension/dist at chrome://extensions and
# copy the id it shows. Unset means no extension can reach the API.
EXTENSION_ORIGINS=chrome-extension://<your-unpacked-extension-id>

# Optional — AI Ask mode (off unless CHAT_ENABLED=true)
CHAT_ENABLED=true
GROQ_API_KEYS=<key1>,<key2>

# Optional — student rating form. The rating routes return 503 until
# RATING_SECRET (at least 32 characters) is set.
RATING_SECRET=<generate-with-openssl-rand-hex-32>
# Professor pages show /rate comments only when true. Turn on with the
# frontend's RATE_ENABLED at launch.
SHOW_STUDENT_REVIEWS=false
IPINFO_TOKEN=<ipinfo-token-for-the-ip-data-fetch-script>
IP_DATA_DIR=/tmp/ipdata

# Optional — Cloudflare Turnstile CAPTCHA on feedback and ratings (skipped
# when unset), and Resend for emailing feedback submissions
TURNSTILE_SECRET_KEY=<turnstile-secret-key>
RESEND_API_KEY=<resend-api-key>
```

```bash
python backend/server.py     # → http://localhost:5001
```

### Backups

`backend/backup_db.py` writes a data-only `pg_dump` to `backend/backups/`, and
`backend/restore_db.py` reloads chosen tables from one inside a single
transaction (`--list`, `--tables a,b`, `--all`). Both need the PostgreSQL **16**
command-line tools (`pg_dump`, `psql`) on `PATH`, matching the server: the backup
refuses any other `pg_dump` version, because newer ones write settings
PostgreSQL 16 rejects. On Windows, install them from
the EDB installer at postgresql.org/download/windows (select only *Command Line
Tools*) and add its `bin` folder to `PATH`.

### PostgreSQL integration tests

`backend/tests/pg/` runs the real SQL against a local PostgreSQL 16 + pgvector
server and skips unless `PG_TEST_URL` is set:

```bash
docker run -d --name rmh-pg-test -p 54329:5432 -e POSTGRES_PASSWORD=test pgvector/pgvector:pg16 -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key
cd backend && PG_TEST_URL='postgresql://postgres:test@localhost:54329/postgres?sslmode=require' python -m pytest tests/pg -q
```

In Git Bash on Windows, prefix the `docker run` with `MSYS_NO_PATHCONV=1`; otherwise Git Bash rewrites the `/etc/ssl/...` paths and PostgreSQL fails to start.

### Frontend

```bash
cd frontend
npm install
npm run dev                  # → http://localhost:5173
```

The dev frontend talks to the backend on port 5001 automatically. Optional `frontend/.env`:

```env
VITE_API_URL=<backend-url>                    # unset: same origin, proxied to 5001 in dev
VITE_TURNSTILE_SITE_KEY=<turnstile-site-key>  # required for production builds
```

### Browser extension

```bash
cd extension
npm install
npm run build                # → extension/dist
```

Load `extension/dist` as an unpacked extension at `chrome://extensions`, then put the id it shows in the backend's `EXTENSION_ORIGINS`.

### Scheduled jobs

`data-refresh` rebuilds the site's data every Sunday and `banner-refresh` pulls the course schedule every Monday.

`catalog-edition-watch` checks every Monday for the NEU catalog's new academic-year edition, which goes live between July and September. GitHub disables scheduled workflows in a public repo after 60 days without activity, so **before July each year, confirm it is still enabled in the Actions tab**.

---

<div align="center">

If RateMyHusky helped you dodge a 2.1-difficulty-but-somehow-brutal professor, star the repo.

</div>
