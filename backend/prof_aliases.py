"""Canonical RMP-name-variant -> canonical-name alias map (normalized keys).

Folds the different spellings RMP files one professor under ("dan kennedy",
"daniel kennedy") onto one name_key, which also keeps their catalog slug stable.

Single source of truth shared by the pipeline (build time) and server.py
(runtime). These were previously two hand-synced copies that had drifted:
the server copy was missing 62 of the aliases the catalog was built with.
"""

ALIAS_MAP = {
    # ── Two different men in one department, both going by "Peter Xu": RMP lists
    # them as "Peter Xu" and "Peter (Xun) Xu". No automatic rule can separate
    # them: same surname, same department, both teaching a 2301-level supply
    # chain course. Each maps to its legal name, which is also the slug their
    # catalog rows already use.
    #
    #   RMP "Peter Xu" (id 2875022, 11 reviews, MGSC2301, 2023-11..2026-03)
    #     -> "peng xu"  ("Peng(Peter) Xu", https://damore-mckim.northeastern.edu/people/pengpeter-xu/)
    #
    #   RMP "Peter (Xun) Xu" (id 3161329, 4 reviews, "2301"/supply chain, 2026-04..05)
    #     -> "xun xu"  (https://damore-mckim.northeastern.edu/people/xun-xu/)
    #
    # Do not collapse these two into each other: the review dates alone rule it
    # out (Peng's reviews start in 2023, Xun's in 2026).
    "peter xu": "peng xu",
    "peter (xun) xu": "xun xu",
    "laney strange": "elena strange",
    "ben tasker": "benjamin tasker",
    "alberto de la torre": "alberto de la torre duran",
    "justin wang": "hsiao-an wang",
    "sakib miazi": "md nazmus sakib miazi",
    "nazmus miazi": "md nazmus sakib miazi",
    "alex depaoli": "alexander depaoli",
    "denisee spencer": "denise spencer",
    "chris bruell": "christopher bruell",
    "hande ondemir": "hande musdal ondemir",
    "francis frank georges": "francis georges",
    "isabel campos": "isabel sobral campos",
    "mary sue potts-santone": "mary-susan potts-santone",
    "ronald c. zullo": "ronald zullo",
    "steve granelli": "steven granelli",
    "william (bill) goldman": "william goldman",
    "virgiliu pavlu": "virgil pavlu",
    "zhiyuan (katherine) zhang": "zhiyuan zhang",
    "katherine zhang": "zhiyuan zhang",
    "bill goldman": "william goldman",
    "aarti sathyanaran": "aarti sathyanarayana",
    "akash murty": "akash murthy",
    "ali chaleshtari": "ali shirzadeh chaleshtari",
    "sriram rajagopalan": "sriramasundarar rajagopalan",
    "mauricio codesso": "mauricio mello codesso",
    "magda cooney": "magdalena cooney",
    "john lowery": "john lowrey",
    "iesha karasik": "ieshia karasik",
    "ifa khan": "iffat khan",
    "h. david sherman": "h sherman",
    "ganish krisnamoorthy": "ganesh krishnamoorthy",
    "farena sultan": "fareena sultan",
    "cathy merlo": "catherine merlo",
    "ye yin": "yi yin",
    "silvio amir": "silvio amir alves moreira",
    "olin shivers": "olin shivers iii",
    "rush sanghrajka": "rushit sanghrajka",
    "john alexis gomez": "john alexis guerra gomez",
    "ghita amor tijani": "ghita amor-tijani",
    "bob lupi": "robert lupi",
    "hany sadaka": "hanai sadaka",
    "mary- susan potts": "mary-susan potts-santone",
    "xiaotao (kelvin) liu": "xiaotao liu",
    "kelvin liu": "xiaotao liu",
    "Alex Budnitz": "Alexander Budnitz",
    "Alex Martsinkovsky": "Alexander Martsinkovsky",
    "Anu Gaur": "Anupama Gaur",
    "Balasubrama Maheswaran": "Balasubramaniam Maheswaran",
    "Barb Murrer": "Barbara Murrer",
    "Ben Knudsen": "Benjamin Knudsen",
    "Ben Machlin": "Benjamin Machlin",
    "Bolo Amgalan": "Bolor Amgalan",
    "Brad Lehman": "Bradley Lehman",
    "Chris Ayala": "Christopher Ayala",
    "Chris Beasley": "Christopher Beasley",
    "Chris Bosso": "Christopher Bosso",
    "Chris King": "Christopher King",
    "Chris Robertson": "Christopher Robertson",
    "Chris Selland": "Christopher Selland",
    "Christo Wilson": "Christopher Wilson",
    "Dan Kennedy": "Daniel Kennedy",
    "Dan Lothian": "Daniel Lothian",
    "Dan Matthew": "Daniel Matthew",
    "Dan Metzger": "Daniel Metzger",
    "Dan Sunderland": "Daniel Sunderland",
    "Dan Urman": "Daniel Urman",
    "Dan Zedek": "Daniel Zedek",
    "Ed Witten": "Edward Witten",
    "Gahye Song": "Ga Hye Song",
    "Ganeshsingh Thakur": "Ganesh Thakur",
    "Greg Allen": "Gregory Allen",
    "Greg Collier": "Gregory Collier",
    "Greg Fiete": "Gregory Fiete",
    "Greg Goodale": "Gregory Goodale",
    "Greg Kowalski": "Gregory Kowalski",
    "Greg Wassall": "Gregory Wassall",
    "Jean Francois Hamel": "Jean-Francois Hamel",
    "Jeff Howe": "Jeffrey Howe",
    "Jeff Kushner": "Jeffrey Kushner",
    "Ji-Yong Shin": "Ji Yong Shin",
    "Kat Gonso": "Kathleen Gonso",
    "Ken Baclawski": "Kenneth Baclawski",
    "Kris Dorsey": "Kristen Dorsey",
    "Marie-Odile Hobeika": "Marie Odile Hobeika",
    "Matt Garcia": "Matthew Garcia",
    "Matt Hunt": "Matthew Hunt",
    "Matt Lee": "Matthew Lee",
    "Matt Williams": "Matthew Williams",
    "Meg Heckman": "Meghan Heckman",
    "Mitch Franklin": "Mitchell Franklin",
    "Muhammad Shabanpour": "Muhammadhussian Shabanpour",
    "Nadaa Naji": "Nada Naji",
    "N. Castor": "Nicole Castor",
    "Pierre Tchetgen": "Pierre-Valery Tchetgen",
    "Ray Weaver": "Raymond Weaver",
    "seo eun (sunny) yang": "seoeun yang",
    "yang seoeun": "seoeun yang",
    "Sheng Yen": "Sheng-Che Yen",
    "Tim Brown": "Timothy Brown",
    "Tim Rupert": "Timothy Rupert",
    "A Zilleruelo": "Arturo Zilleruelo",
    # Both O'Malleys are spelled with an apostrophe; RMP has three variants.
    "don o'malley": "donald o'malley",
    "donald o' malley": "donald o'malley",
    "donica omalley": "donica o'malley",
    "G. Kimball": "Grayson Kimball",
    "R Cole Eidson": "Robert Eidson",
    "S. M Gupta": "Surendra Gupta",
    "sarthak gupta": "sarthak suhrid gupta",
}


# Hand-reviewed corrections to how an RMP listing links to a professor, keyed
# by RMP's spelling of the name. rmp_link_key reports such a match as
# "manual", which is what separates a reviewer's decision from the ALIAS_MAP
# spellings ("alias") and a plain normalized-name match ("exact"); callers do
# not persist that method today.
#
# Keyed by name rather than RMP's legacy id because rmp_reviews carries no id:
# reviews reach a professor through their professor_name, so an override keyed
# any other way would move the summary and leave its ratings behind — the
# recount in the pipeline would then publish 0 ratings under the new key.
# rmp_link_key() is the single place both sides resolve through.
#
# Add entries here by hand when a reviewer finds a wrong link.
RMP_MANUAL_LINKS = {
}


def _normalize_name(name: str) -> str:
    import re, unicodedata
    s = str(name).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip()
    return s

# Ensure keys/values match normalize_name() used by server.py and the pipeline.
ALIAS_MAP = {_normalize_name(k): _normalize_name(v) for k, v in ALIAS_MAP.items()}
RMP_MANUAL_LINKS = {_normalize_name(k): _normalize_name(v) for k, v in RMP_MANUAL_LINKS.items()}


def rmp_link_key(name):
    """(name_key, match_method) for an RMP listing or review's professor_name.

    Manual links win over aliases, which win over the name as written. There is
    no "fuzzy" branch: RMP listings link to a professor only by name.
    """
    key = _normalize_name(name)
    if key in RMP_MANUAL_LINKS:
        return RMP_MANUAL_LINKS[key], "manual"
    if key in ALIAS_MAP:
        return ALIAS_MAP[key], "alias"
    return key, "exact"
