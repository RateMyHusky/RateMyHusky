"""Build the student-profile program list (majors and minors) from the undergraduate catalog.

Re-run by hand when the catalog changes (new edition, new programs):

    python scraper/programs_scrape.py

It writes backend/programs.json and frontend/src/data/programs.json (identical
copies; a backend test fails if they drift) and prints the counts. Commit both.

The catalog has no single list of programs, and each college lays its program
pages out differently (department tabs, combined-major pages, interdisciplinary
pages). What is uniform is the page for each program: its <title> is
"<Name>, <Degree> (<Campus>)" for a major and "<Name>, Minor" for a minor. So
this reads /sitemap.xml, fetches every page under a college, and keeps the
pages whose title has that shape. The campus is dropped (the Boston and Oakland
pages of one major are one entry); the degree stays, so "Computer Science, BSCS"
and "Computer Science, BACS" stay distinct. Concentrations and department pages
have no degree in the title and fall out.

~650 pages at one request per 250ms: about three minutes.
"""

import html as html_module
import json
import os
import re
import sys
from datetime import date

from catalog_api import BASE, clean
from catalog_scrape import CatalogClient

SOURCE = BASE + "/undergraduate/"
MIN_MAJORS = 200   # 342 live on 2026-11-20
MIN_MINORS = 100   # 181 live on 2026-11-20

TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
# "Computer Science, BSCS (Boston)", "Computer Science, Minor", and the catalog's
# own typo "..., BA (Boston" (unclosed paren). Anything after the degree is dropped.
PROGRAM_TITLE = re.compile(r"^(?P<name>.+?),\s*(?P<degree>Minor|B[A-Za-z]{1,6}|PharmD)\b")
COLLEGE_LINK = re.compile(r'<a\s+href="/undergraduate/(?P<slug>[a-z0-9-]+)/"[^>]*>(?P<label>.*?)</a>', re.S)
# Not colleges: policy and admission sections sit beside them in the same list.
NOT_COLLEGES = {"admission", "information-entering-students", "expenses",
                "academic-policies-procedures", "university-academics"}

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = [os.path.join(REPO, "backend", "programs.json"),
           os.path.join(REPO, "frontend", "src", "data", "programs.json")]


class ThinCatalog(Exception):
    """Too few programs found: the site changed shape, so write nothing."""


def parse_program_page(page_html):
    """("major"|"minor", name) for a program page, None for any other page."""
    title = TITLE.search(page_html)
    if not title:
        return None
    text = clean(html_module.unescape(title.group(1))).split(" < ")[0]
    match = PROGRAM_TITLE.match(text)
    if not match:
        return None
    degree = match.group("degree")
    return ("minor" if degree == "Minor" else "major", f"{match.group('name')}, {degree}")


def colleges(index_html):
    """{slug: college name} from the links on /undergraduate/."""
    return {m.group("slug"): clean(m.group("label")) for m in COLLEGE_LINK.finditer(index_html)
            if m.group("slug") not in NOT_COLLEGES}


def program_paths(sitemap_xml, college_slugs):
    """Sitemap paths below a college page (the college page itself is not a program)."""
    paths = []
    for url in re.findall(r"<loc>(.*?)</loc>", sitemap_xml):
        if not url.startswith(BASE + "/undergraduate/"):
            continue
        path = url[len(BASE):]
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[1] in college_slugs:
            paths.append(path)
    return paths


def build(fetch, min_majors=MIN_MAJORS, min_minors=MIN_MINORS):
    """The program list as the JSON dict. fetch(path) -> html text."""
    college_names = colleges(fetch("/undergraduate/"))
    found = {"major": [], "minor": []}
    for path in program_paths(fetch("/sitemap.xml"), college_names):
        program = parse_program_page(fetch(path))
        if program:
            kind, name = program
            found[kind].append({"name": name, "college": college_names[path.split("/")[2]]})
    lists = {}
    for kind in ("major", "minor"):
        seen = set()
        lists[kind] = []
        for entry in sorted(found[kind], key=lambda e: (e["college"], e["name"])):
            if entry["name"] not in seen:
                seen.add(entry["name"])
                lists[kind].append(entry)
    if len(lists["major"]) < min_majors or len(lists["minor"]) < min_minors:
        raise ThinCatalog(f"found {len(lists['major'])} majors and {len(lists['minor'])} minors, "
                          f"expected at least {min_majors} and {min_minors}")
    return {"source": SOURCE, "copied": date.today().isoformat(),
            "majors": lists["major"], "minors": lists["minor"]}


def main():
    try:
        result = build(CatalogClient()._get)
    except ThinCatalog as thin:
        print(f"ABORTED: {thin}\nNothing was written.", file=sys.stderr)
        return 1
    for path in OUTPUTS:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    print(f"{len(result['majors'])} majors, {len(result['minors'])} minors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
