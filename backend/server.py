"""
Backend API server for NEU Professor Ratings.
No pandas/numpy — queries PostgreSQL directly per request.

Install deps:  pip install flask flask-cors flask-limiter psycopg2-binary pyjwt requests python-dotenv gunicorn
Run:           python server.py
"""

import os, re, unicodedata, json, hashlib, hmac, random, secrets
import html as _html
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from functools import lru_cache
from dotenv import load_dotenv
from prof_aliases import ALIAS_MAP
from pipeline.names import COLLEGE_MAP
from flask import Flask, g, jsonify, request, redirect, make_response
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
import jwt as pyjwt
import requests as http_requests
from urllib.parse import urlencode, urlparse
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
import time
from rag.chat_search import keyword_search
from rag.chat_question import handle_question
from rag.llm_adapter import GroqAdapter
from rag.key_pool import KeyPool
from rag.chat_gate import gate
from rag.chat_retrieve import retrieve, fetch_reddit_mentions
from rag.query_embedder import embed_query
from rag.chat_answer import generate, generate_course_list, generate_course_ranking
from course_page import build_course
from professor_full import build_payload
import bookmarks
import moderation
import notify
import ip_networks
import rating_identity
import rating_checks
import ratings
import survey_reviews
import usage_alert

load_dotenv()

import types as _types

CHAT_ENABLED = os.getenv("CHAT_ENABLED", "false").lower() == "true"
# The ip_hash in ask_log is only as private as this salt: with a known one, every
# IPv4 hash can be reversed by trying all 2^32 addresses.
_IP_SALT = os.getenv("ASK_IP_SALT", "")
if CHAT_ENABLED and not _IP_SALT:
    raise RuntimeError("ASK_IP_SALT must be set when CHAT_ENABLED is true")
_chat_pool = KeyPool()
_chat_adapter = GroqAdapter(_chat_pool)

def _hash_ip(ip):
    return hmac.new(_IP_SALT.encode(), (ip or "").encode(), hashlib.sha256).hexdigest()[:16]


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def normalize_name(name):
    s = str(name).strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# Joins multi-select dept/college filter values. Not ",": department names carry
# commas ("Lang, Literature and Culture"). Must match FILTER_SEPARATOR in api.ts.
FILTER_SEPARATOR = "|"


def split_filter(raw):
    return [v.strip() for v in (raw or "").split(FILTER_SEPARATOR) if v.strip()]


def int_arg(name, default, lo, hi):
    """request.args[name] as an int clamped to [lo, hi]; `default` when missing or
    not a number. A bare int() turned limit=0 into a ZeroDivisionError (a 500)."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


def float_arg(name, default, lo, hi, ndigits=1):
    """request.args[name] as a float clamped to [lo, hi] and rounded, so near-equal
    values share one cache entry instead of each minting a new one."""
    try:
        value = float(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    if value != value:   # NaN
        value = default
    return round(max(lo, min(value, hi)), ndigits)


# Search input caps: each word adds a LIKE clause, so an unbounded query is an
# unbounded scan. No professor name or course title needs more than this.
SEARCH_MAX_CHARS = 100
SEARCH_MAX_WORDS = 6
# The most rows a catalog page returns, except the sitemap's: the homepage asks for
# 100, and building or caching every filter combination of the whole catalog is how
# requests got multi-MB rebuilds and the cache filled with multi-MB entries.
CACHEABLE_PAGE_LIMIT = 100
# The sitemap fetches the whole catalog in one page of this size
# (frontend/scripts/generate-sitemap.mjs); it is the one big page served, and cached.
CATALOG_FULL_LIMIT = 10000
# Sorts each catalog knows; anything else is alpha, so made-up sort values all
# share alpha's cache entry instead of each minting one.
PROFESSOR_SORTS = {"alpha", "alpha_desc", "rating", "rating_asc", "comments"}
COURSE_SORTS = {"alpha", "alpha_desc", "rating", "rating_asc", "ratings", "recent"}


def sort_arg(known):
    sort = request.args.get("sort", "alpha")
    return sort if sort in known else "alpha"


def like_safe(text):
    """`text` with LIKE wildcards removed, so a typed % or _ can't match everything.
    Names and course titles never contain them."""
    return re.sub(r"[%_\\]", "", text)


def search_text(raw):
    """A user search string normalized for LIKE: lowercased, wildcard-free, capped."""
    q = like_safe(normalize_name(raw or ""))[:SEARCH_MAX_CHARS]
    return " ".join(q.split()[:SEARCH_MAX_WORDS])


def course_search_text(raw):
    """search_text for a course search, with a spaced code joined: "cs 3100" -> "cs3100".
    course_catalog.search_text stores the code unspaced, so the spaced form a student
    types only matched courses whose title happened to mention it."""
    return re.sub(r"\b([a-z]{2,5}) (\d{4})\b", r"\1\2", search_text(raw))


# Build a word-level mapping so partial/typeahead queries also resolve.
# e.g. typing "virgiliu" (an RMP-only spelling) still finds "virgil".
_WORD_ALIAS = {}
for _from, _to in ALIAS_MAP.items():
    _from_words = set(_from.split())
    _to_words = set(_to.split())
    for w in _from_words - _to_words:
        # Strip parens/punctuation so "(katherine)" becomes "katherine",
        # "c." becomes "c", matching what normalize_name produces.
        clean = re.sub(r'[^a-z0-9\-]', '', w)
        if clean:
            _WORD_ALIAS[clean] = _to_words - _from_words


def resolve_alias(q):
    """Return the canonical query if q matches an alias, else q."""
    return ALIAS_MAP.get(q, q)


def sanitize(text: str) -> str:
    return _html.unescape(str(text))


def friendly_count(n: int) -> str:
    if n < 100:
        return str(n)
    rounded = (n // 100) * 100
    return f"{rounded:,}+"


def _name_to_slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


# ──────────────────────────────────────────────
#  App setup
# ──────────────────────────────────────────────
class _JSONProvider(DefaultJSONProvider):
    """JSON nested too deep to parse raises RecursionError, which get_json lets through
    as a 500. As a ValueError it's bad JSON like any other: None with silent=True, else a 400."""

    def loads(self, s, **kwargs):
        try:
            return super().loads(s, **kwargs)
        except RecursionError as e:
            raise ValueError("JSON nested too deep") from e


app = Flask(__name__)
app.json = _JSONProvider(app)
app.config["COMPRESS_MIMETYPES"] = ["application/json", "text/html"]
app.config["COMPRESS_MIN_SIZE"] = 256
# Every request body is a small JSON object (feedback, bookmarks, Ask); reject
# anything bigger before it is read into memory.
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
Compress(app)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Set per environment, never defaulted: the id derives from the public key in
# extension/manifest.json, so anyone could copy that key into their own
# unpacked extension and inherit whatever this trusts. Comma-separated, so the
# dev id and the Web Store's can both run during the handover.
EXTENSION_ORIGINS = [
    o.strip() for o in os.getenv("EXTENSION_ORIGINS", "").split(",") if o.strip()
]

# Not EXTENSION_ORIGINS: a popup holding host_permissions for the site isn't
# subject to CORS, and the extension sends credentials: 'omit'. It still needs
# the ALLOWED_ORIGINS entry below, because Chrome does send an Origin header.
CORS(app, supports_credentials=True, origins=[FRONTEND_URL])
def get_real_ip():
    """Client IP: X-RMH-Client-IP from the keyed proxy, else last X-Forwarded-For."""
    # Only the Vercel middleware can send the key, so only then is the client
    # IP header it sets trustworthy. Checked here, not assumed from
    # require_proxy_key: the limiter's hook runs before that one.
    if _has_proxy_key():
        client_ip = request.headers.get("X-RMH-Client-IP", "").strip()
        if client_ip:
            return client_ip
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # Last entry is the IP appended by our trusted proxy (Vercel/Railway);
        # earlier entries are client-supplied and spoofable.
        return xff.split(",")[-1].strip()
    return get_remote_address()

limiter = Limiter(get_real_ip, app=app, default_limits=["20 per second"])


BLOCKED_USER_AGENTS = [
    "python-requests", "python-httpx", "python-urllib", "aiohttp",
    "scrapy", "curl", "wget", "go-http-client", "java/", "okhttp",
    "httpie", "postmanruntime", "node-fetch", "undici",
    "gptbot", "ccbot", "claudebot", "bytespider", "google-extended",
    "ahrefsbot", "semrushbot", "dotbot", "mj12bot", "petalbot",
    "barkrowler", "dataforseobot",
]

def _origin_host(value: str) -> str:
    """Normalize a URL to 'scheme://host[:port]', lowercased, or '' if unparseable.

    Strips any path/query (Referer carries a path; Origin does not) so the
    comparison is on the web origin only. Returns '' when scheme or host is
    missing, which never matches the allowlist.
    """
    p = urlparse(value or "")
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}".lower()


# Vercel Preview deploys get a new hostname per build, so they can't be listed
# like FRONTEND_URL. Set only where previews should reach this backend, e.g.
# ^https://rate-my-husky-(?:git-[a-z0-9-]+|[a-z0-9]+)-grain-is-grainys-projects\.vercel\.app$
# (matches PREVIEW_ORIGIN_RE in middleware.ts). The hyphen-free hash segment
# keeps another team's hash URLs out, but not a git-<branch> alias under a
# team slug ending in "-grain-is-grainys-projects" (or a claimed *.vercel.app
# alias), so treat a match as a likely preview, not a proven one.
# Unset = no preview origin is trusted.
_preview_re = os.getenv("PREVIEW_ORIGIN_RE", "").strip()
PREVIEW_ORIGIN_RE = re.compile(_preview_re) if _preview_re else None


def _is_preview_origin(origin: str) -> bool:
    """True for a normalized origin (from _origin_host) matching PREVIEW_ORIGIN_RE."""
    return bool(origin and PREVIEW_ORIGIN_RE and PREVIEW_ORIGIN_RE.fullmatch(origin))


# Compare against normalized origins so a stray trailing slash or path on either
# side can't cause a lockout (or a startswith-style prefix bypass).
ALLOWED_ORIGINS = {
    _origin_host(o) for o in (
        FRONTEND_URL,
        "http://localhost:5173",
        "http://localhost:3000",
        *EXTENSION_ORIGINS,
    ) if _origin_host(o)
}


@app.before_request
def block_bots():
    ua = (request.headers.get("User-Agent") or "").lower()
    if ua and any(bot in ua for bot in BLOCKED_USER_AGENTS):
        return jsonify({"error": "Forbidden"}), 403


# Shared secret added by the Vercel middleware proxy (frontend/middleware.ts).
# Unset = open, which is only allowed off Railway (local dev): on Railway an unset
# secret would leave the backend reachable directly, bypassing the proxy.
PROXY_SECRET = os.getenv("PROXY_SECRET")
if not PROXY_SECRET and os.getenv("RAILWAY_ENVIRONMENT"):
    raise RuntimeError("PROXY_SECRET must be set on Railway")


def _has_proxy_key():
    """True when the request carries the Vercel proxy's shared secret."""
    if not PROXY_SECRET:
        return False
    # Bytes, not str: compare_digest raises on non-ASCII strings, and WSGI hands a
    # header over as latin-1, so `X-Proxy-Key: ÿ` was a 500 instead of a 403.
    return hmac.compare_digest(request.headers.get("X-Proxy-Key", "").encode(), PROXY_SECRET.encode())


@app.before_request
def require_proxy_key():
    if not PROXY_SECRET:
        return
    if not _has_proxy_key():
        return jsonify({"error": "Forbidden"}), 403


@app.before_request
def check_origin():
    """Block API requests that don't originate from the frontend."""
    if request.path.startswith("/api/auth/google"):
        return  # allow OAuth redirects
    if request.path == "/api/csp-report":
        return  # browsers send violation reports without a usable Origin; it only logs
    if request.method == "OPTIONS":
        return  # allow CORS preflight
    raw = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if not raw:
        return  # no Origin/Referer (e.g. same-origin GET) — nothing to check
    origin = _origin_host(raw)
    if origin not in ALLOWED_ORIGINS and not _is_preview_origin(origin):
        return jsonify({"error": "Forbidden"}), 403


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# TEMPORARY: per-request server time for the backend refactor's latency targets.
# Remove once the targets are measured.
_TIMED_PREFIXES = ("/api/professors/", "/api/courses/", "/api/professors-catalog",
                   "/api/courses-catalog")


@app.before_request
def _timing_start():
    g.t0 = time.perf_counter()


@app.after_request
def _timing_log(response):
    t0 = g.pop("t0", None)
    if t0 is not None and request.path.startswith(_TIMED_PREFIXES):
        print(f"[timing] {request.path} {response.status_code} "
              f"{(time.perf_counter() - t0) * 1000:.1f}ms", flush=True)
    return response


@app.errorhandler(HTTPException)
def _http_error(e):
    """404/405/429 and every other HTTP error as JSON; the frontend reads the status.

    A limiter 429 never names its bucket ("20 per 1 hour"): that tells a client which
    key it hit, and so whether a fresh device token gets around it."""
    if e.code == 429:
        return jsonify({"error": "Rate limit reached. Please try again later."}), 429
    return jsonify({"error": e.description}), e.code


@app.errorhandler(Exception)
def _unhandled_error(e):
    """Any uncaught error is logged with its traceback and served as a JSON 500."""
    app.logger.exception("Unhandled error on %s", request.path)
    return jsonify({"error": "Internal server error"}), 500


# ──────────────────────────────────────────────
#  Database connection pool
# ──────────────────────────────────────────────
ORACLE_DATABASE_URL = os.getenv("ORACLE_DATABASE_URL")
if not ORACLE_DATABASE_URL:
    raise RuntimeError("ORACLE_DATABASE_URL environment variable is required")

_pool = None
_pool_lock = Lock()


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    # Locked: two threads creating it at once (the purge thread starts alongside the
    # first request after a boot) would each open a pool and leak one.
    with _pool_lock:
        if _pool is None:
            _pool = ThreadedConnectionPool(5, 10, ORACLE_DATABASE_URL, sslmode="require",
                                           connect_timeout=5,
                                           # UTC: the Groq budget, throttle and usage-alert
                                           # queries take "today" from the session, and the
                                           # Python side counts days in UTC.
                                           options="-c statement_timeout=5000 -c timezone=UTC",
                                           keepalives=1, keepalives_idle=30,
                                           keepalives_interval=10, keepalives_count=3)
    return _pool

# ──────────────────────────────────────────────
#  Simple in-memory cache (TTL-based)
# ──────────────────────────────────────────────
_cache = {}
_cache_lock = Lock()
CACHE_TTL = 86400      # 24 h; a pipeline run invalidates by bumping data_version
CACHE_MAX_SIZE = 5000

_feedback_lock = Lock()
_feedback_count = 0
_account_feedback_count = 0
_feedback_by_account = {}
_feedback_date = None   # "YYYY-MM-DD" UTC, resets counter each day
FEEDBACK_DAILY_LIMIT = 80
# Requests with a verified account get their own allowance, so anonymous reports can't
# use up the day and block a data-deletion request. 80 + 15 + 3 usage alerts + 1
# review digest (review_digest.py) fit Resend's free 100/day.
ACCOUNT_FEEDBACK_DAILY_LIMIT = 15
# One account's share of that allowance, so one user sending from several IPs can't
# use up the day and block another user's data-deletion request.
FEEDBACK_PER_ACCOUNT_DAILY_LIMIT = 3
# feedback types that require a reply email and carry the signed-in account's verified sub,
# so support can act on the right ask_log rows (review an appeal, or erase the user's data)
_ACCOUNT_FEEDBACK_TYPES = {"banappeal", "datadeletion"}
# A professor asking to correct or remove their page: the FAQ, Privacy Policy and
# Terms say these can't be verified or answered without an email, so it's required.
_EMAIL_REQUIRED_FEEDBACK_TYPES = _ACCOUNT_FEEDBACK_TYPES | {"professor"}

# Types that can change or remove what a professor's page shows. The FAQ and the
# Privacy Policy promise professors we confirm these at their Northeastern
# address before acting, so the support email says up front whether that is possible.
_PAGE_CHANGE_FEEDBACK_TYPES = {"missing", "incorrectdata", "professor"}

# Every type the endpoint accepts, with its email subject label. "missing" and
# "feature" were merged into "incorrectdata" and "general" on the form but stay
# accepted for cached bundles; "banappeal" is hidden while Ask is off. Drop the two
# old keys once no tab can still be running a pre-merge bundle (a couple of weeks
# after the merge ships).
_FEEDBACK_TYPE_LABELS = {
    "bug": "Bug Report",
    "incorrectdata": "Wrong or Missing Data",
    "missing": "Missing Data",
    "general": "Idea or General Feedback",
    "reviewreport": "Review Report",   # the Report link on a RateMyHusky review
    "feature": "Feature Request",
    "professor": "Professor Request",
    "datadeletion": "Account Deletion Request",
    "banappeal": "Ask Ban Appeal",
}
# These limits and the email pattern in submit_feedback are copied in
# frontend/src/components/FeedbackTab.tsx and frontend/public/maintenance.html
# (maxlength attributes and the submit handler's regex). Change all three together.
FEEDBACK_MAX_DESCRIPTION = 5000
FEEDBACK_MAX_EMAIL = 254   # RFC 5321's limit on a full address

def _turnstile_unconfigured():
    """True on Railway without TURNSTILE_SECRET_KEY: forms then fail closed, since
    skipping the CAPTCHA is only meant for local dev."""
    return not os.getenv("TURNSTILE_SECRET_KEY") and bool(os.getenv("RAILWAY_ENVIRONMENT"))


def _turnstile_verdict(token):
    """Cloudflare's siteverify answer for `token`, or None when it can't be reached."""
    try:
        resp = http_requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": os.getenv("TURNSTILE_SECRET_KEY"), "response": token, "remoteip": get_real_ip()},
            timeout=5,
        )
        verdict = resp.json() if resp.ok else {}
    except Exception:
        return None
    return verdict if isinstance(verdict, dict) else {}


def _turnstile_accepts(verdict):
    """A passed challenge, solved on our own site. A token solved on another site that
    embeds our public site key must not count; checked on Railway only, because
    Turnstile's test keys report a placeholder hostname. Vercel previews share this
    backend under a new hostname per branch, so PREVIEW_ORIGIN_RE vouches for those."""
    if not verdict.get("success"):
        return False
    hostname = (verdict.get("hostname") or "").lower()
    return (not os.getenv("RAILWAY_ENVIRONMENT") or hostname in _turnstile_hostnames()
            or _is_preview_origin(_origin_host(f"https://{hostname}")))


def _turnstile_gate(token, label, unavailable):
    """None when the CAPTCHA passes (or is off, in local dev), else the (status, error)
    to answer with. Shared by feedback and ratings so the two fail the same way;
    `unavailable` is the form's own message for when the CAPTCHA isn't set up."""
    if _turnstile_unconfigured():
        print(f"[{label}] TURNSTILE_SECRET_KEY not configured")
        return 503, unavailable
    if not os.getenv("TURNSTILE_SECRET_KEY"):
        return None
    if not token or not isinstance(token, str):
        return 400, "CAPTCHA verification required"
    verdict = _turnstile_verdict(token)
    if verdict is None:
        # Cloudflare unreachable is our outage, not a failed human check: retry later.
        return 503, "CAPTCHA verification is unavailable, try again shortly"
    if not _turnstile_accepts(verdict):
        return 403, "CAPTCHA verification failed"
    return None


def _turnstile_hostnames():
    """Hostnames a Turnstile token may have been solved on: the frontend's, its www
    variant, plus any extras in TURNSTILE_HOSTNAMES (comma-separated)."""
    host = (urlparse(FRONTEND_URL).hostname or "").lower()
    names = {host, f"www.{host}"} if host else set()
    names |= {h.strip().lower() for h in os.getenv("TURNSTILE_HOSTNAMES", "").split(",") if h.strip()}
    return names


def _is_northeastern_address(email):
    """@northeastern.edu, or a college subdomain such as @khoury.northeastern.edu."""
    domain = email.rpartition("@")[2].lower()
    return domain == "northeastern.edu" or domain.endswith(".northeastern.edu")


def professor_verify_note(feedback_type, reply_email):
    """The "Verify:" line for a page-change request, or None for other types."""
    if feedback_type not in _PAGE_CHANGE_FEEDBACK_TYPES:
        return None
    if not reply_email:
        return "no email - if this is a professor's request, it can't be verified or answered; don't act on it"
    if _is_northeastern_address(reply_email):
        return "Northeastern address - if it's a professor's request, reply to confirm before acting"
    return "not a Northeastern address - if it's a professor's request, ask them to write from their Northeastern email"



DATA_VERSION_TTL = 60
_version_state = {"value": 0, "checked": 0.0}
_version_lock = Lock()


def data_version():
    """stats_cache.data_version, re-read at most once a minute per process. Every
    pipeline run bumps it, which retires every cached page at once. Bumping it by
    hand (UPDATE stats_cache SET value = value + 1 WHERE key = 'data_version')
    flushes every process's cache within a minute, e.g. after a takedown or
    moderation change."""
    now = time.time()
    with _version_lock:
        if now - _version_state["checked"] < DATA_VERSION_TTL:
            return _version_state["value"]
        _version_state["checked"] = now
    try:
        row = query_one("SELECT value FROM stats_cache WHERE key = 'data_version'")
    except psycopg2.Error as e:
        # A cache hit needs no other query; keep serving it and re-read in a minute.
        print(f"data_version: read failed, keeping v{_version_state['value']}: {e}")
        return _version_state["value"]
    value = int(row["value"]) if row else 0
    with _version_lock:
        if value != _version_state["value"]:
            with _cache_lock:
                _cache.clear()   # entries under the old version can never be read again
        _version_state["value"] = value
    return value


def cache_get(key):
    key = f"v{data_version()}:{key}"
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry["ts"] < CACHE_TTL:
            return entry["data"]
        return None


def cache_set(key, data):
    key = f"v{data_version()}:{key}"
    with _cache_lock:
        _cache.pop(key, None)   # re-insert so dict order stays oldest-first
        _cache[key] = {"data": data, "ts": time.time()}
        while len(_cache) > CACHE_MAX_SIZE:
            del _cache[next(iter(_cache))]


def drop_professor_pages(slugs):
    """Drop the cached /full of each professor in slugs, under every slug it was
    opened by: the cache key is the URL's slug, which may be an alias."""
    with _cache_lock:
        for k in [k for k, e in _cache.items()
                  if ":prof_full:" in k and (e["data"].get("identity") or {}).get("slug") in slugs]:
            del _cache[k]


def _acquire_fresh_conn():
    key = id(g._get_current_object() if hasattr(g, '_get_current_object') else g)
    g.db_key = key
    g.db = _get_pool().getconn(key=key)
    return g.db


def _discard_db_conn():
    """Return the current request's connection to the pool and mark it closed."""
    db = g.pop('db', None)
    key = g.pop('db_key', None)
    if db is not None:
        try:
            _get_pool().putconn(db, key=key, close=True)
        except Exception:
            try:
                db.close()
            except Exception:
                pass


def _rollback_after_cancel(conn):
    """A cancelled statement aborts the transaction (the pool is not autocommit), so
    roll back or the request's next query fails with InFailedSqlTransaction."""
    try:
        conn.rollback()
    except Exception:
        _discard_db_conn()


def get_db():
    if 'db' not in g:
        return _acquire_fresh_conn()
    conn = g.db
    if conn.closed:
        _discard_db_conn()
        return _acquire_fresh_conn()
    return conn


@app.teardown_appcontext
def return_db(exc):
    db = g.pop('db', None)
    key = g.pop('db_key', None)
    if db is not None:
        try:
            _get_pool().putconn(db, key=key)
        except KeyError:
            try:
                db.close()
            except Exception:
                pass


def query(sql, params=None):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur.fetchall()
    except psycopg2.extensions.QueryCanceledError:
        _rollback_after_cancel(conn)
        raise   # statement_timeout: the connection is healthy, a retry would just time out again
    except (psycopg2.InterfaceError, psycopg2.OperationalError):
        # Connection was stale — discard it and retry once with a fresh one
        _discard_db_conn()
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, params or ())
            return cur.fetchall()
        except psycopg2.Error:
            _rollback_after_cancel(conn)   # the sibling except below can't catch a failed retry
            raise
    except psycopg2.Error:
        # Any failed statement aborts the transaction too (the pool is not
        # autocommit). Roll back so a guarded read (teaching history) can fail
        # without failing the request's later queries.
        if conn is not None:
            _rollback_after_cancel(conn)
        raise


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def _chat_write(sql, params=None):
    """Write helper for the question path (ask_log INSERTs): execute + commit, never fetch.
    The read-only query()/query_one() call fetchall(), which raises on a non-RETURNING INSERT;
    and the pool is not autocommit, so writes must commit explicitly.
    A logging write must never fail the request that already generated a successful answer:
    retry once on a stale connection (mirrors query()), then swallow and log any further error."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
    except psycopg2.extensions.QueryCanceledError as e:
        _rollback_after_cancel(conn)
        print(f"_chat_write: log write timed out, dropping: {e}")
    except (psycopg2.InterfaceError, psycopg2.OperationalError):
        try:
            _discard_db_conn()
            conn = get_db()
            cur = conn.cursor()
            cur.execute(sql, params or ())
            conn.commit()
        except Exception as e:
            print(f"_chat_write: log write failed after retry, dropping: {e}")
    except Exception as e:
        print(f"_chat_write: log write failed, dropping: {e}")

def _chat_write_rc(sql, params=None):
    """Like _chat_write but returns the executed statement's rowcount."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    conn.commit()
    return cur.rowcount

# ask_log keeps each question with its account id and ip_hash; rows older than this
# are deleted. The abuse ladder only reads the last STRIKE_WINDOW_DAYS (7) and the
# budget only today's, so 30 days leaves room for appeals and debugging.
ASK_LOG_RETENTION_DAYS = 30
ASK_LOG_PURGE_EVERY = 3600          # seconds between purge attempts per process
ASK_LOG_PURGE_BATCH = 5000          # bounded so one DELETE stays inside statement_timeout
_ask_log_purge = {"last": 0.0}
_ask_log_purge_lock = Lock()


def _claim_ask_log_purge(now=None):
    """True for the one caller per ASK_LOG_PURGE_EVERY that should run the purge."""
    now = time.time() if now is None else now
    with _ask_log_purge_lock:
        if now - _ask_log_purge["last"] < ASK_LOG_PURGE_EVERY:
            return False
        _ask_log_purge["last"] = now
        return True


def delete_old_ask_log(write_fn=None):
    """Delete a batch of ask_log rows past retention; best-effort, since _chat_write
    logs a failure and the next hour retries."""
    # Postgres has no DELETE ... LIMIT, so the batch is picked in a subquery
    # (by created_at, which al_created indexes).
    (write_fn or _chat_write)(
        "DELETE FROM ask_log WHERE id IN (SELECT id FROM ask_log "
        "WHERE created_at < now() - %s * INTERVAL '1 day' LIMIT %s)",
        (ASK_LOG_RETENTION_DAYS, ASK_LOG_PURGE_BATCH))


def purge_old_ask_log(write_fn=None, now=None):
    """delete_old_ask_log at most once an hour per process."""
    if _claim_ask_log_purge(now):
        delete_old_ask_log(write_fn)


def _purge_ask_log_job():
    with app.app_context():   # get_db() keeps its connection on flask.g
        delete_old_ask_log()


@app.before_request
def purge_ask_log_in_background():
    """Start the hourly purge from whatever request comes in first, on its own
    thread: it runs whether or not Ask is on, and no user waits for the DELETE.
    Railway only, so local dev never deletes from the database. Claimed here, before
    the thread starts, so a burst of requests at the hour starts just one."""
    if os.getenv("RAILWAY_ENVIRONMENT") and _claim_ask_log_purge():
        Thread(target=_purge_ask_log_job, daemon=True).start()


def _write(sql, params=None):
    """Write helper for user-facing mutations (bookmarks add/remove): execute +
    commit, retry once on a stale connection (mirrors query()). Unlike
    _chat_write, this does not swallow errors — a failed bookmark write must
    surface to the caller, not be silently dropped like a best-effort log write.
    Returns the RETURNING rows as dicts, or None for a statement without one."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        rows = cur.fetchall() if cur.description else None
        conn.commit()
    except psycopg2.extensions.QueryCanceledError:
        _rollback_after_cancel(conn)
        raise
    except (psycopg2.InterfaceError, psycopg2.OperationalError):
        _discard_db_conn()
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        rows = cur.fetchall() if cur.description else None
        conn.commit()
    return rows



# ──────────────────────────────────────────────
#  Google OAuth config
# ──────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Session tokens carry their own issuer and audience, so a token signed with the
# same secret for some other purpose can't be replayed as a sign-in.
JWT_ISSUER = "ratemyhusky"
JWT_AUDIENCE = "ratemyhusky-web"
# Tokens can't be revoked server-side (logout only drops the browser's copy), so a
# stolen one is usable until it expires; keep that window short.
SESSION_DAYS = 7


def decode_session_token(token):
    """The verified claims of a session token, or None when it is missing, expired,
    forged or minted without our issuer/audience."""
    if not token:
        return None
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"],
                            audience=JWT_AUDIENCE, issuer=JWT_ISSUER)
    except pyjwt.InvalidTokenError:   # ExpiredSignatureError is a subclass
        return None


# ──────────────────────────────────────────────
#  Search helper
# ──────────────────────────────────────────────
def _professor_search(q, limit=5, rated_only=False):
    """Search professors with tiered relevance ranking. rated_only applies the
    caller's avg_rating filter before the 100-row cut, not after it."""
    # Normalize first: name_key is stored lowercase/ASCII, and LIKE is
    # case-sensitive. Callers like the chat/Ask path pass a raw gate hint ("Wu Chieh"),
    # so without this the LIKE filter (and the lowercase ALIAS_MAP) never match.
    q = search_text(q)
    # Resolve full-query alias first (e.g. "virgiliu pavlu" → "virgil pavlu")
    q_resolved = resolve_alias(q)

    words = q_resolved.split()
    if not words:
        return []

    # Expand individual words through the word-level alias map so partial
    # typeahead queries like "virgiliu" also match "virgil pavlu".
    expanded_words = set(words)
    for w in words:
        if w in _WORD_ALIAS:
            expanded_words.update(_WORD_ALIAS[w])

    # Build WHERE: each *original* word must match, OR its alias expansion must
    conditions = []
    params = []
    for word in words:
        alt_words = _WORD_ALIAS.get(word)
        if alt_words:
            group = [word] + list(alt_words)
            conditions.append("(" + " OR ".join("name_key LIKE %s" for _ in group) + ")")
            params.extend(f"%{w}%" for w in group)
        else:
            conditions.append("name_key LIKE %s")
            params.append(f"%{word}%")

    if rated_only:
        conditions.append("avg_rating IS NOT NULL")
    where = " AND ".join(conditions)
    rows = query(
        f"SELECT slug, name, name_key, department, avg_rating, total_reviews "
        f"FROM professors_catalog WHERE {where} "
        f"ORDER BY (name_key LIKE %s OR name_key LIKE %s) DESC, total_reviews DESC LIMIT 100",
        params + [f"{q_resolved}%", f"% {q_resolved}%"]
    )

    # Rank in Python for proper tiered relevance (use resolved query)
    q_rank = q_resolved
    words_rank = q_resolved.split()

    def rank_match(row):
        nk = row['name_key']
        parts = nk.split()

        # Tier 1: q matches a whole name part exactly
        if q_rank in parts:
            return 1
        # Tier 2: q matches the start of any name part
        if any(p.startswith(q_rank) for p in parts):
            return 2
        # Tier 3: q is a substring of the full name
        if q_rank in nk:
            return 3
        # Tier 4: multi-word: each word prefixes a name part
        if len(words_rank) >= 2 and all(any(p.startswith(w) for p in parts) for w in words_rank):
            return 4
        # Tier 5: multi-word: each word is substring of any name part
        if len(words_rank) >= 2 and all(any(w in p for p in parts) for w in words_rank):
            return 5
        return 6

    ranked = sorted(rows, key=lambda r: (rank_match(r), -(r['total_reviews'] or 0)))
    return ranked[:limit]


# ──────────────────────────────────────────────
#  API Routes
# ──────────────────────────────────────────────
@app.route("/api/stats")
def stats():
    cached = cache_get("stats")
    if cached:
        resp = jsonify(cached)
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp
    rows = query("SELECT key, value FROM stats_cache")
    stat_map = {r['key']: r['value'] for r in rows}
    result = [
        {"label": "Professors", "value": friendly_count(stat_map.get('professors', 0))},
        {"label": "Courses", "value": friendly_count(stat_map.get('courses', 0))},
        {"label": "Comments", "value": friendly_count(stat_map.get('comments', 0))},
        {"label": "Departments", "value": friendly_count(stat_map.get('departments', 0))},
    ]
    cache_set("stats", result)
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/colleges")
def colleges():
    cached = cache_get("colleges")
    if cached:
        return jsonify(cached)
    rows = query("""
        SELECT college, COUNT(*) as cnt FROM professors_catalog
        WHERE avg_rating IS NOT NULL
        GROUP BY college HAVING COUNT(*) >= 5
        ORDER BY college
    """)
    result = [r['college'] for r in rows if r['college'] != 'Other']
    cache_set("colleges", result)
    return jsonify(result)


# ── Leaderboard ranking ──────────────────────────────────────────────
# Ranking by raw avg_rating lets a 5.00 built on 3 reviews outrank a 4.9 built on
# 500. 551 professors sit at exactly 5.00 and 97% of them have under 15 reviews.
# That is why the Law and Professional Studies boards filled up with them when
# those boards carried a review floor of 5 rather than 100 and course
# evaluations still counted toward total_reviews.
#
# So rank on a Bayesian posterior mean instead — the IMDb Top 250 formula —
# blending each professor toward the global mean with a prior worth SHRINKAGE_M
# reviews:   (n*R + m*C) / (n + m)
#
# A professor with 3 reviews is dragged to C; one with 500 barely moves. m=50 is
# small enough that the correlation between score and review count only rises to
# ~0.26 (it saturates around 0.30, so a larger m buys nothing but distortion).
# C is read from the data rather than hardcoded so it tracks re-scrapes.
#
# This is the *sort key only* — the displayed number stays avg_rating. Shrinkage
# is mathematically a contraction, so it cannot spread the top of the board; the
# clustering near 4.9 is a real property of the ratings, not something a formula
# should paper over.
SHRINKAGE_M = 50

# What C is measured over. It was avg(avg_rating) across the entire catalog,
# which is mostly professors carrying a handful of responses: their ratings are
# sampling noise, so averaging them describes the noise rather than the
# professors, and the prior the whole board shrinks toward came out of it.
#
# The prior of a ranking should be the mean of the quantity being ranked, so it
# is measured over professors whose rating is actually pinned down. At 30
# responses the standard error of a mean rating is ~0.13; at 5 it is ~0.33, which
# is wider than the entire top of the board.
#
# Deliberately global rather than per-college: a per-college prior ranks each
# professor against their own college, which is department-relative ranking under
# another name. That was built once and rejected — this board is a class-picking
# tool, not a per-department award.
RANKING_PRIOR_MIN_REVIEWS = 30
FALLBACK_PRIOR = 4.2   # only for an empty or brand-new catalog

# The board's evidence floor, and deliberately the same 30 as the prior's: a
# threshold for "well enough measured to be ranked" cannot sensibly be looser
# than the one for "well enough measured to inform the prior". The standard-error
# argument above is the whole reason for both.
#
# It replaced a floor of 100 with a per-college exception dropping Law and
# Professional Studies to 5. Both halves of that were wrong in opposite
# directions, and shrinkage is what makes a single number workable:
#
#   - 100 is too strict for total_reviews as it now stands: RMP ratings and
#     survey ratings only, since course evaluations left it (2026-10-04). At 100,
#     all 6 of the boards that fill at 30 change members, 5 of them lose rows,
#     and Engineering's drops to 0.
#     Nor does shrinkage do the floor's job: Khoury's rank-10 score needs ~17
#     reviews at a perfect 5.00, so on a board that fills at 30 it is the floor,
#     not the shrunk score, that keeps a thinly rated 5.00 off it. On a short
#     board the fill below lets one on, under every professor at 30.
#   - 5 was the old exception's floor, and it comes back as a fill rather than a
#     floor. Health Sciences has 5 professors at 30, and a short board read as
#     broken. So a board that has fewer than `limit` professors at 30 is filled
#     from those with at least BOARD_FILL_MIN_REVIEWS. The fill ranks below
#     every professor at 30, whatever its score: shrinkage alone would let a
#     5.00 on 20 ratings pass a 4.50 on 30. No SHRINKAGE_M fixes that: as m
#     grows the score orders by n * (rating - prior), and 20 * (5.00 - C) beats
#     30 * (4.50 - C) whenever C is above 3.5. A board with `limit` professors
#     at 30 and at or above the prior never reaches the fill.
#
# Nobody rated below the prior is on a board, however many ratings back it.
# Ranking the 30+ tier first otherwise put a 2.86 on 250 ratings at Health
# Sciences #5, above fill professors at 4.57-5.00.
BOARD_MIN_REVIEWS = 30
BOARD_FILL_MIN_REVIEWS = 5

# Law and Professional Studies have no board at all. Neither has a professor
# at 30 (their grad, part-time and online students barely use RMP), and even
# the fill cannot reach 10: Law had 7 eligible at that floor and Professional
# Studies 5, so a "top 10" would be every rated professor in the college, on 5
# to 16 ratings each and scoring within 0.25 of the prior. Homepage.tsx leaves
# them out of COLLEGES to match.
NO_BOARD_COLLEGES = frozenset({"Law", "Professional Studies"})
BOARD_COLLEGES = frozenset(COLLEGE_MAP.values()) - NO_BOARD_COLLEGES

# total_reviews (BIGINT) is cast to float so the shrinkage arithmetic is
# floating-point throughout instead of leaning on implicit int/float coercion.
# float(m), not "{m}.0" — the latter renders "0.9.0" and is a syntax error if
# SHRINKAGE_M is ever tuned to a non-integer.
# The prior arrives as a bound parameter rather than a subquery, so the sort does
# not carry a full-table aggregate and the value can be measured under its own
# filter. It is cast explicitly (%s::float) so its type never depends on how the
# driver renders the bound value.
RANKING_SCORE_SQL = """
    ((total_reviews::float * avg_rating + {m} * %s::float)
     / (total_reviews::float + {m}))
""".format(m=float(SHRINKAGE_M))


def ranking_prior(query_one):
    """Mean rating of professors well-enough measured to have one.

    Falls back to a constant only when nothing clears the floor, which means an
    empty catalog — ranking on None would order the whole board by review count.
    """
    row = query_one("""
        SELECT avg(avg_rating) AS prior FROM professors_catalog
        WHERE avg_rating IS NOT NULL AND total_reviews >= %s
    """, (RANKING_PRIOR_MIN_REVIEWS,))
    prior = row.get("prior") if row else None
    return float(prior) if prior is not None else FALLBACK_PRIOR


def shrunk_score(avg_rating, total_reviews, prior_mean, m=SHRINKAGE_M):
    """Python mirror of RANKING_SCORE_SQL (for tests and any Python-side ranking)."""
    if avg_rating is None:
        return None
    n = total_reviews or 0
    return (n * avg_rating + m * prior_mean) / (n + m)


@app.route("/api/goat-professors")
def goat_professors():
    college = request.args.get("college", "Khoury")
    # Clamped, and the floor is not a parameter: every distinct value would
    # store its own cache entry, and a negative LIMIT is a Postgres error.
    limit = max(1, min(request.args.get("limit", 10, type=int), 50))

    # v5: the ordering has changed three times — to the shrunk score, again when
    # the prior stopped being the whole-catalog average, and again when the
    # per-college review floor collapsed to a single BOARD_MIN_REVIEWS and the
    # sort gained a name tiebreak. v6: short boards fill from
    # BOARD_FILL_MIN_REVIEWS, Law and Professional Studies lost their boards,
    # and ratings below the prior left. An unbumped key serves the previous
    # version from the cache after deploy, which looks exactly like the fix not
    # working. v7: rows carry the slug; a cached v6 row has none to link with.
    # Unknown colleges are answered before the cache: every value would
    # otherwise store its own [] and push real boards out of the LRU. With
    # limit clamped, a college holds at most 50 entries.
    if college not in BOARD_COLLEGES:
        return jsonify([])
    cache_key = f"goat:v7:{college}:{limit}"
    cached = cache_get(cache_key)
    # `is not None`: an empty board is a real answer and must cache too.
    if cached is not None:
        return jsonify(cached)

    prior = ranking_prior(query_one)
    # `name` breaks ties last. Without it, professors equal on both score and
    # review count come back in whatever order the scan produces, so the board
    # could reshuffle between requests. Measured on the current corpus:
    # 3 such groups across the catalog, covering 6 professors, and none
    # reaching a top 10. So this closes the door rather than fixing a visible bug.
    #
    # Which colleges hold them is not worth stating: an earlier version of this
    # comment said "none in Law", Law acquired one on the next refresh, and the
    # test guarding the claim went red on data drift alone. Tie groups move
    # whenever total_reviews is recomputed. The durable property is the one
    # test_measured_claims checks — that no tie reaches a board's top 10, which
    # is the only place the ordering is visible.
    rows = query(f"""
        SELECT * FROM professors_catalog
        WHERE college = %s AND total_reviews >= %s AND avg_rating >= %s
        ORDER BY total_reviews >= %s DESC,
                 {RANKING_SCORE_SQL} DESC, total_reviews DESC, name
        LIMIT %s
    """, (college, BOARD_FILL_MIN_REVIEWS, prior, BOARD_MIN_REVIEWS, prior, limit))

    result = []
    for row in rows:
        result.append({
            # Link by this, never by the name: namesakes get a -2 suffix.
            "slug": row["slug"],
            "name": row["name"],
            "dept": row["department"],
            "rmpRating": round(row["rmp_rating"], 2) if row["rmp_rating"] else None,
            # Never NULL: `avg_rating >= %s` above drops those rows.
            "avgRating": round(row["avg_rating"], 2),
            # Displayed as "Ratings": the floor above gates on it and
            # RANKING_SCORE_SQL weights by it.
            "totalReviews": row["total_reviews"] or 0,
            "totalComments": row["total_comments"] or 0,
        })
    if result:   # an unknown college is empty; don't let made-up names fill the cache
        cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/random-professor")
def random_professor():
    count_row = query_one("SELECT COUNT(*) as cnt FROM professors_catalog WHERE num_ratings >= 3")
    total = count_row["cnt"] if count_row else 0
    if total == 0:
        return jsonify({"error": "No professors found"}), 404
    offset = random.randint(0, total - 1)
    row = query_one("""
        SELECT * FROM professors_catalog
        WHERE num_ratings >= 3
        LIMIT 1 OFFSET %s
    """, (offset,))
    if not row:
        return jsonify({"error": "No professors found"}), 404
    return jsonify({
        "name": row["name"],
        "dept": row["department"],
        "college": row["college"],
    })


def _format_course_code(raw: str) -> str:
    return re.sub(r"\s+", "", str(raw).upper())


@app.route("/api/search")
def search():
    q = search_text(request.args.get("q", ""))
    search_type = request.args.get("type", "Professor")
    limit = int_arg("limit", 5, 1, 20)

    if len(q) < 2:
        return jsonify([])

    if search_type == "Professor":
        matches = _professor_search(q, limit)
        results = []
        for r in matches:
            results.append({
                "type": "professor",
                "name": r["name"],
                "dept": r["department"],
                "rating": round(r["avg_rating"], 2) if r["avg_rating"] and r["avg_rating"] > 0 else None,
                "slug": r["slug"],
            })
        return jsonify(results)

    else:
        # Course search
        q = course_search_text(request.args.get("q", ""))
        rows = query("""
            SELECT code, name, department FROM course_catalog
            WHERE search_text LIKE %s
            ORDER BY
                CASE WHEN lower(code) LIKE %s THEN 0 ELSE 1 END,
                code
            LIMIT %s
        """, (f"%{q}%", f"{q}%", limit))

        results = []
        for r in rows:
            results.append({
                "type": "course",
                "code": r["code"],
                "name": r["name"],
                "dept": r["department"],
            })
        return jsonify(results)


# ──────────────────────────────────────────────
#  Reddit RAG chatbot
# ──────────────────────────────────────────────
@app.route("/api/chat", methods=["GET", "POST"])
@limiter.limit("30 per minute")
def chat():
    # Keyword search is a GET. Ask questions are POSTed in a JSON body so they stay
    # out of the query string, and with it out of Vercel's and Railway's access logs.
    if request.method == "POST":
        body = request.get_json(silent=True)
        q = body.get("q") if isinstance(body, dict) else None
        q = q.strip() if isinstance(q, str) else ""
        mode = "question"
    else:
        q = (request.args.get("q") or "").strip()
        mode = request.args.get("mode", "keyword")
        if mode != "keyword":
            return jsonify({"mode": "error", "message": "Ask questions must be sent as a POST."}), 405
    if len(q) < 2:
        return jsonify({"mode": mode, "results": []})
    if mode == "keyword":
        try:
            limit = min(int(request.args.get("limit", "20")), 50)
        except (TypeError, ValueError):
            limit = 20
        data = keyword_search(q, query, _professor_search, limit=limit,
                              mod_filter=moderation.sql_filter("t"))
        return jsonify({"mode": "keyword", "results": data["comments"], "professors": data["professors"]})
    # 'question' mode is account-gated: identity comes from the verified JWT (not a spoofable
    # header), so the abuse ladder keys on a server-trusted user id that can't be forged or omitted.
    _claims = decode_session_token(_get_auth_token())
    if _claims is None:
        return jsonify({"mode": "error", "message": "Sign in to use Ask mode."}), 401
    deps = _types.SimpleNamespace(
        chat_enabled=CHAT_ENABLED,
        num_keys=len(_chat_pool.entries) or 1,
        query_fn=query,
        query_one_fn=query_one,
        prof_search_fn=_professor_search,
        cache_get_fn=cache_get,
        cache_set_fn=cache_set,
        keyword_search_fn=lambda qq: keyword_search(qq, query, _professor_search),
        gate_fn=lambda qq: gate(qq, _chat_adapter),
        retrieve_fn=lambda qq, hint: retrieve(qq, hint, query, query_one, _professor_search,
                                             embed_query_fn=embed_query, rmp_mod=moderation.sql_filter),
        generate_fn=lambda qq, blocks: generate(qq, blocks, _chat_adapter),
        generate_course_list_fn=lambda topic, courses: generate_course_list(topic, courses, _chat_adapter),
        generate_course_ranking_fn=lambda subject, metric, direction, courses: generate_course_ranking(subject, metric, direction, courses, _chat_adapter),
        log_fn=_chat_write,
        usage_alert_fn=lambda: usage_alert.maybe_alert(
            query, query_one, _chat_write_rc, len(_chat_pool.entries) or 1),
    )
    session_token = _claims.get("sub")  # verified account id — unspoofable, never None
    if not session_token:
        return jsonify({"mode": "error", "message": "Sign in to use Ask mode."}), 401
    ip_hash = _hash_ip(get_real_ip())
    payload, code = handle_question(q, session_token, ip_hash, deps)
    return jsonify(payload), code


def _department_colleagues(department, exclude_slug):
    """Up to 8 other professors_catalog rows in the same department, highest
    review-count first. Cached per department (shared across every professor
    in it) since professors_catalog is indexed on department already."""
    if not department:
        return []
    cache_key = f"colleagues:{department}"
    rows = cache_get(cache_key)
    if rows is None:
        rows = query("""
            SELECT name, slug, avg_rating, total_reviews FROM professors_catalog
            WHERE department = %s AND slug IS NOT NULL AND total_reviews >= 1
            ORDER BY total_reviews DESC LIMIT 9
        """, (department,))
        cache_set(cache_key, rows)
    colleagues = []
    for r in rows:
        if r["slug"] == exclude_slug:
            continue
        colleagues.append({
            "name": r["name"],
            "slug": r["slug"],
            "avgRating": round(r["avg_rating"], 2) if r["avg_rating"] else None,
            "totalRatings": r["total_reviews"],
        })
    return colleagues[:8]


# ──────────────────────────────────────────────
#  Professor profile page
# ──────────────────────────────────────────────
def professor_payload(slug):
    """The §4.2 payload for `slug` (cached), or None when no professor matches.
    Shared by /full and render.py so the crawler page and the app agree."""
    # The lookup also accepts case, hyphen and alias variants of a name. A variant
    # caches only a pointer to the professor's own slug, so old or mis-cased links
    # hit the one cached payload instead of each keeping a full copy (or rebuilding).
    canonical = cache_get(f"prof_slug:{slug}")
    data = cache_get(f"prof_full:{canonical or slug}")
    if data is None and canonical is None:
        # A slug seen for the first time may be a variant of a page that is cached:
        # one indexed lookup finds out before a full build_payload.
        prof = _resolve_professor(slug, query_one)
        if prof is None:
            return None
        canonical = prof["slug"]
        if canonical != slug:
            cache_set(f"prof_slug:{slug}", canonical)
            data = cache_get(f"prof_full:{canonical}")
    if data is None:
        data = build_payload(canonical or slug, query, query_one, sanitize, fetch_reddit_mentions,
                             review_id=_review_id if _student_reviews_shown() else None)
        if data is None:
            return None
        if data.pop("_partial", False):
            g.history_failed = True   # a failed Banner or survey read is not cached: see history_cache_control
        else:
            cache_set(f"prof_full:{data['identity']['slug']}", data)
    return data


def _student_reviews_shown():
    """/rate comments go out on professor pages only with SHOW_STUDENT_REVIEWS on:
    the frontend's RATE_ENABLED only hides the tab, not what /full returns."""
    return SHOW_STUDENT_REVIEWS and _rating_enabled()


def _review_id(rating_uuid):
    return survey_reviews.public_id(RATING_SECRET, rating_uuid)


def history_cache_control(resp):
    """A page built after a failed Banner read must not be cached downstream
    either, or the CDN keeps the degraded page for a day. Also used by render.py."""
    if g.get("history_failed"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/professors/<slug>/full")
def professor_full(slug):
    data = professor_payload(slug)
    if data is None:
        return jsonify({"error": "Professor not found"}), 404
    # The department links to its hub page only when there is one: the hub drops small
    # departments. Copied, because professor_payload hands back the cached dict.
    identity = data["identity"]
    dept_slug = department_slug(identity.get("department") or "")
    data = {**data, "identity": {**identity, "departmentSlug": dept_slug if dept_slug in _department_hub_map() else None}}
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "private, max-age=3600" if _is_authed() else "public, max-age=3600"
    resp.headers["Vary"] = "Authorization"
    return history_cache_control(resp)


from professor_full import _resolve_professor  # same lookup as /full, skips denied profs

MIN_TAG_REVIEWS = 3  # need at least this many reviews before showing a tag


@app.route("/api/professors/<slug>/tags")
def professor_tags(slug):
    cache_key = f"prof_tags:{slug}"
    data = cache_get(cache_key)
    if data is None:
        prof = _resolve_professor(slug, query_one)
        if not prof:
            return jsonify({"error": "Professor not found"}), 404
        rows = query(
            "SELECT tag, review_count FROM professor_tags "
            "WHERE name_key = %s AND review_count >= %s ORDER BY review_count DESC",
            (prof["name_key"], MIN_TAG_REVIEWS),
        )
        data = [{"tag": r["tag"], "count": r["review_count"]} for r in rows]
        cache_set(cache_key, data)
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/tags/popular")
def popular_tags():
    data = cache_get("tags_popular")
    if data is None:
        # join on professors_catalog so denied profs don't get counted
        rows = query(
            "SELECT pt.tag, COUNT(*) AS profs FROM professor_tags pt "
            "JOIN professors_catalog pc ON pc.name_key = pt.name_key "
            "WHERE pt.review_count >= %s GROUP BY pt.tag ORDER BY profs DESC LIMIT 20",
            (MIN_TAG_REVIEWS,),
        )
        # count is number of profs with the tag
        data = [{"tag": r["tag"], "count": int(r["profs"])} for r in rows]
        cache_set("tags_popular", data)
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/departments")
def departments():
    college = request.args.get("college", "")
    cache_key = f"depts:{college or 'all'}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    if college and college != "All":
        college_list = split_filter(college)
        if len(college_list) == 1:
            rows = query("""
                SELECT DISTINCT department FROM professors_catalog
                WHERE avg_rating IS NOT NULL AND college = %s
                ORDER BY department
            """, (college_list[0],))
        else:
            rows = query("""
                SELECT DISTINCT department FROM professors_catalog
                WHERE avg_rating IS NOT NULL AND college IN (""" + ",".join(["%s"] * len(college_list)) + """)
                ORDER BY department
            """, tuple(college_list))
    else:
        rows = query("""
            SELECT DISTINCT department FROM professors_catalog
            WHERE avg_rating IS NOT NULL
            ORDER BY department
        """)
    BAD_DEPTS = {"Computer amp Informational Tech.", "Computer  Informational Tech.", "Counseling amp Educational Psych", "Counseling  Educational Psych"}
    result = [r['department'] for r in rows if r['department'] and r['department'] not in BAD_DEPTS]
    if result:   # an unknown college is empty; don't let made-up names fill the cache
        cache_set(cache_key, result)
    return jsonify(result)


def department_slug(name):
    """Deterministic, reversible department slug: lowercase, '&' -> 'and',
    any run of non-alphanumerics -> single '-', trim leading/trailing '-'."""
    s = name.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _department_hub_map():
    """slug -> {name, professorCount, avgRating} for every department with
    >=1 rated professor (avg_rating set, so unrated Banner-only professors
    in professors_catalog are not counted), built
    from a single grouped query. Cached like the other catalog lookups.
    Collisions (two department names slugging to the same value) keep the
    first-seen entry and drop the rest."""
    cached = cache_get("dept_hub_map")
    if cached is not None:
        return cached
    rows = query("""
        SELECT department, COUNT(*) as cnt, AVG(avg_rating) as avg
        FROM professors_catalog
        WHERE avg_rating IS NOT NULL AND department IS NOT NULL AND department != ''
        GROUP BY department
    """)
    BAD_DEPTS = {"Computer amp Informational Tech.", "Computer  Informational Tech.", "Counseling amp Educational Psych", "Counseling  Educational Psych"}
    by_slug = {}
    for r in rows:
        name = r["department"]
        if not name or name in BAD_DEPTS:
            continue
        slug = department_slug(name)
        if slug in by_slug:
            continue  # collision: keep the first-seen department for this slug
        by_slug[slug] = {
            "slug": slug,
            "name": name,
            "professorCount": r["cnt"],
            "avgRating": round(r["avg"], 2) if r["avg"] is not None else None,
        }
    cache_set("dept_hub_map", by_slug)
    return by_slug


@app.route("/api/departments/hub")
def departments_hub():
    cache_key = "depts_hub_list"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    by_slug = _department_hub_map()
    entries = sorted(by_slug.values(), key=lambda d: d["professorCount"], reverse=True)
    result = {"departments": entries, "total": len(entries)}
    cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/departments/<slug>")
def department_hub_detail(slug):
    cache_key = f"dept_hub:{slug}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    by_slug = _department_hub_map()
    entry = by_slug.get(slug)
    if not entry:
        return jsonify({"error": "Department not found"}), 404

    rows = query("""
        SELECT name, slug, avg_rating, difficulty, would_take_again_pct, total_reviews
        FROM professors_catalog
        WHERE department = %s AND avg_rating IS NOT NULL
        ORDER BY avg_rating DESC
    """, (entry["name"],))
    professors = [{
        "name": r["name"],
        "slug": r["slug"],
        "avgRating": round(r["avg_rating"], 2) if r["avg_rating"] is not None else None,
        "difficulty": round(r["difficulty"], 2) if r["difficulty"] is not None else None,
        "wouldTakeAgainPct": round(r["would_take_again_pct"], 1) if r["would_take_again_pct"] is not None else None,
        "totalRatings": r["total_reviews"],
    } for r in rows]

    result = {
        "name": entry["name"],
        "slug": entry["slug"],
        "professorCount": entry["professorCount"],
        "avgRating": entry["avgRating"],
        "professors": professors,
    }
    cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/professors-catalog")
def professors_catalog():
    q = search_text(request.args.get("q", ""))
    college = request.args.get("college", "")
    dept = request.args.get("dept", "")
    sort = sort_arg(PROFESSOR_SORTS)
    page = int_arg("page", 1, 1, 100000)
    limit = int_arg("limit", 20, 1, CATALOG_FULL_LIMIT)

    min_rating = float_arg("minRating", 0.0, 0.0, 5.0)
    max_rating = float_arg("maxRating", 5.0, 0.0, 5.0)
    min_reviews = int_arg("minReviews", 1, 1, 100000)
    max_reviews = int_arg("maxReviews", -1, -1, 100000)
    max_reviews = None if max_reviews < 0 else max_reviews

    def key(pg, rows):
        return (f"profcat:{q}:{college}:{dept}:{sort}:{pg}:{rows}:"
                f"{min_rating}:{max_rating}:{min_reviews}:{max_reviews}")

    # Only the sitemap's exact request gets the whole catalog; any other big page gets
    # CACHEABLE_PAGE_LIMIT rows. So every page served is small or that one, and cached.
    if limit > CACHEABLE_PAGE_LIMIT and key(page, limit) != f"profcat::::alpha:1:{CATALOG_FULL_LIMIT}:0.0:5.0:1:None":
        limit = CACHEABLE_PAGE_LIMIT
    cached = cache_get(key(page, limit))
    if cached:
        return jsonify(cached)

    # If there's a search query, get matching name_keys first
    matched_name_keys = None
    if q and len(q) >= 2:
        matches = _professor_search(q, limit=200, rated_only=True)
        matched_name_keys = [m["name_key"] for m in matches]
        if not matched_name_keys:
            return jsonify({"professors": [], "total": 0, "page": 1, "totalPages": 1})

    # Build dynamic query
    conditions = ["avg_rating IS NOT NULL"]
    params = []

    if college and college != "All":
        college_list = split_filter(college)
        if len(college_list) == 1:
            conditions.append("college = %s")
            params.append(college_list[0])
        elif college_list:
            conditions.append("college IN (" + ",".join(["%s"] * len(college_list)) + ")")
            params.extend(college_list)
    DEPT_ALIASES = {
        "Computer & Informational Tech.": ["Computer amp Informational Tech.", "Computer  Informational Tech."],
        "Counseling & Educational Psych": ["Counseling amp Educational Psych", "Counseling  Educational Psych"],
    }
    if dept and dept != "All":
        dept_list = split_filter(dept)
        expanded = []
        for d in dept_list:
            expanded.append(d)
            expanded.extend(DEPT_ALIASES.get(d, []))
        if len(expanded) == 1:
            conditions.append("department = %s")
            params.append(expanded[0])
        elif expanded:
            conditions.append("department IN (" + ",".join(["%s"] * len(expanded)) + ")")
            params.extend(expanded)
    if min_rating > 0:
        conditions.append("avg_rating >= %s")
        params.append(min_rating)
    if max_rating < 5:
        conditions.append("avg_rating <= %s")
        params.append(max_rating)
    if min_reviews > 1:
        conditions.append("total_reviews >= %s")
        params.append(min_reviews)
    if max_reviews is not None:
        conditions.append("total_reviews <= %s")
        params.append(max_reviews)

    where = " AND ".join(conditions)

    if matched_name_keys is not None:
        # Filter to search matches, preserve search order
        placeholders = ",".join(["%s"] * len(matched_name_keys))
        # Get total count
        count_row = query_one(
            f"SELECT COUNT(*) as cnt FROM professors_catalog WHERE {where} AND name_key IN ({placeholders})",
            params + matched_name_keys
        )
        total = count_row["cnt"]

        # Get page data - preserve search ranking order
        total_pages = max(1, (total + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit

        all_rows = query(
            f"SELECT * FROM professors_catalog WHERE {where} AND name_key IN ({placeholders})",
            params + matched_name_keys
        )

        # Reorder by search ranking
        name_key_order = {nk: i for i, nk in enumerate(matched_name_keys)}
        all_rows.sort(key=lambda r: name_key_order.get(r["name_key"], 999999))
        page_rows = all_rows[offset:offset + limit]
    else:
        # No search - use SQL sorting
        if sort == "rating":
            order = "avg_rating DESC NULLS LAST"
        elif sort == "rating_asc":
            order = "avg_rating ASC NULLS LAST, slug ASC"
        elif sort == "alpha_desc":
            order = "lower(name) DESC, slug DESC"
        elif sort == "comments":
            order = "total_comments DESC"
        else:
            order = "lower(name) ASC"

        count_row = query_one(f"SELECT COUNT(*) as cnt FROM professors_catalog WHERE {where}", params)
        total = count_row["cnt"]

        total_pages = max(1, (total + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit

        page_rows = query(
            f"SELECT * FROM professors_catalog WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [limit, offset]
        )

    professors = []
    for row in page_rows:
        professors.append({
            "name": row["name"],
            "slug": row["slug"],
            "department": row["department"],
            "college": row["college"],
            "avgRating": round(row["avg_rating"], 2) if row["avg_rating"] else None,
            "rmpRating": round(row["rmp_rating"], 2) if row["rmp_rating"] else None,
            "totalReviews": row["total_reviews"],
            "totalComments": row.get("total_comments", 0) or 0,
            "wouldTakeAgainPct": round(row["would_take_again_pct"], 1) if row["would_take_again_pct"] else None,
            "imageUrl": row["image_url"],
            "focusX": row.get("focus_x") if row.get("focus_x") is not None else 50.0,
            "focusY": row.get("focus_y") if row.get("focus_y") is not None else 30.0,
        })

    result = {
        "professors": professors,
        "total": total,
        "page": page,
        "totalPages": total_pages,
    }
    # Under the page served, which a page past the end was clamped to: page=2..100000
    # past a 1-page result are one entry, not one each.
    cache_set(key(page, limit), result)
    return jsonify(result)


@app.route("/api/course-departments")
def course_departments():
    cached = cache_get("course_depts")
    if cached:
        return jsonify(cached)
    rows = query("""
        SELECT DISTINCT department FROM course_catalog
        WHERE department IS NOT NULL AND department != ''
        ORDER BY department
    """)
    result = [r["department"] for r in rows]
    cache_set("course_depts", result)
    return jsonify(result)


@app.route("/api/courses-catalog")
def courses_catalog():
    q = course_search_text(request.args.get("q", ""))
    dept = request.args.get("dept", "")
    sort = sort_arg(COURSE_SORTS)
    page = int_arg("page", 1, 1, 100000)
    limit = int_arg("limit", 20, 1, CATALOG_FULL_LIMIT)

    min_rating = float_arg("minRating", 0.0, 0.0, 5.0)
    max_rating = float_arg("maxRating", 5.0, 0.0, 5.0)

    # The catalog page shows rated courses only; the sitemap and prerender need every course.
    rated_only = request.args.get("rated") == "1"

    def key(pg, rows):
        return f"coursecat:{q}:{dept}:{sort}:{pg}:{rows}:{min_rating}:{max_rating}:{rated_only}"

    # Same cap as professors_catalog: only the sitemap's exact request gets the whole catalog.
    if limit > CACHEABLE_PAGE_LIMIT and key(page, limit) != f"coursecat:::alpha:1:{CATALOG_FULL_LIMIT}:0.0:5.0:False":
        limit = CACHEABLE_PAGE_LIMIT
    cached = cache_get(key(page, limit))
    if cached:
        return jsonify(cached)

    # avg_rating is precomputed on course_catalog (see precompute.py step 8),
    # so this is a plain indexed SELECT/WHERE/ORDER/LIMIT like professors_catalog.
    conditions = ["avg_rating IS NOT NULL"] if rated_only else []
    params = []

    if dept and dept != "All":
        dept_list = split_filter(dept)
        if len(dept_list) == 1:
            conditions.append("department = %s")
            params.append(dept_list[0])
        elif dept_list:
            conditions.append("department IN (" + ",".join(["%s"] * len(dept_list)) + ")")
            params.extend(dept_list)
    if q:
        conditions.append("search_text LIKE %s")
        params.append(f"%{q}%")
    if min_rating > 0:
        conditions.append("avg_rating >= %s")
        params.append(min_rating)
    if max_rating < 5:
        conditions.append("avg_rating <= %s")
        params.append(max_rating)

    where_str = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    join = ""
    if sort == "rating":
        order = "avg_rating DESC NULLS LAST, lower(code) ASC"
    elif sort == "rating_asc":
        order = "avg_rating ASC NULLS LAST, lower(code) ASC"
    elif sort == "alpha_desc":
        order = "lower(code) DESC"
    elif sort == "ratings":
        order = "num_ratings DESC NULLS LAST, lower(code) ASC"
    elif sort == "recent":
        # Last term Banner has the course on, best rated first within a term;
        # courses Banner never saw go last. From 2026 Summer 1 and Summer 2
        # share one code (202650), so the label orders the sessions, as in
        # teaching_history.label_code.
        join = "LEFT JOIN banner_course_offerings bco ON bco.subject_course = course_catalog.code"
        order = """bco.last_term_code DESC NULLS LAST,
                   CASE WHEN bco.last_term_label LIKE 'Summer 2 %%' THEN 2
                        WHEN bco.last_term_label LIKE 'Summer 1 %%' THEN 0 ELSE 1 END DESC,
                   avg_rating DESC NULLS LAST, lower(code) ASC"""
    else:
        order = "lower(code) ASC"

    count_row = query_one(f"SELECT COUNT(*) as cnt FROM course_catalog {where_str}", params)
    total = count_row["cnt"] if count_row else 0

    total_pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * limit

    def page_rows(join, order):
        return query(f"""
            SELECT code, name, department, avg_rating, num_ratings FROM course_catalog {join}
            {where_str}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

    try:
        rows = page_rows(join, order)
    except psycopg2.errors.UndefinedTable:
        # Banner decorates the catalog and never fails it: without its tables
        # (a fresh database), Most Recent sorts like Highest Rated.
        rows = page_rows("", "avg_rating DESC NULLS LAST, lower(code) ASC")

    courses = [
        {
            "code": r["code"],
            "name": r["name"],
            "department": r["department"],
            "avgRating": round(r["avg_rating"], 2) if r["avg_rating"] is not None else None,
            "numRatings": int(r.get("num_ratings") or 0),
        }
        for r in rows
    ]

    result = {
        "courses": courses,
        "total": total,
        "page": page,
        "totalPages": total_pages,
    }
    # Under the page served, which a page past the end was clamped to: page=2..100000
    # past a 1-page result are one entry, not one each.
    cache_set(key(page, limit), result)
    return jsonify(result)


def course_payload(code):
    """The §4.3 payload for `code` (cached), or None when it is not in the catalog.
    Shared by /api/courses/<code> and render.py."""
    code_norm = _format_course_code(code)
    if not code_norm:
        return None
    cache_key = f"course:{code_norm}"
    data = cache_get(cache_key)
    if data is None:
        data = build_course(code_norm, query, query_one)
        if data is None:
            return None
        if data.pop("_historyFailed", False):
            g.history_failed = True   # a failed Banner read is not cached: see history_cache_control
        else:
            cache_set(cache_key, data)
    return data


@app.route("/api/courses/<code>")
def course_profile(code):
    data = course_payload(code)
    if data is None:
        return jsonify({"error": "Course not found"}), 404
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "private, max-age=3600" if _is_authed() else "public, max-age=3600"
    resp.headers["Vary"] = "Authorization"
    return history_cache_control(resp)


# ──────────────────────────────────────────────
#  Google OAuth routes
# ──────────────────────────────────────────────
def _login_frontend():
    """The frontend a login started from: a preview origin from the Referer, else FRONTEND_URL."""
    origin = _origin_host(request.headers.get("Referer", ""))
    return origin if _is_preview_origin(origin) else FRONTEND_URL


def _callback_frontend(flow):
    """The frontend the callback returns to; the cookie is client-held, so re-check it."""
    origin = (flow or {}).get("origin")
    return origin if isinstance(origin, str) and _is_preview_origin(origin) else FRONTEND_URL


# Each sign-in keeps its own cookie, named after its state, holding where to return,
# whether it is a popup and which frontend it started on. With shared cookies, a
# second tab starting a sign-in overwrote the first's, which then failed the state check.
AUTH_FLOW_COOKIE = "auth_flow_"
_STATE_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")   # secrets.token_urlsafe output
# Sign-ins one browser keeps open at once. A flow that fails at Google or is backed
# out of never reaches the callback, so starting another drops the oldest past this;
# unbounded, retries pile up cookies until the Cookie header is too big to send.
AUTH_FLOW_MAX = 3


def _auth_flow(state):
    """The {"returnTo", "popup", "origin"} saved when this browser started sign-in
    `state`, or None when it didn't start one (or it expired)."""
    if not _STATE_RE.match(state or ""):
        return None
    try:
        flow = json.loads(request.cookies.get(AUTH_FLOW_COOKIE + state, ""))
    except ValueError:
        return None
    return flow if isinstance(flow, dict) else None


def _stale_auth_flows():
    """Cookie names of this browser's sign-ins to drop so the one starting now fits:
    all but the newest AUTH_FLOW_MAX - 1 by start time, unreadable ones counting oldest."""
    flows = []
    for name in request.cookies:
        if name.startswith(AUTH_FLOW_COOKIE):
            started = (_auth_flow(name[len(AUTH_FLOW_COOKIE):]) or {}).get("t")
            flows.append((started if isinstance(started, (int, float)) else -1, name))
    flows.sort(reverse=True)
    return [name for _, name in flows[AUTH_FLOW_MAX - 1:]]


def _end_auth_flow(resp, state):
    """`resp` with sign-in `state`'s cookie deleted; every callback outcome ends the flow.
    `state` comes from the query string, so only a well-formed one names a cookie."""
    if _STATE_RE.match(state or ""):
        resp.delete_cookie(AUTH_FLOW_COOKIE + state, httponly=True, samesite="None", secure=True)
    return resp


def _get_redirect_uri(frontend):
    # Go through the Vercel proxy, not direct to Railway. Google rejects any
    # redirect_uri not registered on the client, so only registered previews
    # (e.g. the dev branch's fixed URL) can sign in.
    return f"{frontend}/api/auth/google/callback"


# Browsers drop a cookie over 4KB, which failed the sign-in. The cap counts the path
# as JSON writes it into the flow cookie (é takes six characters), and the cookie's
# own quoting at most doubles that, so this leaves room.
RETURN_TO_MAX = 1500


def _json_len(value):
    """Characters `value` takes inside the flow cookie's JSON, not counting its quotes."""
    return len(json.dumps(value)) - 2


def _safe_return_to(value):
    """`value` if it is a path on this site, else "/". Over RETURN_TO_MAX the query
    string is dropped first. "//host" and "/\\host" are refused: they are paths to
    the server but links to another site once the frontend reuses them."""
    if not isinstance(value, str):
        return "/"
    if _json_len(value) > RETURN_TO_MAX:
        value = value.split("?", 1)[0]
    parsed = urlparse(value)
    if (_json_len(value) > RETURN_TO_MAX or parsed.scheme or parsed.netloc
            or not value.startswith("/") or value.startswith("//") or "\\" in value):
        return "/"
    return value


@app.route("/api/auth/google")
@limiter.limit("10 per minute")
def auth_google():
    return_to = _safe_return_to(request.args.get("returnTo", "/"))
    frontend = _login_frontend()
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _get_redirect_uri(frontend),
        "response_type": "code",
        "scope": "openid email profile",
        "hd": "husky.neu.edu",
        # Bound to this browser by its auth_flow_ cookie and checked on the callback,
        # so nobody can complete a sign-in into their account in someone else's browser.
        "state": state,
    }
    flow = {"returnTo": return_to, "popup": request.args.get("popup") == "1", "t": int(time.time())}
    if frontend != FRONTEND_URL:
        flow["origin"] = frontend
    resp = make_response(redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}"))
    for name in _stale_auth_flows():
        resp.delete_cookie(name, httponly=True, samesite="None", secure=True)
    resp.set_cookie(AUTH_FLOW_COOKIE + state, json.dumps(flow), max_age=600,
                    httponly=True, samesite="None", secure=True)
    return resp


@app.route("/api/auth/google/callback")
@limiter.limit("10 per minute")
def auth_google_callback():
    code = request.args.get("code")
    state = request.args.get("state", "")
    flow = _auth_flow(state)
    frontend = _callback_frontend(flow)

    def fail(reason):
        return _end_auth_flow(redirect(f"{frontend}?auth_error={reason}"), state)

    if not code:
        return fail("no_code")
    if flow is None:
        return fail("state_mismatch")

    try:
        token_resp = http_requests.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": _get_redirect_uri(frontend),
            "grant_type": "authorization_code",
        }, timeout=10)
        if token_resp.status_code != 200:
            return fail("token_exchange_failed")

        access_token = token_resp.json().get("access_token")

        user_resp = http_requests.get(GOOGLE_USERINFO_URL, headers={
            "Authorization": f"Bearer {access_token}",
        }, timeout=10)
        if user_resp.status_code != 200:
            return fail("userinfo_failed")
    except Exception:
        return fail("timeout")

    user_info = user_resp.json()

    if user_info.get("hd") != "husky.neu.edu":
        return fail("invalid_domain")

    payload = {
        "sub": user_info["id"],
        "email": user_info["email"],
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

    if flow.get("popup") is True:
        # Desktop popup: post message to opener and close
        resp = make_response(f"""
        <html><body><script>
          window.opener && window.opener.postMessage({{ type: "auth_complete", token: "{token}" }}, "{frontend}");
          window.close();
        </script></body></html>
        """)
    else:
        # Mobile redirect: pass token via URL fragment (not querystring, so it's not logged)
        return_to = _safe_return_to(flow.get("returnTo"))
        resp = make_response(redirect(f"{frontend}{return_to}#auth_token={token}"))
    return _end_auth_flow(resp, state)


def _get_auth_token():
    """Get JWT token from Authorization header or cookie."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("auth_token")


def _is_authed():
    """True when the request carries a valid session token. Pages serve the same
    payload either way; only the Cache-Control header differs."""
    return decode_session_token(_get_auth_token()) is not None


@app.route("/api/auth/me")
@limiter.limit("30 per minute")
def auth_me():
    payload = decode_session_token(_get_auth_token())
    if payload is None:
        return jsonify(None), 401
    return jsonify({
        "email": payload["email"],
        "name": payload["name"],
        "picture": payload.get("picture", ""),
    })


@app.route("/api/auth/logout", methods=["POST"])
@limiter.limit("10 per minute")
def auth_logout():
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie("auth_token")
    return resp


def _require_bookmarks_auth():
    """Hard-401 auth gate shared by all three /api/bookmarks routes (same
    pattern as /api/chat's question mode). Returns the JWT `sub` claim, or
    None if a 401 JSON response has already been returned in its place."""
    claims = decode_session_token(_get_auth_token())
    return claims["sub"] if claims else None


@app.route("/api/bookmarks")
@limiter.limit("30 per minute")
def bookmarks_get():
    user_sub = _require_bookmarks_auth()
    if not user_sub:
        return jsonify({"error": "Sign in required"}), 401
    return jsonify(bookmarks.list_bookmarks(user_sub, query))


def _json_object():
    """The request's JSON body when it is an object, else {} (a list, a string,
    or no JSON at all), so handlers can call .get on it."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _json_str(data, name):
    """A stripped string field; "" when missing or not a string (123, null)."""
    value = data.get(name)
    return value.strip() if isinstance(value, str) else ""


@app.route("/api/bookmarks", methods=["POST"])
@limiter.limit("20 per minute")
def bookmarks_add():
    user_sub = _require_bookmarks_auth()
    if not user_sub:
        return jsonify({"error": "Sign in required"}), 401

    data = _json_object()
    item_type = _json_str(data, "itemType")
    item_key = _json_str(data, "itemKey")
    if item_type not in ("professor", "course") or not item_key:
        return jsonify({"error": "itemType must be 'professor' or 'course', itemKey is required"}), 400

    status = bookmarks.add_bookmark(user_sub, item_type, item_key, query_one, _write)
    if status == "not_found":
        return jsonify({"error": "Not found"}), 404
    if status == "limit_reached":
        return jsonify({"error": "Bookmark limit reached"}), 400
    return jsonify({"ok": True})


@app.route("/api/bookmarks", methods=["DELETE"])
@limiter.limit("20 per minute")
def bookmarks_remove():
    user_sub = _require_bookmarks_auth()
    if not user_sub:
        return jsonify({"error": "Sign in required"}), 401

    data = _json_object()
    item_type = _json_str(data, "itemType")
    item_key = _json_str(data, "itemKey")
    if item_type not in ("professor", "course") or not item_key:
        return jsonify({"error": "itemType must be 'professor' or 'course', itemKey is required"}), 400

    bookmarks.remove_bookmark(user_sub, item_type, item_key, _write)
    return jsonify({"ok": True})


# What a CSP report logs, each value capped. URLs lose their query string, which
# can carry search terms or tokens.
CSP_REPORT_FIELDS = ("document-uri", "effective-directive", "violated-directive",
                     "blocked-uri", "source-file", "line-number")
CSP_REPORT_URL_FIELDS = {"document-uri", "blocked-uri", "source-file"}


@app.route("/api/csp-report", methods=["POST"])
@limiter.limit("60 per hour")
def csp_report():
    """Logs the browser reports for frontend/vercel.json's Content-Security-Policy-Report-Only,
    so we can see what the policy would block before enforcing it. Nothing is stored.
    frontend/middleware.ts forwards only a sample (CSP_REPORT_SAMPLE) of them."""
    data = request.get_json(force=True, silent=True)   # sent as application/csp-report
    report = data.get("csp-report") if isinstance(data, dict) else None
    if isinstance(report, dict):
        fields = {}
        for name in CSP_REPORT_FIELDS:
            value = str(report.get(name, ""))
            if name in CSP_REPORT_URL_FIELDS:
                value = value.split("?", 1)[0].split("#", 1)[0]
            fields[name] = value[:300]
        print("[csp] " + json.dumps(fields), flush=True)
    return "", 204


@app.route("/api/feedback", methods=["POST"])
# Only sent feedback counts toward the per-IP limit, so junk posts that fail the
# CAPTCHA or validation can't use up a real user's 10 a day.
@limiter.limit("10 per day", deduct_when=lambda response: response.status_code == 200)
# Every post counts here, so junk tokens can't make unlimited siteverify calls
# (each holds a worker for up to 5 s).
@limiter.limit("50 per day")
def submit_feedback():
    global _feedback_count, _account_feedback_count, _feedback_date

    data = _json_object()
    feedback_type = _json_str(data, "feedbackType")
    description = _json_str(data, "description")
    reply_email = _json_str(data, "email")
    turnstile_token = _json_str(data, "turnstileToken")
    account_token = _json_str(data, "accountSub")

    # Validate before Turnstile: a bad request shouldn't cost a siteverify call
    # or use up the user's one-time CAPTCHA token.
    if not feedback_type or not description:
        return jsonify({"error": "feedbackType and description are required"}), 400

    if feedback_type not in _FEEDBACK_TYPE_LABELS:
        return jsonify({"error": "Unknown feedback type"}), 400

    if len(description) > FEEDBACK_MAX_DESCRIPTION:
        return jsonify({"error": f"Description is too long (max {FEEDBACK_MAX_DESCRIPTION} characters)"}), 400

    # Ask ban appeals, data-deletion and professor requests are useless without a reply
    # address — require it (other types stay optional).
    if feedback_type in _EMAIL_REQUIRED_FEEDBACK_TYPES and not reply_email:
        return jsonify({"error": "Email is required for this request"}), 400

    if reply_email and (len(reply_email) > FEEDBACK_MAX_EMAIL
                        or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', reply_email)):
        return jsonify({"error": "Invalid email address"}), 400

    # Resolve the account from its JWT (verified server-side, never trust a client-supplied id)
    # so we can locate/clear its ask_log rows by session_token (appeal review or data erasure).
    appeal_account = None
    if feedback_type in _ACCOUNT_FEEDBACK_TYPES and account_token:
        claims = decode_session_token(account_token)
        appeal_account = claims.get("sub") if claims else None

    # Support can't erase data that isn't tied to an account, so don't send it on.
    if feedback_type == "datadeletion" and appeal_account is None:
        return jsonify({"error": "Sign in required"}), 401

    # Verify Cloudflare Turnstile CAPTCHA
    failed = _turnstile_gate(turnstile_token, "feedback", "Feedback is temporarily unavailable")
    if failed:
        status, error = failed
        return jsonify({"error": error}), status

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _feedback_lock:
        if _feedback_date != today:
            _feedback_date = today
            _feedback_count = _account_feedback_count = 0
            _feedback_by_account.clear()
        if appeal_account:
            if (_account_feedback_count >= ACCOUNT_FEEDBACK_DAILY_LIMIT
                    or _feedback_by_account.get(appeal_account, 0) >= FEEDBACK_PER_ACCOUNT_DAILY_LIMIT):
                return jsonify({"error": "Daily feedback limit reached. Please try again tomorrow."}), 429
            _account_feedback_count += 1
            _feedback_by_account[appeal_account] = _feedback_by_account.get(appeal_account, 0) + 1
        else:
            if _feedback_count >= FEEDBACK_DAILY_LIMIT:
                return jsonify({"error": "Daily feedback limit reached. Please try again tomorrow."}), 429
            _feedback_count += 1

    if not os.getenv("RESEND_API_KEY"):
        print("[feedback] RESEND_API_KEY not configured")
        return jsonify({"error": "Email service not configured"}), 500

    type_label = _FEEDBACK_TYPE_LABELS[feedback_type]
    submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"Submitted:   {submitted_at}",
        f"Type:        {type_label}",
    ]
    if reply_email:
        lines.append(f"From:        {reply_email}")
    verify_note = professor_verify_note(feedback_type, reply_email)
    if verify_note:
        lines.append(f"Verify:      {verify_note}")
    if feedback_type in _ACCOUNT_FEEDBACK_TYPES:
        # surface the session_token to act on via clear_ask_strikes.py
        # (--account <sub> for appeals, --purge-account <sub> for data deletion)
        lines.append(f"Account:     {appeal_account or 'not signed in / token invalid'}")
    lines += ["", "Description:", description]
    body = "\n".join(lines)

    if not notify.send_team_email(f"[RateMyHusky] {type_label}", body, reply_to=reply_email or None):
        return jsonify({"error": "Failed to send email"}), 500

    return jsonify({"ok": True})


# ──────────────────────────────────────────────
#  Student ratings (no login): /api/rate
# ──────────────────────────────────────────────

RATING_SECRET = os.getenv("RATING_SECRET")
# Off until launch: turn it on with the frontend's RATE_ENABLED (see _student_reviews_shown).
SHOW_STUDENT_REVIEWS = os.getenv("SHOW_STUDENT_REVIEWS", "false").lower() == "true"
# Loaded at import so gunicorn --preload reads the data files once.
_networks = ip_networks.load_index(os.getenv("IP_DATA_DIR", "/tmp/ipdata"))
_rating_moderation_client = None
_last_ip_purge = 0.0
_IP_PURGE_INTERVAL = 3600
_MIN_RATING_SECRET = 32


def _rating_enabled():
    """A RATING_SECRET shorter than 32 characters counts as unset. Deployed (PROXY_SECRET
    set), a missing Turnstile key turns the form off rather than letting it run without CAPTCHA."""
    if PROXY_SECRET and not os.getenv("TURNSTILE_SECRET_KEY"):
        return False
    return bool(RATING_SECRET) and len(RATING_SECRET) >= _MIN_RATING_SECRET


def _rating_moderation_score(texts):
    """moderation.score_texts through a client that gives up after 5 s, so a slow API holds the rating."""
    global _rating_moderation_client
    if _rating_moderation_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise moderation.ModerationUnavailable("OPENAI_API_KEY is not set")
        from openai import OpenAI
        _rating_moderation_client = OpenAI(api_key=api_key, timeout=5, max_retries=0)
    return moderation.score_texts(texts, client=_rating_moderation_client)


def _rating_limit_key():
    token = request.cookies.get(rating_identity.DEVICE_COOKIE, "")
    if not rating_identity.valid_device_token(token):
        body = request.get_json(silent=True)
        token = body.get("deviceToken") if isinstance(body, dict) else None
    if _rating_enabled() and rating_identity.valid_device_token(token):
        return rating_identity.keyed_hash(RATING_SECRET, "device", token) + "|" + get_real_ip()
    return get_real_ip()


def _network_type():
    """The client's network type, looked up once per request."""
    if "network_type" not in g:
        g.network_type = _networks.network_type(get_real_ip())
    return g.network_type


def _shared_network():
    """Campus and Private Relay addresses are shared by many students, so the IP-only limit skips them."""
    return _network_type() in ("campus", "relay")


RATINGS_UNAVAILABLE = "Ratings are not available right now"


def _rating_unavailable():
    return jsonify({"error": RATINGS_UNAVAILABLE}), 503


def _rating_response(body, status, token=None):
    resp = make_response(jsonify(body), status)
    resp.headers["Cache-Control"] = "no-store"
    if token:
        resp.set_cookie(rating_identity.DEVICE_COOKIE, token, max_age=rating_identity.DEVICE_MAX_AGE,
                        httponly=True, secure=True, samesite="Lax", path="/api")
    return resp


def _device_token(mirror):
    """(token, minted_now): the cookie, else a valid localStorage mirror, else a new one."""
    for candidate in (request.cookies.get(rating_identity.DEVICE_COOKIE), mirror):
        if rating_identity.valid_device_token(candidate):
            return candidate, False
    return rating_identity.new_device_token(), True


@app.route("/api/rate/start")
def rate_start():
    if not _rating_enabled():
        return _rating_unavailable()
    now = datetime.now(timezone.utc)
    # The localStorage mirror comes in a header, not the query string, so it stays out of access logs.
    token, minted = _device_token(request.headers.get("X-Rmh-Device"))
    device_hash = rating_identity.keyed_hash(RATING_SECRET, "device", token)
    opened = rating_identity.sign_opened(RATING_SECRET, int(now.timestamp()), device_hash, minted)
    counter = ratings.huskies_this_term(query_one, now)
    return _rating_response({"opened": opened, "deviceToken": token, "counter": counter}, 200, token)


@app.route("/api/rate/professors/<slug>")
def rate_professor(slug):
    if not _rating_enabled():
        return _rating_unavailable()
    if not ratings.professor_exists(slug, query_one):
        return _rating_response({"error": "Professor not found"}, 404)
    # The cookie doesn't reach a cross-site API, so the localStorage mirror comes in a header too.
    token = request.cookies.get(rating_identity.DEVICE_COOKIE)
    if not rating_identity.valid_device_token(token):
        token = request.headers.get("X-Rmh-Device")
    device_hash = (rating_identity.keyed_hash(RATING_SECRET, "device", token)
                   if rating_identity.valid_device_token(token) else None)
    return _rating_response(ratings.professor_context(slug, device_hash, query), 200)


@app.route("/api/rate", methods=["POST"])
@limiter.limit("20 per hour", key_func=_rating_limit_key)
@limiter.limit("300 per hour", exempt_when=_shared_network)
def rate_submit():
    global _last_ip_purge
    # 1. Secret
    if not _rating_enabled():
        return _rating_unavailable()
    body = request.get_json(silent=True)
    now = datetime.now(timezone.utc)

    # 2. Honeypot: look accepted, verify and store nothing
    if isinstance(body, dict) and body.get("website"):
        return _rating_response({"ok": True, "counter": ratings.huskies_this_term(query_one, now)}, 200)

    # 3. Validation
    clean, err = rating_checks.validate_submission(body, now.year)
    if err:
        return _rating_response({"error": err}, 400)

    # 4. Turnstile
    failed = _turnstile_gate(body.get("turnstileToken"), "rate", RATINGS_UNAVAILABLE)
    if failed:
        status, error = failed
        return _rating_response({"error": error}, status)

    # 5. Existence
    if clean["professor_slug"] and not ratings.professor_exists(clean["professor_slug"], query_one):
        return _rating_response({"error": "Unknown professor"}, 400)
    new_course = None
    if not ratings.course_exists(clean["course_code"], query_one):
        if not clean["new_course_name"]:
            return _rating_response({"error": "Unknown course code: give the course name"}, 400)
        new_course = clean["new_course_name"]

    # 6. Device, hashes, network, fill time
    device, minted_now = _device_token(body.get("deviceToken"))
    device_hash = rating_identity.keyed_hash(RATING_SECRET, "device", device)
    ip = get_real_ip()
    ip_hash = rating_identity.keyed_hash(RATING_SECRET, "ip", ip)
    prefix = rating_identity.ip_prefix(ip)
    prefix_hash = rating_identity.keyed_hash(RATING_SECRET, "net", prefix) if prefix else None
    network_type = _network_type()
    fill_seconds, opened_minted = rating_identity.read_opened(
        RATING_SECRET, body.get("opened"), device_hash, int(now.timestamp()))

    # A well-formed token the client picked is no returning device unless it already has a rating.
    new_device = minted_now or opened_minted or not ratings.device_seen(device_hash, query_one)

    # 7. Moderation: a blocked comment stops here, before anything is written
    moderation_action = rating_checks.moderate(clean["comment"], score=_rating_moderation_score)
    if moderation_action == "block":
        return _rating_response({"error": "comment_blocked"}, 422, device)

    # 8. Pending professor / course. No team email: invented names cost nothing to
    # submit, so one email each could flood the inbox and the Resend quota the
    # feedback form shares. Reviewers find them with `review_ratings.py list`.
    pending_professor_id = pending_course_id = None
    if clean["new_professor"]:
        name, dept = clean["new_professor"]["name"], clean["new_professor"]["department"]
        pending_professor_id, _ = ratings.pending_professor(name, dept, query_one, _write)
    if new_course:
        pending_course_id, _ = ratings.pending_course(clean["course_code"], new_course, query_one, _write)

    # 9. Replace-or-insert, holds and bursts
    key = ratings.rating_key(clean, pending_professor_id, pending_course_id)
    existing = ratings.existing_rating(device_hash, key, query_one)
    chash = rating_checks.comment_hash(clean["comment"])
    duplicate = ratings.duplicate_comment(chash, existing["id"] if existing else None, query_one)
    near = ratings.near_duplicate_ids(clean["comment"], key, existing["id"] if existing else None, query, now)
    skew = ratings.skew_week(key, clean["rating"], new_device, existing["id"] if existing else None,
                             query_one, now)
    bursts = ratings.burst_reasons(key, ip_hash, prefix_hash, network_type, query_one, now)
    # A pending professor or course counts nowhere until a reviewer approves it, so only
    # a known pair is checked against who Banner and RMP have teaching the course.
    unverified = (bool(key["professor_slug"]) and bool(key["course_code"])
                  and not ratings.pair_taught(key["professor_slug"], key["course_code"], query_one))
    # A reviewer took this rating's comment down (review_ratings.py remove-comment): the mark
    # stays on the row, and any comment it carries again waits for review.
    removed = bool(existing) and "comment_removed" in (existing["hold_reasons"] or "").split(",")
    silent = ratings.flagged(device_hash, ip_hash, network_type, query_one, now)
    status, reasons = rating_checks.assess(fill_seconds, network_type, bursts, duplicate, moderation_action,
                                           edit=bool(existing) and existing["status"] == "accepted",
                                           unverified_pair=unverified,
                                           comment_removed=removed and bool(clean["comment"]),
                                           near_duplicate=bool(near), skew_week=skew,
                                           silent_hold=silent)
    if removed and "comment_removed" not in reasons:
        reasons.append("comment_removed")
    row = {
        **key,
        "term_label": clean["term_label"], "rating": clean["rating"], "difficulty": clean["difficulty"],
        "hours": clean["hours"],
        "grade": clean["grade"], "comment": clean["comment"] or None, "comment_hash": chash,
        "status": status, "hold_reasons": ",".join(reasons) or None,
        "device_hash": device_hash, "new_device": new_device,
        "ip_hash": ip_hash, "ip_prefix_hash": prefix_hash, "network_type": network_type,
        "fill_seconds": fill_seconds, "collection": "turnstile+device",
    }
    ratings.save_rating(row, existing, _write)
    held = ratings.hold_burst(bursts, key, ip_hash, prefix_hash, _write, now) if bursts else set()
    if near:
        ratings.hold_matches(near, "near_duplicate", device_hash, ip_hash, prefix_hash, network_type, _write)
    if skew:
        ratings.hold_skew_week(key, _write, now)
    # The page shows student reviews live. Any save can change it: a new review, an edit,
    # or an accepted review edited into a held one, whose old comment must come down. A burst
    # also holds reviews on other professors. Dropped after the hold, so no request between
    # the two writes re-caches rows that are about to be held.
    pages = held | {key["professor_slug"]} if key.get("professor_slug") else held
    if pages:
        drop_professor_pages(pages)

    # 10. Clear old IP hashes, at most hourly per process
    if time.time() - _last_ip_purge >= _IP_PURGE_INTERVAL:
        _last_ip_purge = time.time()
        ratings.purge_ip_hashes(_write, now)

    # 11. Same body whether accepted or held
    return _rating_response({"ok": True, "counter": ratings.huskies_this_term(query_one, now)}, 200, device)


from render import render_bp
app.register_blueprint(render_bp)

if __name__ == "__main__":
    print("Starting server on port 5001...")
    app.run(debug=True, port=5001, use_reloader=True)
