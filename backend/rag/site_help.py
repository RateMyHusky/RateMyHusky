"""Hand-written answers to questions about the site itself ("how do bookmarks work?").

A match returns a fixed answer with links and costs no LLM call. The registry never answers
about a named professor or course: those questions fall through to the LLM path.
"""
import re
from dataclasses import dataclass

from rag.chat_gate import MAX_QUERY_LEN


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    answer: str
    links: tuple[tuple[str, str], ...]
    patterns: tuple[re.Pattern, ...]


def _p(*regexes):
    return tuple(re.compile(r, re.I) for r in regexes)


# Same shape as chat_retrieve's course-code regex, kept local so this module stays light.
_COURSE_CODE = re.compile(r"\b[a-z]{2,5}\s?\d{4}\b")
# A title used as a title: prof / professor / dr (optional ".") then a word that is not a
# plain noun-phrase word. "rate a professor" and "my professor page" pass; "professor Lee" does not.
_TITLE = re.compile(r"\b(?:prof|professor|dr)\b\.?\s+(\w+)")
_TITLE_STOP = {"a", "an", "the", "my", "your", "their", "this", "that", "who", "is", "has",
               "page", "pages", "ratings", "reviews"}

ENTRIES: tuple[Entry, ...] = (
    Entry(
        "ask_help", "What can Ask answer?",
        "Ask answers questions about one Northeastern professor or course at a time, using their "
        "ratings, reviews, and Reddit comments. Questions about reviews need you to sign in with "
        "your Husky Google account.",
        (("FAQ", "/faq#students"),),
        _p(r"what (kinds?|types?|sorts?) of questions (can|could) (i|you) (ask|answer)",
           r"what (can|could) ask (answer|do|handle)",
           r"how (does|do) (the )?ask( feature| widget| assistant| box)? work",
           r"how do i use (the )?ask\b",
           r"(can|does) ask (answer|handle)")),
    Entry(
        "awards", "Teaching award badges",
        "Badges come from the award lists Northeastern publishes, including the University "
        "Excellence in Teaching Award and college awards such as Khoury's. Each badge links to "
        "the announcement it came from.",
        (("FAQ: award badges", "/faq#students"),),
        _p(r"\bwhere (do|does|did) (the )?(teaching )?(award )?badges? come from",
           r"\bwhat (are|is|do) (the )?(teaching )?(award )?badges?( mean)?$",
           r"\bwhere (do|does|did) (the )?(teaching )?awards? (data|information|info|badges?) come from")),
    Entry(
        "photos", "Why no photo?",
        "We only use photos that Northeastern publishes on its own faculty and college "
        "directory pages. Many instructors, especially part-time and former faculty, don't have "
        "one there, so we don't either.",
        (("FAQ: photos", "/faq#students"),),
        _p(r"\bwhy (is|are) there no (photo|picture|headshot)s?\b",
           r"\bwhy (doesn'?t|does not|don'?t|do not) (this|a|every|some|that) (instructor|faculty|professor|page|profile)s? have (a )?(photo|picture|headshot)",
           r"\bwhere do (the )?(faculty |professor |instructor )?(photos|pictures|headshots) come from",
           r"\bwhy (do|does) (some|a|this) (page|profile)s? (have|show) no (photo|picture|headshot)")),
    Entry(
        "offerings", "Last Taught and When it's offered",
        "They come from Northeastern's public course schedule, and show when a course ran and "
        "who taught it, to read alongside the reviews. For seats, meeting times, and "
        "registration, use Northeastern's registration system or SearchNEU.",
        (("FAQ: Last Taught", "/faq#students"),),
        _p(r"\blast taught\b",
           r"\bwhen (a |the |this )?(course|class)(es)? (is|are|gets?) (offered|run|taught)\b",
           r"\bwhen it'?s offered\b",
           r"\bwhen (is|are|do|does) (a |the |this )?(course|class)(es)? (get |being )?(offered|run|taught)")),
    Entry(
        "missing_course", "Missing course",
        "A professor's course list combines the courses students have rated them in with the "
        "courses Northeastern's schedule shows them teaching in recent terms. A course they "
        "taught before then that nobody has reviewed won't appear.",
        (("FAQ: missing courses", "/faq#students"),),
        _p(r"\b(course|class)(es)? ((is|are) )?(missing|not (listed|showing|shown)|isn'?t (listed|showing|shown)) (from|on|in) (a |the |this |my )?(professor'?s? |instructor'?s? )?(page|list|profile)",
           r"\b(isn'?t|aren'?t|not) (a |the |my )?(course|class)(es)? (listed|showing|shown) (on|in) (the|a|this) (page|list|profile)",
           r"\b(can'?t|cannot|don'?t) (see|find) (a |the |my )?(course|class) (on|in) (the|a|this) (professor'?s? )?(page|list|profile)")),
    Entry(
        "no_ratings", "Page but no ratings",
        "Most instructors on Northeastern's course schedule get a page even when nobody has "
        "rated them on RateMyProfessors or here. Their page shows the courses and terms they "
        "taught, and ratings appear after students submit them and the next weekly refresh runs.",
        (("FAQ: pages without ratings", "/faq#students"), ("Rate a professor", "/rate")),
        _p(r"\bwhy (does|do|is|are) (there |a |an |this |some |my |the |these )?(a |an )?(instructor|page|profile|professor)s?\b.*\b(no|zero|without) (ratings?|reviews?)\b",
           r"\b(page|profile)s? (but|with|without) (no|zero) (ratings?|reviews?)")),
    Entry(
        "sentiment", "Sentiment bar",
        "It's an automated read of whether a Reddit comment speaks about the professor "
        "positively, negatively, or neutrally. It is generated by a model, not written by a "
        "person, and it scores each comment on its own, so sarcasm can be misread. Read the "
        "comment itself before you rely on the label.",
        (("FAQ: sentiment bar", "/faq#students"),),
        _p(r"\bsentiment (bar|label|score|colou?r|meaning)s?\b",
           r"\b(reddit|comment) sentiment\b.*\b(mean|work|calculated|determined|generated|decided)",
           r"\b(mean|work|calculated|determined|generated)\b.*\bsentiment (bar|label)")),
    Entry(
        "goated", "GOATED Professors",
        "GOATED Professors are ranked by rating and by how many students rated them, so a "
        "very high score from only a few students counts for less than a slightly lower score "
        "from many. The ranking compares every professor on the same scale and doesn't adjust "
        "for how hard their department is.",
        (("GOATED Professors", "/#goated"), ("FAQ: ranking", "/faq#students")),
        _p(r"\b(what|how)\b.*\bgoated\b.*\b(rank|list|mean|calculat|work|chosen|picked|sorted|order|score|decided)",
           r"\b(what|how)\b.*\b(rank|mean|calculat|work|chosen|picked|sorted|order)\w*\b.*\bgoated\b")),
    Entry(
        "compare", "Compare professors",
        "Compare puts professors side by side and, for each row, marks the one with the best "
        "number among your picks. Nobody is marked when everyone ties, and a professor with too "
        "few ratings is shown greyed out and never marked best.",
        (("Compare professors", "/compare"), ("FAQ: how Compare works", "/faq#students")),
        _p(r"\bcompare (page|tool|feature|tab)\b",
           r"\bhow does compare\b",
           r"\bwhat (does|is) (the )?compare\b",
           r"\bhow (do|can) i compare (two |multiple |some )?(professors|instructors)\b")),
    Entry(
        "rate", "Rate a professor",
        "Yes. Use the rating form to rate a professor and course you took: you answer a few "
        "questions, add an optional comment, and no sign-in is needed. Once accepted, your "
        "rating shows up here after the next weekly refresh.",
        (("Rate a professor", "/rate"), ("FAQ: writing a review", "/faq#students")),
        _p(r"\b(can|how do|how can|where do|where can) i (write|leave|submit|post|add) (a |an |my )?(review|rating)( here| on (the )?(site|website)| on ratemyhusky)?$",
           r"\brating form\b",
           r"\brate (a|my|an) (professor|course|class|instructor)\b",
           r"\bwhere (do|can) i (rate|review) (a|my|the) (professor|course|class|instructor)s?\b")),
    Entry(
        "affiliation", "Is this run by Northeastern?",
        "No. RateMyHusky is an independent student project. It is not affiliated with, "
        "endorsed by, or officially connected to Northeastern University or RateMyProfessors.",
        (("FAQ", "/faq#students"),),
        _p(r"\b(is|are) (this|the|it|ratemyhusky)\b.*\b(affiliat|endorse|official|run by|owned by|made by|part of|connected (to|with))",
           r"\b(ratemyhusky|this (site|website))\b.*\b(run|owned|made|created|operated|built) by",
           r"\bwho (runs|made|built|owns|created) (this (site|website)|ratemyhusky|the (site|website))\b")),
    Entry(
        "professors", "Professors: corrections and removal",
        "If you teach at Northeastern, you can have your page corrected or removed. Use the "
        "feedback form and choose Data Deletion, entering your Northeastern email, so we can "
        "confirm the request is really from you.",
        (("FAQ for professors", "/faq#professors"),),
        _p(r"\bi teach\b",
           r"\bi('?m| am) (a |an )?(professor|faculty|instructor)",
           r"\b(my|our) (professor |faculty )?(page|profile)\b",
           r"\b(page|profile) (removed|taken down|deleted)\b")),
    Entry(
        "privacy", "Privacy and terms",
        "The Privacy Policy lists what the site collects and publishes, and the Terms of "
        "Service cover how you can use it.",
        (("Privacy Policy", "/privacy"), ("Terms of Service", "/terms")),
        _p(r"\bprivacy\b",
           r"\bterms (of (service|use)|and conditions)\b",
           r"\bwhat (data|information) do you (collect|store|keep|track)")),
    Entry(
        "report", "Report wrong or missing data",
        "Use the Feedback tab on the left edge of any page (a round button in the bottom-right "
        "corner on phones) and choose Wrong or Missing Data. A link to the page in question "
        "helps.",
        (("FAQ: reporting problems", "/faq#students"),),
        _p(r"\bfeedback (tab|button|form|link)\b",
           r"\breport (a |an )?(bug|problem|issue|error|mistake|wrong|incorrect|missing|data)",
           r"\b(wrong|incorrect|missing|outdated) (data|info|information) (on|in) (the |this |a )?(site|page|website|profile)\b",
           r"\bsomething (on|in) (the|this) (site|page|website) (is|looks|seems) (wrong|incorrect|broken)\b",
           r"\bgive feedback\b")),
    Entry(
        "bookmarks", "Bookmarks",
        "Bookmark a professor or course to save it, then find your saved ones on the Bookmarks "
        "page. You need to sign in with your Husky Google account to use bookmarks.",
        (("Your bookmarks", "/bookmarks"),),
        _p(r"\bbookmark",
           r"\bsaved (professors|courses|list|items)\b",
           r"\bsave (a|this|that) (professor|course)\b")),
    Entry(
        "departments", "Departments",
        "The Departments page lists every department, and each one links to its professors and "
        "courses.",
        (("Departments", "/departments"),),
        _p(r"\bdepartments? (page|list|pages|directory)\b",
           r"\bbrowse (professors |courses )?by department\b",
           r"\b(see|browse|list|view) (all |the )?(departments|colleges)\b")),
    Entry(
        "sign_in", "Signing in",
        "Sign in with your Husky Google account. Signing in lets you bookmark professors and "
        "courses and ask Ask questions about reviews; browsing and rating need no sign-in.",
        (("Your bookmarks", "/bookmarks"),),
        _p(r"\b(sign|log)[ -]?in\b",
           r"\bhusky (google )?account\b",
           r"\bgoogle account\b")),
    Entry(
        "theme", "Dark and light mode",
        "Use the theme toggle to switch between dark and light mode. The site remembers your "
        "choice on that device.",
        (),
        _p(r"\b(dark|light|night) (mode|theme)\b",
           r"\btheme (toggle|switch|button)\b",
           r"\b(change|switch|toggle) (the |my )?(site |page )?theme\b",
           r"\bswitch (to )?(dark|light)\b")),
    Entry(
        "search", "Finding a professor or course",
        "Use the search bar to find a professor or course by name. You can also browse every "
        "professor on the Professors page and every course on the Courses page.",
        (("Professors", "/professors"), ("Courses", "/courses")),
        _p(r"\b(search|look ?up) (bar|box|for (a |an )?(professor|course|class|instructor)s?)\b",
           r"\bhow (do|can) i (search|look up|find) (a |an |the )?(professor|course|class|instructor)s?(\s+(here|on (the )?(site|website)|on ratemyhusky))?$",
           r"\bbrowse (all )?(professors|courses|classes)\b",
           r"\bwhere is the search (bar|box)\b")),
    Entry(
        "data_sources", "Where the data comes from",
        "Ratings and written reviews come from RateMyProfessors, and ratings also come from "
        "students through our own rating form. The Reddit tab on a professor's page shows public "
        "posts and comments from Northeastern subreddits that mention that professor, with a "
        "link back to each original. We refresh the data every week.",
        (("FAQ: where ratings come from", "/faq#students"),),
        _p(r"\bwhere (do|does|did) (the |your |these |this |those |this site'?s? )?((reddit|rmp|ratemyprofessors?) )?(ratings?|reviews?|data|posts|comments)\b.*\b(come|from|get|got)\b",
           r"\bhow often (is|are|do|does) (the )?(data|ratings|reviews|site|website) (updat|refresh|chang)",
           r"\bweekly refresh\b",
           r"\bdata sources?\b")),
    Entry(
        "menu", "What can I ask?",
        "I can answer questions about how RateMyHusky works: where the data comes from, how to "
        "rate a professor, how GOATED Professors and Compare work, bookmarks, signing in, "
        "searching, departments, privacy, and more. Tap a topic below.",
        (("FAQ", "/faq"),),
        _p(r"^(help|menu|options|hi|hello|hey)$",
           r"^what (can|do) you (do|know)( here)?$",
           r"^what (can|do) you (do|know) about (this|the) (site|website|ask)$",
           r"^what can i do here$",
           r"^what (is|'?s) (this|the) (site|website|page)$",
           r"^what (is|'?s) ratemyhusky$",
           r"^how does (this|the) (site|website) work$",
           r"^can you help( me)?$",
           r"^i need help$")),
)

_BY_ID = {e.id: e for e in ENTRIES}


def get(entry_id: str) -> Entry | None:
    return _BY_ID.get(entry_id)


def _normalise(q: str) -> str:
    q = re.sub(r"\s+", " ", q.lower())
    return re.sub(r"^[^\w]+|[^\w]+$", "", q)


def _names_entity(text: str) -> bool:
    if _COURSE_CODE.search(text):
        return True
    return any(m.group(1) not in _TITLE_STOP for m in _TITLE.finditer(text))


def match(q: str) -> Entry | None:
    if not q or len(q) > MAX_QUERY_LEN:
        return None
    text = _normalise(q)
    if not text or _names_entity(text):
        return None
    for entry in ENTRIES:
        if any(p.search(text) for p in entry.patterns):
            return entry
    return None


def payload(entry: Entry) -> dict:
    out = {
        "mode": "site_help",
        "id": entry.id,
        "title": entry.title,
        "answer": entry.answer,
        "links": [{"label": label, "href": href} for label, href in entry.links],
    }
    if entry.id == "menu":
        out["menu"] = [{"id": e.id, "title": e.title} for e in ENTRIES if e.id != "menu"]
    return out
