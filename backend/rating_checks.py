"""Pure decision functions for the no-login rating form: validate the body,
hash the comment for duplicate detection, check it against the free rules,
moderate it, and decide whether the rating is accepted or held."""

import hashlib
import re

import moderation
from pipeline.names import name_to_slug, normalize_name
from teaching_history import label_code

HOURS = ("0-2", "3-4", "5-7", "8-10", "10+")
GRADES = ("A", "A-", "B+", "B", "B-", "C+", "C", "C- or below")
MIN_FILL_SECONDS = 8
# An edit opens on the earlier answers, so it gets a lower floor, not none.
EDIT_MIN_FILL_SECONDS = 3
MAX_FILL_SECONDS = 7200
MAX_COMMENT = 2000
MIN_DUPLICATE_CHARS = 20
COURSE_CODE_RE = re.compile(r"^[A-Z]{2,5}\d{4}[A-Z]?$", re.ASCII)
# label_code alone would also accept "Summer Full", which is never a valid label.
TERM_RE = re.compile(r"^(Fall|Spring|Summer 1|Summer 2|Summer|Winter) (\d{4})$", re.ASCII)
# The form offers the last TERM_YEARS years by the browser's clock (TERM_YEARS in
# frontend/src/pages/rate/rateFlow.ts). this_year is UTC's, so one more year on
# each side covers a browser whose year has already or not yet turned over.
TERM_YEARS = 4


def _text(value):
    """The stripped string, or None when value isn't a string."""
    return value.strip() if isinstance(value, str) else None


def _unsafe(value):
    """True for a string PostgreSQL can't store: a NUL byte or a lone surrogate."""
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return "\x00" in value


def _validate_professor(prof):
    if not isinstance(prof, dict):
        return None, None, "professor must be an object"
    slug, name = prof.get("slug"), prof.get("name")
    if (slug in (None, "")) == (name in (None, "")):
        return None, None, "Give either a professor slug or a new professor name"
    if slug not in (None, ""):
        if _text(slug):
            return slug.strip(), None, None
        return None, None, "Invalid professor"
    name = _text(name)
    if name is None:
        return None, None, "Invalid professor name"
    name = " ".join(name.split())
    if not 3 <= len(name) <= 80 or len(name.split()) < 2:
        return None, None, "Professor name must be 3-80 characters and at least two words"
    # The name_key and slug keep only ASCII letters and digits, so "李 明" would
    # key to "" and share one pending row with every other such name.
    if len(name_to_slug(normalize_name(name)).split("-")) < 2:
        return None, None, "Professor name must be at least two words in Latin letters"
    dept = prof.get("department")
    if dept in (None, ""):
        dept = None
    elif _text(dept) is None or len(dept.strip()) > 100:
        return None, None, "Department must be at most 100 characters"
    else:
        dept = dept.strip() or None
    return None, {"name": name, "department": dept}, None


def validate_submission(body, this_year):
    """(clean, None) for a valid body, else (None, error message). Never raises."""
    if not isinstance(body, dict):
        return None, "Body must be a JSON object"
    texts = [body.get(k) for k in ("term", "hours", "grade", "comment")]
    for part in (body.get("professor"), body.get("course")):
        if isinstance(part, dict):
            texts += [part.get(k) for k in ("slug", "name", "department", "code")]
    if any(_unsafe(t) for t in texts):
        return None, "Text contains characters that can't be stored"
    slug, new_prof, err = _validate_professor(body.get("professor"))
    if err:
        return None, err

    course = body.get("course")
    if not isinstance(course, dict):
        return None, "course must be an object"
    code = course.get("code")
    code = re.sub(r"\s+", "", code).upper() if isinstance(code, str) else ""
    if not COURSE_CODE_RE.fullmatch(code):
        return None, "Invalid course code"
    course_name = course.get("name")
    if course_name in (None, ""):
        course_name = None
    elif _text(course_name) is None or not 3 <= len(course_name.strip()) <= 120:
        return None, "Course name must be 3-120 characters"
    else:
        course_name = course_name.strip()

    term = body.get("term")
    if term is not None:
        m = TERM_RE.fullmatch(term) if isinstance(term, str) else None
        if not m or label_code(term) is None or not this_year - TERM_YEARS <= int(m.group(2)) <= this_year + 1:
            return None, "Invalid term"

    rating = body.get("rating")
    if type(rating) is not int or not 1 <= rating <= 5:
        return None, "Rating must be a whole number from 1 to 5"
    difficulty = body.get("difficulty")  # None from a page still on the form from before the question
    if difficulty is not None and (type(difficulty) is not int or not 1 <= difficulty <= 5):
        return None, "Difficulty must be a whole number from 1 to 5"
    hours = body.get("hours")
    if not isinstance(hours, str) or hours not in HOURS:
        return None, "Invalid hours"
    grade = body.get("grade")
    if grade is not None and (not isinstance(grade, str) or grade not in GRADES):
        return None, "Invalid grade"

    comment = body.get("comment")
    if comment is None:
        comment = ""
    elif not isinstance(comment, str):
        return None, "Comment must be text"
    comment = comment.strip()
    if len(comment) > MAX_COMMENT:
        return None, f"Comment must be at most {MAX_COMMENT} characters"

    return {
        "professor_slug": slug, "new_professor": new_prof,
        "course_code": code, "new_course_name": course_name,
        "term_label": term, "rating": rating, "difficulty": difficulty, "hours": hours, "grade": grade,
        "comment": comment,
    }, None


def normalize_comment(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def comment_hash(text):
    """SHA-256 of the normalized comment, or None when it's too short to compare."""
    norm = normalize_comment(text)
    if len(norm) < MIN_DUPLICATE_CHARS:
        return None
    return hashlib.sha256(norm.encode()).hexdigest()


# Free checks that run before any model call (server.rate_submit): each matches
# something a course review never needs. A match is the same 422 as a model block.
_TLD = r"(?:com|net|org|io|ly|gg|me|co|xyz|info|biz|app|link|site|shop|store|online|tv|us|ai)"
_RULES = (
    # Before the domain rule, which an address's domain also matches.
    ("email", re.compile(r"\b[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b", re.I)),
    ("email", re.compile(r"\b[\w.+-]+\s*(?:\(\s*at\s*\)|\[\s*at\s*\])\s*[a-z0-9-]+", re.I)),
    ("link", re.compile(r"https?://|\bwww\s*\.\s*\w", re.I)),
    # Lowercase top-level domain only, so "ASP.NET" passes.
    ("link", re.compile(rf"\b[A-Za-z0-9][A-Za-z0-9-]*\.{_TLD}\b(?!\.?\w)")),
    ("link", re.compile(rf"\b\w+\s*(?:\(\s*dot\s*\)|\[\s*dot\s*\]|\s+dot\s+){_TLD}\b", re.I)),
    ("link", re.compile(r"\bt\.me/|\bdiscord\.gg\b|\bbit\.ly\b", re.I)),
    ("promo", re.compile(r"\b(?:promo|coupon|discount|referral|invite)\s+codes?\b"
                         r"|\buse\s+(?:my\s+)?code\b", re.I)),
    ("phone", re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?![\d-])")),
    # No "Dr": "CHEM 2311 Organic Chemistry Dr Smith" names a course and professor.
    ("address", re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
                           r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Drive|Ct|Court|"
                           r"Pl|Place|Ter|Terrace|Pkwy|Parkway|Hwy|Highway)\b")),
)
# Eight consonants in a row (y counts as a vowel), once stretched letters are
# folded ("boringgggg"), is past English words and texting shorthand ("pwrpnts");
# home-row and bottom-row runs catch mashing that happens to hit a vowel.
_MASH = re.compile(r"[bcdfghjklmnpqrstvwxz]{8,}|asdf|sdfg|dfgh|fghj|ghjk|hjkl|zxcv|xcvb", re.I)
_STRETCHED = re.compile(r"(\w)\1+", re.I)


def rule_block(comment):
    """The first rule the comment breaks ("link", "promo", "phone", "email",
    "address", "mash"), or None. Pure; tuned on the RMP comments so a real
    review almost never matches."""
    for reason, pattern in _RULES:
        if pattern.search(comment):
            return reason
    if _MASH.search(_STRETCHED.sub(r"\1", comment)):
        return "mash"
    return None


def moderate(comment, score=moderation.score_texts):
    """None for an empty comment, else "allow" | "review" | "block", or
    "unavailable" when the scorer fails for any reason."""
    if not comment.strip():
        return None
    try:
        return score([comment])[0].action
    except Exception:
        return "unavailable"


def comment_check_fields(action, reason, now):
    """ratings.CHECK_COLUMNS for new comment text.

    action: the model's "allow" or "review", "unavailable" when the call failed, or
    why no call was made: "over_budget", "duplicate" or "burst". A failed or
    over-budget check is due for moderate_queue.py now; a duplicate or burst is
    never queued, and the reviewer reads it as not yet checked.
    """
    if action in ("allow", "review"):
        return {"comment_check": action, "comment_check_reason": reason, "comment_check_attempts": 1,
                "comment_next_check_at": None, "comment_checked_at": now}
    return {"comment_check": "unchecked", "comment_check_reason": reason or action,
            "comment_check_attempts": int(action == "unavailable"),
            "comment_next_check_at": now if action in ("unavailable", "over_budget") else None,
            "comment_checked_at": None}


def assess(fill_seconds, network_type, bursts, duplicate_comment, edit=False,
           unverified_pair=False):
    """("held", reasons) | ("accepted", []).

    Moderation plays no part: a blocked comment never gets here, and a flagged or
    unchecked one waits for approve-comment without holding the rating's numbers.
    Ratings held as moderation_review or moderation_unavailable before that stay held.

    edit: this replaces an accepted rating. The form prefills the earlier answers,
    so a quick update is normal and only has to clear EDIT_MIN_FILL_SECONDS.
    unverified_pair: neither Banner nor RMP has this professor teaching this course.
    """
    reasons = []
    if fill_seconds is None:
        reasons.append("no_timer")
    elif fill_seconds < (EDIT_MIN_FILL_SECONDS if edit else MIN_FILL_SECONDS):
        reasons.append("too_fast")
    elif fill_seconds > MAX_FILL_SECONDS:
        reasons.append("stale")
    if network_type == "datacenter":
        reasons.append("datacenter")
    reasons.extend(bursts)
    if unverified_pair:
        reasons.append("unverified_pair")
    if duplicate_comment:
        reasons.append("duplicate_comment")
    return ("held", reasons) if reasons else ("accepted", [])
