"""Pure helpers for the agent-driven professor photo re-scrape.

Reuses normalization and college constants from pipeline.names (aliases from
prof_aliases) so the photo pipeline groups and matches professors exactly
like the app does.
"""
import os
import sys
import re

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from pipeline.names import normalize_name, upgrade_image_url, COLLEGE_MAP  # noqa: E402
from prof_aliases import ALIAS_MAP  # noqa: E402


def build_alias_index():
    """Build {normalized_name: equivalence_set} from ALIAS_MAP.

    ALIAS_MAP keys/values are mixed case; normalize both. Each direct pair
    (src, tgt) joins their equivalence sets so any member resolves to all.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for src, tgt in ALIAS_MAP.items():
        union(normalize_name(src), normalize_name(tgt))

    groups = {}
    for node in list(parent):
        groups.setdefault(find(node), set()).add(node)

    idx = {}
    for members in groups.values():
        for m in members:
            idx[m] = set(members)
    return idx


def aliases_for(name, idx):
    """Return the set of normalized names equivalent to `name`."""
    key = normalize_name(name)
    return set(idx.get(key, {key}))


def _parts(name):
    s = normalize_name(name)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return [p for p in s.split() if p]


def name_matches(neu_name, page_name, idx):
    """True if page_name refers to the same person as neu_name.

    Accept: exact normalized match; first+last match ignoring middle names;
    alias equivalence (either direction). Reject: surname-only, or different
    first name with no alias evidence.
    """
    neu_eq = aliases_for(neu_name, idx)
    page_norm = normalize_name(page_name)

    # Alias / exact equivalence (covers documented variants)
    if page_norm in neu_eq:
        return True
    page_eq = aliases_for(page_name, idx)
    if neu_eq & page_eq:
        return True

    np_, pp = _parts(neu_name), _parts(page_name)
    if len(np_) < 2 or len(pp) < 2:
        return False  # need at least first+last on both sides

    # first + last, ignoring middles
    return np_[0] == pp[0] and np_[-1] == pp[-1]


SKIP_PATTERNS = [
    "placeholder", "silhouette", "no-photo", "avatar",
    "generic", "blank", "mystery", "default-person", "headshot-placeholder",
    "logo", "icon", "notched-n", "nu_rgb", "seal",
    "person-banner", "featured-nav", "banner", "hero-image",
    "graduates", "graduation", "commencement", "ceremony", "group",
    "class-of", "cohort",
    "centennial", "campus", "common", "building", "aerial", "quad",
    "hall", "tulips", "entrance",
    "promo", "graphic", "spiral", "cover-",
]

# Local, photo-pipeline-only department->college mapping. Supplements
# precompute.COLLEGE_MAP (which we intentionally do NOT modify) so the photo
# run can organize the ~2,800 professors whose TRACE department strings are
# not in the app's COLLEGE_MAP. Keys are verbatim from the data, including the
# double-space artifacts left when "&" was stripped upstream.
SUPPLEMENTAL_COLLEGE_MAP = {
    # CAMD
    "Art and Design": "CAMD",
    "Theatre": "CAMD",
    "Interdisc Studies - Arts/Media": "CAMD",
    "Dean of Coll of Arts, Media": "CAMD",
    # Science
    "Chemistry  Chemical Biology": "Science",
    "Marine  Environment Sciences": "Science",
    "Interdisc Studies - Science": "Science",
    "Medical Sciences": "Science",
    # Health Sciences
    "Phys Therapy/Movemnt/Rehab Sci": "Health Sciences",
    "Public Health and Health Sci": "Health Sciences",
    "Comm Sciences  Disorders": "Health Sciences",
    "Pharmacy  Health Systems Sci": "Health Sciences",
    "Pharmaceutical Science": "Health Sciences",
    "Health Sci - Interdisciplinary": "Health Sciences",
    "Health Informatics": "Health Sciences",
    "Physician Assistant": "Health Sciences",
    "Health  Physical Education": "Health Sciences",
    # Engineering
    "Mech  Industrial Engineering": "Engineering",
    "Electrical and Comp Engineerng": "Engineering",
    "Dean of Engineering": "Engineering",
    "Civil  Environmental Engineer": "Engineering",
    "General Engineering": "Engineering",
    "Grad Engineering - Leadership": "Engineering",
    # CSSH
    "Pub Policy and Urban Affairs": "CSSH",
    "Interdisc Studies - Soc Sc/Hum": "CSSH",
    "Sociology and Anthropology": "CSSH",
    "Criminology  Criminal Justice": "CSSH",
    "Philosophy and Religion": "CSSH",
    "American Sign Language": "CSSH",
    "Dean of Coll of Soc Sci  Huma": "CSSH",
    "Cultures/Societies/Global Stds": "CSSH",
    "Lang, Literature and Culture": "CSSH",
    "Managerial Economics": "CSSH",
    # Business
    "Entrepreneurship  Innovation": "Business",
    "Finance  Insurance": "Business",
    "International Bus  Strategy": "Business",
    "Management Science": "Business",
    "Management Information Systems": "Business",
    "Technological Entrepreneurship": "Business",
    # Khoury
    "Information Assurance": "Khoury",
    "Computer  Informational Tech.": "Khoury",
    # Professional Studies
    "Counseling  Educational Psych": "Professional Studies",
}


def dept_to_college(department):
    """Map a department string to its college via precompute.COLLEGE_MAP."""
    if not department:
        return "Unknown"
    raw = re.sub(r"\s+", " ", str(department)).strip()
    if raw in COLLEGE_MAP:
        return COLLEGE_MAP[raw]
    # case-insensitive fallback
    low = raw.lower()
    for k, v in COLLEGE_MAP.items():
        if k.lower() == low:
            return v
    # Supplemental local mapping (collapse whitespace on keys to match `raw`)
    for k, v in SUPPLEMENTAL_COLLEGE_MAP.items():
        if re.sub(r"\s+", " ", k).strip() == raw:
            return v
    return "Unknown"


def is_plausible_photo_url(url):
    """Cheap sanity filter on an image URL (no network)."""
    if not url:
        return False
    low = str(url).lower()
    if any(p in low for p in SKIP_PATTERNS):
        return False
    path = low.split("?")[0]
    return any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))
