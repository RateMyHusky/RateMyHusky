"""The majors and minors a student profile may name.

programs.json is scraped from the undergraduate catalog by
scraper/programs_scrape.py, and the frontend ships an identical copy for its
dropdowns. A profile stores a name exactly as it appears here, or OTHER.
"""

import json
import pathlib

OTHER = "other"

_data = json.loads((pathlib.Path(__file__).parent / "programs.json").read_text(encoding="utf-8"))
MAJORS = frozenset(p["name"] for p in _data["majors"])
MINORS = frozenset(p["name"] for p in _data["minors"])
