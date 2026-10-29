"""
NEU Faculty Headshot Scraper (v3 — Directory-First, Fast)

Three-phase approach:
  Phase 1: Scrape college directory listing pages (~220 pages → ~4700 faculty
           with photos already embedded). Build multiple indexes for matching.
  Phase 1.5: For directory-matched professors without photos, fetch their
             known profile page directly (1 request each).
  Phase 2: For remaining professors whose department maps to a known college,
           try ONE slug-based URL on their department's subdomain only.

Reads professor names from rmp_professors.csv.
Outputs: professor_photos.csv (name, image_url, source_page)

Photo updates are manual; no workflow runs them, and the weekly refresh adds
new professors with no photo (pipeline/roster.py). The full sequence:
  1. photo_scrape.py                 -> professor_photos.csv
  2. compute_focus.py                -> adds focus_x / focus_y
  3. set image_url / focus_x / focus_y on the matching professors rows. No script
     does this: pipeline/seed.py copied them from professors_catalog once, and
     load_rmp.py loads the CSV into the separate professor_photos table, which the
     site never reads. Names there are not unique, so update by slug, by hand:
       UPDATE professors SET image_url = %s, focus_x = %s, focus_y = %s WHERE slug = %s;
  4. backend/photo_thumbs.py         -> small WebP copies in frontend/public/photos/
                                        (--refresh if photos changed at the same URL)
  5. commit frontend/public/photos/ and deploy
Skipping step 4 only means the new photos load at full size.

Usage:
    python photo_scrape.py
    python photo_scrape.py --workers 10
    python photo_scrape.py --limit 50
    python photo_scrape.py --skip-directories   # slug-only mode
"""

import csv
import os
import re
import argparse
import unicodedata
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ---------------------------------------------------------------------------
# College directory configurations
# ---------------------------------------------------------------------------

DIRECTORY_CONFIGS = [
    {"subdomain": "www.khoury", "dir_path": "/people/"},
    {"subdomain": "cos",        "dir_path": "/people/"},
    {"subdomain": "damore-mckim","dir_path": "/people/"},
    {"subdomain": "camd",       "dir_path": "/people/"},
    {"subdomain": "bouve",      "dir_path": "/directory/"},
    {"subdomain": "cssh",       "dir_path": "/faculty/"},
    {"subdomain": "law",        "dir_path": "/faculty/"},
    {"subdomain": "cps",        "dir_path": "/faculty/"},
    {"subdomain": "coe",        "dir_path": "/faculty-staff-directory/"},
]

# Department keyword → subdomain mapping (uses substring matching, not exact)
# Each tuple: (keyword_in_department, [subdomains], path_pattern)
DEPT_KEYWORD_MAP = [
    # Khoury
    (["computer sci", "information sci", "cybersec", "data sci", "computer eng",
      "computer & info"], "www.khoury", "/people/"),
    # Engineering — MUST be before COS so "Chemical Engineering" matches here
    (["engineer", "mechanical", "electrical", "civil", "chemical eng",
      "bioengin", "dean of eng"], "coe", "/people/"),
    # COS — use "chemistry" not "chem" to avoid matching "Chemical Engineering"
    (["math", "physics", "chemistry", "chem bio", "biology", "biochem",
      "environment", "marine", "neurosci", "interdisc studies - sci"], "cos", "/people/"),
    # D'Amore-McKim
    (["business", "finance", "account", "marketing", "management",
      "entrepreneur", "supply chain"], "damore-mckim", "/people/"),
    # CAMD
    (["art", "communication", "journalism", "music", "design", "theater",
      "theatre", "architecture", "media"], "camd", "/people/"),
    # Bouve
    (["health", "nursing", "pharmac", "physical therap", "speech",
      "rehab", "counsel", "movem"], "bouve", "/directory/"),
    # CSSH
    (["politic", "econom", "history", "psychol", "sociol", "philosoph",
      "english", "writing", "criminal", "linguist", "language", "anthropol",
      "pub policy", "urban", "interdis", "cultural"], "cssh", "/faculty/"),
    # Law
    (["law"], "law", "/faculty/"),
    # CPS
    (["education", "professional", "special program"], "cps", "/faculty/"),
]

# Images to skip — banners, placeholders, group/campus photos, etc.
SKIP_PATTERNS = [
    # Placeholders
    "placeholder", "silhouette", "no-photo", "avatar",
    "generic", "blank", "mystery", "default-person", "headshot-placeholder",
    # Logos and icons
    "logo", "icon", "notched-n", "nu_rgb", "seal",
    # Nav/banner images
    "person-banner", "featured-nav", "banner", "hero-image",
    # Group/event photos
    "graduates", "graduation", "commencement", "ceremony", "group",
    "class-of", "cohort",
    # Campus/building photos
    "centennial", "campus", "common", "building", "aerial", "quad",
    "hall", "tulips", "entrance",
    # Promotional/decorative
    "promo", "graphic", "spiral", "cover-",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_name(name):
    """Normalize a name for matching: lowercase, ASCII, single spaces."""
    s = str(name).strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def name_to_key(name):
    """Create a matching key: no punctuation."""
    s = normalize_name(name)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return s


def name_to_slug(name):
    """Convert 'Jonathan Bell' → 'jonathan-bell'."""
    s = normalize_name(name)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s


def slug_variations(name):
    """Generate slug variations for a name.

    Includes both first-last and last-first formats since some colleges
    (e.g., COE) use last-first URL slugs.
    """
    slugs = set()
    base = name_to_slug(name)
    slugs.add(base)

    parts = normalize_name(name).split()
    if len(parts) >= 2:
        # first-last (skip middle names)
        slugs.add(re.sub(r'[^a-z0-9]+', '-', f"{parts[0]} {parts[-1]}").strip('-'))
        # last-first (COE format)
        slugs.add(re.sub(r'[^a-z0-9]+', '-', f"{parts[-1]} {parts[0]}").strip('-'))
    if len(parts) >= 3:
        # first-middle-last
        slugs.add(re.sub(r'[^a-z0-9]+', '-', f"{parts[0]} {parts[1]} {parts[-1]}").strip('-'))
        # all-after-first-then-first (COE multi-word last name)
        # e.g. "Hande Musdal Ondemir" → "musdal-ondemir-hande"
        rest = ' '.join(parts[1:])
        slugs.add(re.sub(r'[^a-z0-9]+', '-', f"{rest} {parts[0]}").strip('-'))

    return list(slugs)


def is_valid_photo(url):
    """Check if URL looks like an actual headshot, not a placeholder."""
    if not url:
        return False
    lower = url.lower()
    if any(p in lower for p in SKIP_PATTERNS):
        return False
    path = lower.split('?')[0]
    if not any(path.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
        return False
    return True


def make_absolute(url, page_url):
    """Convert a potentially relative URL to absolute."""
    if not url:
        return url
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        parsed = urlparse(page_url)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    if not url.startswith('http'):
        return urljoin(page_url, url)
    return url


def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
    })
    return session


def dept_to_subdomain(department):
    """Map a department name to a subdomain + path using keyword matching."""
    dept_lower = department.lower()
    for keywords, subdomain, path in DEPT_KEYWORD_MAP:
        if any(kw in dept_lower for kw in keywords):
            return subdomain, path
    return None, None


# ---------------------------------------------------------------------------
# Phase 1: Scrape directory listing pages
# ---------------------------------------------------------------------------

def _find_card_for_link(link):
    """Walk up from a link to find its enclosing card container."""
    container = link
    for _ in range(7):
        container = container.parent
        if not container or container.name in ('body', 'html', '[document]'):
            return None
        if container.name == 'article':
            return container
        cls = ' '.join(container.get('class') or []).lower()
        is_card = False
        if container.name == 'li':
            is_card = True
        elif container.name == 'div' and (
            'card' in cls or 'member' in cls or 'profile' in cls
        ):
            is_card = True
        elif container.name == 'div' and ('person' in cls or 'directory' in cls):
            if container.find(['h2', 'h3', 'h4']):
                is_card = True
        if is_card:
            return container
    return None


def scrape_directory_page(session, url):
    """Scrape one directory listing page.

    Returns: (list of {name, photo_url, profile_url}, next_page_url or None)
    """
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return [], None

        if urlparse(resp.url).netloc != urlparse(url).netloc:
            return [], None

        soup = BeautifulSoup(resp.text, 'html.parser')
        people = []
        profile_pattern = re.compile(
            r'/(people|faculty|directory|person|student)/[a-z0-9][\w-]+/?$', re.I
        )

        seen_urls = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            abs_href = make_absolute(href, resp.url)

            path = urlparse(abs_href).path.rstrip('/')
            if not profile_pattern.search(path):
                continue

            if abs_href in seen_urls:
                continue
            seen_urls.add(abs_href)

            card = _find_card_for_link(link)

            # --- Extract name ---
            name = ''
            heading = link.find(['h2', 'h3', 'h4'])
            if heading:
                name = heading.get_text(strip=True)
            if not name:
                name = link.get_text(strip=True)

            name = re.sub(
                r'\b(Read\s+bio|View\s+(Bio|Profile|Path)|See\s+(Path|Bio))\b',
                '', name, flags=re.I
            ).strip()
            name = name.replace('\u201c', '').replace('\u201d', '').replace('"', '')

            if card and (not name or len(name) < 3):
                for h in card.find_all(['h2', 'h3', 'h4']):
                    candidate = h.get_text(strip=True)
                    if candidate and len(candidate) >= 3 and not re.search(
                        r'\b(program|department|center|office|view|read)\b', candidate, re.I
                    ):
                        name = candidate
                        break

            if not name or len(name) < 3 or len(name) > 80:
                continue
            if name.lower() in ('next', 'previous', 'show all', 'load more'):
                continue

            # --- Extract photo ---
            photo_url = ''
            if card:
                img = card.find('img')
                if img:
                    src = img.get('src', '') or img.get('data-src', '')
                    src = make_absolute(src, resp.url)
                    if is_valid_photo(src):
                        photo_url = src

            people.append({
                'name': name,
                'photo_url': photo_url,
                'profile_url': abs_href,
            })

        # Find next page URL
        next_url = None
        next_link = (
            soup.find('a', class_=re.compile(r'\bnext\b', re.I))
            or soup.find('a', attrs={'aria-label': re.compile(r'next', re.I)})
        )
        if not next_link:
            for a in soup.find_all('a', href=True):
                if re.search(r'^Next\b', a.get_text(strip=True), re.I):
                    next_link = a
                    break
        if next_link and next_link.get('href'):
            next_url = make_absolute(next_link['href'], resp.url)

        return people, next_url

    except Exception:
        return [], None


def scrape_all_directories(session, workers=10):
    """Scrape all college directory pages.

    Returns:
        directory_map: name_key → {name, photo_url, profile_url}
        slug_index:    slug → {name, photo_url, profile_url}
        lastname_index: last_name → [{name, photo_url, profile_url}, ...]
    """
    print("\n  Phase 1: Scraping college directory pages...")

    def scrape_one_college(config):
        subdomain = config['subdomain']
        dir_path = config['dir_path']
        url = f"https://{subdomain}.northeastern.edu{dir_path}"
        college_people = []

        for _ in range(100):
            people, next_url = scrape_directory_page(session, url)
            college_people.extend(people)
            if not next_url or not people:
                break
            url = next_url
 
        return subdomain, college_people

    college_results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scrape_one_college, c): c for c in DIRECTORY_CONFIGS}
        pbar = tqdm(total=len(DIRECTORY_CONFIGS), desc="  Directories", unit=" college")

        for future in as_completed(futures):
            try:
                subdomain, people = future.result()
                college_results.append((subdomain, people))
                pbar.set_postfix_str(f"{subdomain}: {len(people)} people")
            except Exception:
                pass
            pbar.update(1)
        pbar.close()

    # Build indexes
    directory_map = {}   # name_key → entry
    slug_index = {}      # slug_from_url → entry
    lastname_index = {}  # last_name → [entries]
    total_people = 0
    total_with_photos = 0

    for _, people in college_results:
        for person in people:
            key = name_to_key(person['name'])
            if not key:
                continue
            total_people += 1

            # Prefer entries with photos
            existing = directory_map.get(key)
            if existing and existing['photo_url'] and not person['photo_url']:
                continue
            directory_map[key] = person
            if person['photo_url']:
                total_with_photos += 1

            # Slug index: extract slug from profile URL
            profile_path = urlparse(person['profile_url']).path.rstrip('/')
            slug = profile_path.split('/')[-1] if profile_path else ''
            if slug:
                existing_slug = slug_index.get(slug)
                if not existing_slug or (person['photo_url'] and not existing_slug['photo_url']):
                    slug_index[slug] = person

            # Last name index
            name_parts = key.split()
            if name_parts:
                last = name_parts[-1]
                lastname_index.setdefault(last, []).append(person)

    print(f"  Found {total_people} people in directories ({total_with_photos} with photos)")
    print(f"  Built indexes: {len(slug_index)} slugs, {len(lastname_index)} last names")
    return directory_map, slug_index, lastname_index


# ---------------------------------------------------------------------------
# Phase 2: Slug-based fallback for individual profile pages
# ---------------------------------------------------------------------------

def extract_photo_from_profile(html, page_url):
    """Extract the professor headshot URL from an individual profile page.

    Only returns the first valid uploaded image that is:
    - In wp-content/uploads (not theme assets)
    - At least 150px on both sides
    - NOT inside site nav/header/footer (by tag or site-level class)
    - NOT a known placeholder, group photo, or campus image
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Classes that indicate SITE-LEVEL nav/chrome (not content sections).
    # We use word-boundary matching to avoid false positives like
    # "single-people__header-figure" which is a content area.
    skip_class_patterns = re.compile(
        r'\b(site-header|site-footer|site-nav|mega-menu|main-menu'
        r'|primary-nav|widget-area|sidebar)\b', re.I
    )

    for img in soup.find_all('img'):
        src = img.get('src', '') or img.get('data-src', '')
        if not src:
            continue

        if 'wp-content/uploads' not in src and 'pcdn.co' not in src:
            continue

        width = img.get('width')
        height = img.get('height')
        if width and height:
            try:
                w, h = int(width), int(height)
                if w < 150 and h < 150:
                    continue
            except ValueError:
                pass

        # Skip images inside site-level chrome (nav elements, mega-menus).
        # Stop checking at body/html level — body often has theme classes
        # like "mega-menu-primary" that would cause false positives.
        in_skip_section = False
        for depth, parent in enumerate(img.parents):
            if depth > 5:
                break
            if parent.name in ('body', 'html', '[document]'):
                break
            if parent.name == 'nav':
                in_skip_section = True
                break
            parent_cls = ' '.join(parent.get('class') or []).lower()
            parent_id = (parent.get('id') or '').lower()
            if skip_class_patterns.search(parent_cls) or skip_class_patterns.search(parent_id):
                in_skip_section = True
                break
        if in_skip_section:
            continue

        src = make_absolute(src, page_url)
        if not is_valid_photo(src):
            continue

        return src

    return None


def try_slug_lookup(session, name, department):
    """Try to find a professor's photo — ONE targeted request per slug.

    Only tries the professor's department subdomain with its path pattern.
    """
    slugs = slug_variations(name)
    subdomain, path_pattern = dept_to_subdomain(department)
    if not subdomain:
        return None, None

    for slug in slugs:
        url = f"https://{subdomain}.northeastern.edu{path_pattern}{slug}/"
        try:
            resp = session.get(url, timeout=8, allow_redirects=True)
            if resp.status_code != 200:
                continue
            if urlparse(resp.url).netloc != urlparse(url).netloc:
                continue

            photo_url = extract_photo_from_profile(resp.text, resp.url)
            if photo_url:
                return photo_url, resp.url
        except Exception:
            continue

    return None, None


# ---------------------------------------------------------------------------
# Loading professors & matching
# ---------------------------------------------------------------------------

def load_professors(data_dir):
    """Load unique professor names + departments from CSVs."""
    profs = {}

    rmp_path = os.path.join(data_dir, "rmp_professors.csv")
    if os.path.exists(rmp_path):
        with open(rmp_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                name = str(row.get('name', '')).strip()
                dept = str(row.get('department', '')).strip()
                if name:
                    key = normalize_name(name)
                    if key not in profs:
                        profs[key] = {'name': name, 'department': dept}

    return list(profs.values())


def match_prof_to_directory(prof, directory_map, slug_index, lastname_index):
    """Try to match a professor to a directory entry using multiple strategies."""
    name = prof['name']

    # Strategy 1: Exact key match
    key = name_to_key(name)
    if key in directory_map:
        return directory_map[key]

    parts = normalize_name(name).split()

    # Strategy 2: first-last match (skip middle names in our name)
    if len(parts) >= 3:
        first_last = re.sub(r'[^a-z0-9 ]', '', f"{parts[0]} {parts[-1]}")
        if first_last in directory_map:
            return directory_map[first_last]

    # Strategy 3: Slug match — check if any slug variation exists in the slug index
    for slug in slug_variations(name):
        if slug in slug_index:
            return slug_index[slug]

    # Strategy 4: Last name match with first-name similarity.
    # For common last names (>3 candidates), ONLY allow exact first-name matches
    # to avoid false positives (Xiaotao→Xiaoping, Zhehui→Zheng, etc.)
    # For uncommon last names (≤3 candidates), allow prefix/nickname matching.
    if len(parts) >= 2:
        first = re.sub(r'[^a-z]', '', parts[0])
        last = re.sub(r'[^a-z]', '', parts[-1])
        if len(first) >= 2:
            candidates = lastname_index.get(last, [])
            is_common = len(candidates) > 3

            best = None
            best_score = 0
            for entry in candidates:
                entry_parts = name_to_key(entry['name']).split()
                if len(entry_parts) < 2:
                    continue
                entry_first = entry_parts[0]
                entry_last = entry_parts[-1]
                if entry_last != last:
                    continue

                score = 0
                if first == entry_first:
                    score = 100  # exact match — always allowed
                elif not is_common:
                    # Only do fuzzy matching for uncommon last names
                    if first.startswith(entry_first) or entry_first.startswith(first):
                        score = 50 + min(len(first), len(entry_first))
                    elif (first[0] == entry_first[0]
                            and (len(entry_first) <= 4 or len(first) <= 4)):
                        score = 10  # nickname: Dee/Denise

                if score > best_score:
                    best_score = score
                    best = entry

            if best and best_score >= 10:
                return best

    # Strategy 5: Check if directory has entry with extra/fewer name parts
    if len(parts) == 2:
        first = re.sub(r'[^a-z]', '', parts[0])
        last = re.sub(r'[^a-z]', '', parts[-1])
        if len(first) >= 3:
            for dir_key, entry in directory_map.items():
                dir_parts = dir_key.split()
                if len(dir_parts) >= 2:
                    df = dir_parts[0]
                    dl = dir_parts[-1]
                    if dl == last and first[:3] == df[:3]:
                        return entry

    return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def scrape_photos(profs, workers=15, limit=None, skip_directories=False):
    """Full scraping pipeline."""
    if limit:
        profs = profs[:limit]

    session = make_session()
    results = []

    # Phase 1: Directory scraping
    if not skip_directories:
        directory_map, slug_index, lastname_index = scrape_all_directories(
            session, workers=min(workers, 8)
        )
    else:
        directory_map, slug_index, lastname_index = {}, {}, {}

    # Match professors against directory indexes
    unmatched = []
    matched_no_photo = []
    dir_found = 0

    print(f"\n  Matching {len(profs)} professors against directory...")
    for prof in profs:
        match = match_prof_to_directory(prof, directory_map, slug_index, lastname_index)
        if match and match['photo_url']:
            results.append({
                'name': prof['name'],
                'image_url': match['photo_url'],
                'source_page': match['profile_url'],
            })
            dir_found += 1
        elif match and match['profile_url']:
            matched_no_photo.append((prof, match['profile_url']))
        else:
            unmatched.append(prof)

    print(f"  Phase 1 matched: {dir_found}/{len(profs)} professors with photos")
    print(f"  ({len(matched_no_photo)} matched without photo, {len(unmatched)} unmatched)")

    # Phase 1.5: Fetch profile pages for matched-but-no-photo professors
    if matched_no_photo:
        print(f"\n  Phase 1.5: Fetching {len(matched_no_photo)} known profile pages...")
        profile_found = 0
        pbar = tqdm(total=len(matched_no_photo), desc="  Profiles", unit=" prof")

        def fetch_profile(item):
            prof, profile_url = item
            try:
                resp = session.get(profile_url, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    photo_url = extract_photo_from_profile(resp.text, resp.url)
                    if photo_url:
                        return prof, photo_url, resp.url
            except Exception:
                pass
            return prof, None, None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch_profile, item): item for item in matched_no_photo}
            for future in as_completed(futures):
                try:
                    prof, photo_url, source_page = future.result()
                    if photo_url:
                        results.append({
                            'name': prof['name'],
                            'image_url': photo_url,
                            'source_page': source_page,
                        })
                        profile_found += 1
                    else:
                        unmatched.append(prof)
                except Exception:
                    pass
                pbar.update(1)
        pbar.close()
        print(f"  Phase 1.5 found: {profile_found} additional professors")

    # Phase 2: Targeted slug lookup — only try professor's OWN college subdomain
    # Filter to only professors with a known department mapping
    phase2_profs = [p for p in unmatched if dept_to_subdomain(p['department'])[0]]
    skipped = len(unmatched) - len(phase2_profs)

    if phase2_profs:
        print(f"\n  Phase 2: Slug lookup for {len(phase2_profs)} professors "
              f"(skipped {skipped} with unknown dept)...")
        slug_found = 0
        pbar = tqdm(total=len(phase2_profs), desc="  Slug lookup", unit=" prof")

        def lookup_one(prof):
            return prof, try_slug_lookup(session, prof['name'], prof['department'])

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(lookup_one, p): p for p in phase2_profs}

            for future in as_completed(futures):
                try:
                    prof, (photo_url, source_page) = future.result()
                    if photo_url:
                        results.append({
                            'name': prof['name'],
                            'image_url': photo_url,
                            'source_page': source_page,
                        })
                        slug_found += 1
                except Exception:
                    pass
                pbar.update(1)

        pbar.close()
        print(f"  Phase 2 found: {slug_found} additional professors")
    else:
        print(f"\n  Phase 2: No professors with known departments to look up")

    total = len([r for r in results if r.get('image_url')])
    print(f"\n  Total: {total}/{len(profs)} professors with photos")
    return results


def save_csv(results, output_path):
    """Save results to CSV, rejecting duplicate image URLs.

    If the same image URL was assigned to multiple professors, it's almost
    certainly a shared/wrong image (campus photo, nav image, etc.), so we
    drop ALL entries with that URL.
    """
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    with_photos = [r for r in results if r['image_url']]

    # Drop image URLs shared by multiple professors.
    # - 3+ professors sharing a URL = always wrong (group/campus/promo image)
    # - 2 professors sharing a URL = only OK if same person (name variant)
    from collections import defaultdict, Counter
    url_counts = Counter(r['image_url'] for r in with_photos)

    # For URLs shared by exactly 2, check if it's the same person
    url_lastnames = defaultdict(set)
    for r in with_photos:
        if url_counts[r['image_url']] == 2:
            parts = normalize_name(r['name']).split()
            last = re.sub(r'[^a-z]', '', parts[-1]) if parts else ''
            url_lastnames[r['image_url']].add(last)

    bad_urls = set()
    for url, count in url_counts.items():
        if count >= 3:
            # 3+ professors = always a shared/wrong image
            bad_urls.add(url)
        elif count == 2:
            # 2 professors = check if last names are related
            names = list(url_lastnames.get(url, set()))
            if len(names) == 2:
                a, b = names
                if a not in b and b not in a:
                    bad_urls.add(url)

    if bad_urls:
        before = len(with_photos)
        with_photos = [r for r in with_photos if r['image_url'] not in bad_urls]
        dropped = before - len(with_photos)
        print(f"  Dropped {dropped} entries with mismatched duplicate image URLs "
              f"({len(bad_urls)} shared URLs)")

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'image_url', 'source_page'])
        writer.writeheader()
        for row in with_photos:
            writer.writerow(row)

    print(f"  Saved {len(with_photos)} photo URLs to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape NEU faculty headshot photos from college websites"
    )
    parser.add_argument(
        "--data-dir", type=str, default=None,
        help="Directory containing rmp_professors.csv",
    )
    parser.add_argument(
        "--workers", type=int, default=15,
        help="Parallel threads (default 15)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max professors to process (for testing)",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output CSV path",
    )
    parser.add_argument(
        "--skip-directories", action="store_true",
        help="Skip Phase 1 directory scraping (slug-only mode)",
    )

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = args.data_dir or os.path.join(script_dir, "output_data")
    output_path = args.output or os.path.join(data_dir, "professor_photos.csv")

    profs = load_professors(data_dir)
    print(f"  Loaded {len(profs)} unique professors")

    if not profs:
        print("  No professors found. Check your data directory.")
        return

    results = scrape_photos(
        profs,
        workers=args.workers,
        limit=args.limit,
        skip_directories=args.skip_directories,
    )

    save_csv(results, output_path)


if __name__ == "__main__":
    main()
