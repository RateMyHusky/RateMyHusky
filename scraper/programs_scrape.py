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

Editions: the current catalog plus the archived 2022-2023 through 2025-2026
ones. Students are held to the catalog of the year they entered, so a current
student (classes of 2027-2030) can be in a major the current edition no longer
lists (Data Science, BS became Artificial Intelligence). Each archive edition
has its own /archive/<year>/sitemap.xml and index; its sitemap lists the
edition's pages under /undergraduate/, which live at /archive/<year>/undergraduate/.
A name found in several editions is one entry, labelled with the college of the
newest edition that has it (the current one first).

~650 pages per edition at one request per 250ms: about fifteen minutes in all.
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
ARCHIVE_YEARS = ("2025-2026", "2024-2025", "2023-2024", "2022-2023")  # newest first
MIN_MAJORS = 200   # 342 live on 2026-11-20
MIN_MINORS = 100   # 181 live on 2026-11-20

TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
# "Computer Science, BSCS (Boston)", "Computer Science, Minor", and the catalog's
# own typo "..., BA (Boston" (unclosed paren). Anything after the degree is dropped.
PROGRAM_TITLE = re.compile(r"^(?P<name>.+?),\s*(?P<degree>Minor|B[A-Z][A-Za-z]{0,5}|PharmD)\b")

# Not colleges: policy and admission sections sit beside them in the same list.
NOT_COLLEGES = {"admission", "information-entering-students", "expenses",
                "academic-policies-procedures", "university-academics", "appendix", "faculty"}

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


def colleges(index_html, prefix=""):
    """{slug: college name} from the links on <prefix>/undergraduate/."""
    link = re.compile(r'<a\s+href="%s/undergraduate/(?P<slug>[a-z0-9-]+)/"[^>]*>(?P<label>.*?)</a>'
                      % re.escape(prefix), re.S)
    return {m.group("slug"): clean(m.group("label")) for m in link.finditer(index_html)
            if m.group("slug") not in NOT_COLLEGES}


def program_paths(sitemap_xml, college_slugs, prefix=""):
    """Paths (under prefix) below a college page; the college page itself is not a program.

    Archive sitemaps list an edition's pages as /undergraduate/... (some as http://).
    """
    paths = []
    for url in re.findall(r"<loc>(.*?)</loc>", sitemap_xml):
        match = re.match(r"https?://catalog\.northeastern\.edu(/undergraduate/.*)", url)
        if not match:
            continue
        parts = match.group(1).strip("/").split("/")
        if len(parts) >= 3 and parts[1] in college_slugs:
            paths.append(prefix + match.group(1))
    return paths


def scrape_edition(fetch, prefix="", sitemap="/sitemap.xml"):
    """{"major": {name: college}, "minor": {name: college}} for one catalog edition."""
    college_names = colleges(fetch(prefix + "/undergraduate/"), prefix)
    found = {"major": {}, "minor": {}}
    for path in program_paths(fetch(sitemap), college_names, prefix):
        program = parse_program_page(fetch(path))
        if program:
            kind, name = program
            college = college_names[path[len(prefix):].split("/")[2]]
            found[kind].setdefault(name, college)
    return found


def build(fetch, min_majors=MIN_MAJORS, min_minors=MIN_MINORS, archive_years=ARCHIVE_YEARS):
    """The program list as the JSON dict. fetch(path) -> html text."""
    current = scrape_edition(fetch)
    # The gate is on the current edition alone: archives must not hide a redesigned site.
    if len(current["major"]) < min_majors or len(current["minor"]) < min_minors:
        raise ThinCatalog(f"found {len(current['major'])} majors and {len(current['minor'])} minors, "
                          f"expected at least {min_majors} and {min_minors}")
    editions = [current] + [scrape_edition(fetch, f"/archive/{year}", f"/archive/{year}/sitemap.xml")
                            for year in archive_years]
    lists = {}
    for kind in ("major", "minor"):
        merged = {}
        for edition in editions:   # newest first: the first college label seen wins
            for name, college in edition[kind].items():
                merged.setdefault(name, college)
        lists[kind] = [{"name": name, "college": college} for college, name in
                       sorted((college, name) for name, college in merged.items())]
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
