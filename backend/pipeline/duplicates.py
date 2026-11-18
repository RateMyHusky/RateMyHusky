"""Find one professor listed twice under a nickname ("Tony Russo" and "Anthony Russo").

RMP files a professor under whatever name students typed, so a nickname page
doesn't match the professor's name_key and becomes a second profile with the
ratings split between them. Every pipeline run calls nickname_merges(), and the
roster folds each sure pair into one profile: the RMP-only profile's pages move
to the other one, and it drops out of the catalog (roster.plan_relinks,
roster.merged_slugs). A new RMP page under a nickname links straight to the
existing profile (roster.resolve_roster), so the duplicate never appears.

Sure means all of these hold:
  - same last name and same department;
  - the first names are a known nickname pair (NICKNAMES), not just a shared
    prefix ("Dan"/"Danielle") or an initial, and the nickname stands for only
    one name ("Tom" is Thomas; "Pat" may be Patrick or Patricia, so it waits);
  - no other professor in that department fits either one, both ways;
  - the one that goes away is an RMP-only profile (Banner is the official
    roster, so two Banner profiles are left to a person) with no page a
    reviewer linked to it by hand;
  - neither name is a pair in prof_aliases.NOT_DUPLICATES.

Anything close that misses one of these is listed for review instead:
    python -m pipeline.duplicates          # read-only report
"""

import re
from collections import defaultdict

from prof_aliases import NOT_DUPLICATES

# nickname -> the formal first names it can stand for. A formal name maps to
# itself implicitly. Two first names match when they share a formal name.
NICKNAMES = {
    "abby": {"abigail"}, "al": {"albert", "alan", "allen", "alfred"}, "alex": {"alexander", "alexandra"},
    "alexa": {"alexandra"}, "andy": {"andrew"}, "drew": {"andrew"}, "ant": {"anthony"},
    "tony": {"anthony"}, "toni": {"antonia"}, "barb": {"barbara"}, "becky": {"rebecca"},
    "becca": {"rebecca"}, "ben": {"benjamin"}, "benji": {"benjamin"}, "beth": {"elizabeth"},
    "liz": {"elizabeth"}, "lizzie": {"elizabeth"}, "eliza": {"elizabeth"}, "betsy": {"elizabeth"},
    "bill": {"william"}, "billy": {"william"}, "will": {"william"}, "bob": {"robert"},
    "bobby": {"robert"}, "rob": {"robert"}, "robbie": {"robert"}, "bert": {"robert", "albert"},
    "brad": {"bradley"}, "cathy": {"catherine", "cathleen"}, "kate": {"katherine", "kathryn", "catherine"},
    "katie": {"katherine", "kathryn", "catherine"}, "kathy": {"katherine", "kathryn", "kathleen"},
    "kat": {"katherine", "kathryn"}, "chris": {"christopher", "christine", "christina"},
    "christy": {"christine", "christina"}, "chuck": {"charles"}, "charlie": {"charles"},
    "dan": {"daniel"}, "danny": {"daniel"}, "dave": {"david"}, "deb": {"deborah"},
    "debbie": {"deborah"}, "don": {"donald"}, "doug": {"douglas"}, "ed": {"edward"},
    "eddie": {"edward"}, "ted": {"edward", "theodore"}, "teddy": {"edward", "theodore"},
    "theo": {"theodore"}, "fred": {"frederick"}, "frank": {"francis", "franklin"},
    "gabe": {"gabriel"}, "greg": {"gregory"}, "hank": {"henry"}, "jack": {"john"},
    "johnny": {"john"}, "jake": {"jacob"}, "jim": {"james"}, "jimmy": {"james"},
    "jamie": {"james"}, "jen": {"jennifer"}, "jenny": {"jennifer"}, "jeff": {"jeffrey"},
    "jerry": {"gerald", "jerome"}, "joe": {"joseph"}, "joey": {"joseph"}, "jon": {"jonathan"},
    "josh": {"joshua"}, "judy": {"judith"}, "ken": {"kenneth"}, "kenny": {"kenneth"},
    "larry": {"lawrence"}, "len": {"leonard"}, "lenny": {"leonard"}, "maggie": {"margaret"},
    "meg": {"margaret"}, "peggy": {"margaret"}, "marty": {"martin"}, "matt": {"matthew"},
    "mike": {"michael"}, "mickey": {"michael"}, "mitch": {"mitchell"}, "nate": {"nathaniel", "nathan"},
    "nat": {"nathaniel", "natalie"}, "nick": {"nicholas"}, "nicky": {"nicholas"}, "pam": {"pamela"},
    "pat": {"patricia", "patrick"}, "patty": {"patricia"}, "phil": {"philip", "phillip"},
    "ray": {"raymond"}, "ron": {"ronald"}, "russ": {"russell"}, "sam": {"samuel", "samantha"},
    "sammy": {"samuel"}, "sandy": {"sandra"}, "steve": {"steven", "stephen"},
    "sue": {"susan"}, "suzy": {"susan"}, "tim": {"timothy"}, "timmy": {"timothy"},
    "tom": {"thomas"}, "tommy": {"thomas"}, "val": {"valerie"}, "vicky": {"victoria"},
    "vince": {"vincent"}, "zach": {"zachary"}, "zack": {"zachary"}, "missy": {"melissa"},
    "mandy": {"amanda"}, "manny": {"emmanuel", "manuel"}, "nikki": {"nicole"},
    "jess": {"jessica"}, "jessie": {"jessica"}, "lou": {"louis"}, "walt": {"walter"},
    "wes": {"wesley"}, "gene": {"eugene"}, "cindy": {"cynthia"}, "terry": {"terrence", "theresa"},
    "rick": {"richard"}, "ricky": {"richard"}, "rich": {"richard"}, "dick": {"richard"},
    "stan": {"stanley"}, "vic": {"victor"}, "abe": {"abraham"},
    "tess": {"theresa"}, "tina": {"christina"}, "sasha": {"alexander", "alexandra"},
}


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "esq"}


def name_parts(name_key, initials=False):
    """(first name, last name) of a name_key, or (None, None). A parenthesized
    maiden name and a trailing suffix ("Jr", "III") are ignored. A leading initial
    ("j. timothy sage") has no first name to compare unless `initials`."""
    words = [w.strip(".") for w in re.sub(r"\(.*?\)", " ", name_key or "").replace(",", " ").split()]
    words = [w for w in words if w]
    while len(words) > 2 and words[-1] in SUFFIXES:
        words.pop()
    if len(words) < 2:
        return None, None
    return (words[0] if initials or len(words[0]) > 1 else None), words[-1]


def _formal(first):
    return NICKNAMES.get(first, set()) | ({first} if first not in NICKNAMES else set())


def nickname_match(a, b):
    """True when first names a and b differ and one can stand for the other."""
    return bool(a and b and a != b and _formal(a) & _formal(b))


def sure_nickname(a, b):
    """nickname_match, where each nickname among a and b stands for only one
    name, so "Pat" never folds into Patricia when it might be Patrick."""
    return nickname_match(a, b) and all(len(_formal(n)) == 1 for n in (a, b))


def _vetoed(a, b):
    return frozenset((a["name_key"], b["name_key"])) in NOT_DUPLICATES


class NicknameIndex:
    """Professors bucketed by (department, last name)."""

    def __init__(self, professors):
        self.buckets = defaultdict(list)
        for p in professors:
            self.add(p)

    def add(self, p):
        first, last = name_parts(p["name_key"])
        if first and p.get("department"):
            self.buckets[(p["department"], last)].append((first, p))

    def matches(self, name_key, department, exclude=None):
        """The professors a nickname of name_key, in that department, could be."""
        first, last = name_parts(name_key)
        if not first or not department:
            return []
        return [p for f, p in self.buckets.get((department, last), ())
                if p["slug"] != exclude and p["name_key"] != name_key and nickname_match(first, f)]

    def target(self, name_key, department, exclude=None):
        """The one professor a new RMP page under name_key belongs to, or None."""
        found = self.matches(name_key, department, exclude)
        if len(found) != 1 or not sure_nickname(name_parts(name_key)[0], name_parts(found[0]["name_key"])[0]):
            return None
        back = self.matches(found[0]["name_key"], department, found[0]["slug"])
        if any(p["name_key"] != name_key for p in back) or _vetoed({"name_key": name_key}, found[0]):
            return None
        return found[0]


def survivor(a, b):
    """The profile of a sure pair that stays, or (None, why a person decides)."""
    banner = [p for p in (a, b) if p.get("origin") == "banner"]
    if len(banner) == 2:
        return None, "both are on the Banner roster"
    if banner:
        return banner[0], None
    formal = [p for p in (a, b) if name_parts(p["name_key"])[0] not in NICKNAMES]
    if len(formal) == 1:
        return formal[0], None
    return None, "no way to tell which name is formal"


def nickname_merges(professors, pinned=()):
    """({merged-away slug: surviving slug}, [review rows]). Pure.

    `professors` leaves out any already merged away, so a merged-away profile is
    never a survivor and a merge made earlier can't make a later match look
    ambiguous. `pinned` is the slugs holding a page a reviewer linked by hand
    ('manual'): moving the rest of such a profile's pages would split it, so it
    is only reviewed. Each review row is (professor a, professor b, reason) for a
    pair that looks like one person but isn't sure enough to merge.
    """
    index = NicknameIndex(professors)
    merges, review = {}, []
    for (department, _), group in index.buckets.items():
        for i, (fa, a) in enumerate(group):
            for fb, b in group[i + 1:]:
                if not nickname_match(fa, fb) or _vetoed(a, b):
                    continue
                if not sure_nickname(fa, fb):
                    review.append((a, b, "the nickname can stand for more than one name"))
                    continue
                if len(index.matches(a["name_key"], department, a["slug"])) != 1 \
                        or len(index.matches(b["name_key"], department, b["slug"])) != 1:
                    review.append((a, b, "more than one professor in the department could be this one"))
                    continue
                keep, why = survivor(a, b)
                if keep is None:
                    review.append((a, b, why))
                    continue
                gone = b if keep is a else a
                if gone.get("origin", "rmp") != "rmp":
                    review.append((a, b, "the profile to fold away is not RMP-only"))
                    continue
                if gone["slug"] in pinned:
                    review.append((a, b, "a reviewer linked a page by hand to the profile to fold away"))
                    continue
                merges[gone["slug"]] = keep["slug"]
    return merges, review


def near_misses(professors, merges, skip=()):
    """Review rows for pairs nickname_merges never considers: same last name and
    department with one first name a prefix or initial of the other ("Sidd" and
    "Siddhartha", "C. Randall" and "Carey"), or a known nickname pair split across
    two departments. `skip` is the review rows already found. Pure."""
    skip = {frozenset((a["slug"], b["slug"])) for a, b, _ in skip}
    rows = []
    by_last = defaultdict(list)
    for p in professors:
        first, last = name_parts(p["name_key"], initials=True)
        if first:
            by_last[last].append((first, p))
    for group in by_last.values():
        for i, (fa, a) in enumerate(group):
            for fb, b in group[i + 1:]:
                if a["slug"] in merges or b["slug"] in merges or _vetoed(a, b) or fa == fb \
                        or frozenset((a["slug"], b["slug"])) in skip:
                    continue
                same_dept = a.get("department") and a.get("department") == b.get("department")
                short, long_ = sorted((fa, fb), key=len)
                if same_dept and long_.startswith(short):
                    rows.append((a, b, "one first name is the start of the other"))
                elif not same_dept and nickname_match(fa, fb) and a.get("department") and b.get("department"):
                    rows.append((a, b, "nickname pair in different departments"))
    return rows


def main():
    import csv
    import sys

    from .db import connect, fetch_all

    professors = fetch_all(connect(), "SELECT slug, name, name_key, department, origin FROM professors")
    merges, review = nickname_merges(professors)
    review += near_misses(professors, merges, review)
    by_slug = {p["slug"]: p for p in professors}
    print(f"merged automatically: {len(merges)}")
    for old, new in sorted(merges.items()):
        print(f"  {by_slug[old]['name']} ({old}) -> {by_slug[new]['name']} ({new})  {by_slug[new]['department']}")
    print(f"for a person to check: {len(review)}  (confirm one: add it to RMP_MANUAL_LINKS; "
          "rule one out: add it to NOT_DUPLICATES)")
    w = csv.writer(sys.stdout)
    w.writerow(["reason", "name_a", "slug_a", "origin_a", "department_a",
                "name_b", "slug_b", "origin_b", "department_b"])
    for a, b, why in sorted(review, key=lambda r: (r[2], r[0]["name_key"])):
        w.writerow([why, a["name"], a["slug"], a.get("origin"), a.get("department"),
                    b["name"], b["slug"], b.get("origin"), b.get("department")])


if __name__ == "__main__":
    main()
