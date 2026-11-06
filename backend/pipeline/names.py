"""Name and department helpers shared by the pipeline and the photo scrapers."""

import html
import re
import unicodedata


def normalize_name(name):
    s = str(name).strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def name_to_slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


_FOLD_PUNCTUATION = str.maketrans({
    "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
})


def search_fold(text):
    """Search key: curly quotes and dashes mapped to ASCII, accents stripped, lowercased,
    everything but letters, digits, "+", "#" and single spaces removed. "+" and "#" are kept
    (C++, C#) and are not LIKE wildcards."""
    s = (text or "").translate(_FOLD_PUNCTUATION)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii').lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9 +#]', '', s)
    return re.sub(r' +', ' ', s).strip()


def search_squash(text):
    return search_fold(text).replace(" ", "")


def tidy_name(name):
    """Display-name cleanup: unescape, collapse whitespace, and fix casing only
    when the whole name is lowercase or uppercase (or "Mc" + lowercase after the
    first word). Never feeds slugs, name_key or rmp_name."""
    if not name:
        return name
    s = re.sub(r'\s+', ' ', html.unescape(name)).strip()
    letters = [c for c in s if c.isalpha()]
    if letters and (all(c.islower() for c in letters) or all(c.isupper() for c in letters)):
        out = []
        for w in s.split(' '):
            bare = w.rstrip('.,')
            if bare.upper() in {"II", "III", "IV"}:
                out.append(bare.upper() + w[len(bare):])
            elif bare.lower() == "jr":
                out.append("Jr" + w[len(bare):])
            else:
                out.append(re.sub(r"(^|[-'’.])([^\W\d_])", lambda m: m.group(1) + m.group(2).upper(), w.lower()))
        s = ' '.join(out)
    # Past the first word "Mc" + lowercase is a surname (Mcgreevy); a given name can
    # just start with it (Mcebisi).
    first, _, rest = s.partition(' ')
    rest = re.sub(r'\bMc([a-z])', lambda m: "Mc" + m.group(1).upper(), rest)
    return f"{first} {rest}" if rest else first


def upgrade_image_url(url):
    return re.sub(r'-\d+x\d+(?=\.\w+$)', '', str(url))


COLLEGE_MAP = {
    "Computer Science": "Khoury", "Information Science": "Khoury",
    "Information Systems": "Khoury", "Computer & Informational Tech.": "Khoury",
    "Computer Engineering": "Khoury", "Cybersecurity": "Khoury",
    "Data Science": "Khoury", "Computer Information Systm": "Khoury",
    "Grad Engineering - Multidiscpl": "Engineering",
    "Engineering": "Engineering", "Electrical Engineering": "Engineering",
    "Mechanical Engineering": "Engineering", "Civil Engineering": "Engineering",
    "Chemical Engineering": "Engineering", "Industrial Engineering": "Engineering",
    "Materials Engineering": "Engineering", "Engineering Technology": "Engineering",
    "Electronics": "Engineering", "Electrical & Computer Engr": "Engineering",
    "Mechanical & Industrial Eng": "Engineering", "Civil & Environmental Eng": "Engineering",
    "Bioengineering": "Engineering", "Industrial Technology": "Engineering",
    "Business": "Business", "Business Administration": "Business",
    "Finance": "Business", "Finance & Insurance": "Business",
    "Accounting": "Business", "Accounting & Finance": "Business",
    "Marketing": "Business", "Management": "Business",
    "Entrepreneurship": "Business", "International Business": "Business",
    "Supply Chain Management": "Business", "Operations Management": "Business",
    "Managerial Science": "Business", "Organizational Behavior": "Business",
    "Organizational Leadership": "Business", "Human Resources Management": "Business",
    "Leadership": "Business",
    "Dean of College of Sciences": "Science",
    "Mathematics": "Science", "Physics": "Science", "Chemistry": "Science",
    "Biology": "Science", "Biochemistry": "Science",
    "Environmental Science": "Science", "Environmental Studies": "Science",
    "Marine Sciences": "Science", "Marine Biology": "Science",
    "Microbiology": "Science", "Biotechnology": "Science",
    "Geology": "Science", "Earth Science": "Science",
    "Biomedical": "Science", "Science": "Science", "Math": "Science",
    "Behavioral Neuroscience": "Science",
    "Art": "CAMD", "Art History": "CAMD", "Architecture": "CAMD",
    "Communication Studies": "CAMD", "Communication": "CAMD",
    "Communications": "CAMD", "Journalism": "CAMD",
    "Media": "CAMD", "Media Studies": "CAMD",
    "Graphic Design": "CAMD", "Design": "CAMD",
    "Music": "CAMD", "Music Technology": "CAMD", "Music Business": "CAMD",
    "Theater": "CAMD", "Game Design": "CAMD", "Fine Arts": "CAMD",
    "Visual Arts": "CAMD", "Cinema": "CAMD", "Photography": "CAMD",
    "Multimedia": "CAMD", "Creative Studies": "CAMD",
    "Health Science": "Health Sciences", "Health Sciences": "Health Sciences",
    "Nursing": "Health Sciences", "Pharmacy": "Health Sciences",
    "Physical Therapy": "Health Sciences",
    "Speech & Hearing Sciences": "Health Sciences",
    "Speech Language Pathology": "Health Sciences",
    "Health Management": "Health Sciences",
    "Health & Physical Education": "Health Sciences",
    "Medicine": "Health Sciences", "Regulatory Affairs": "Health Sciences",
    "Counseling Psychology": "Health Sciences", "Applied Psychology": "Health Sciences",
    "Political Science": "CSSH", "Economics": "CSSH", "History": "CSSH",
    "Psychology": "CSSH", "Sociology": "CSSH", "Philosophy": "CSSH",
    "English": "CSSH", "Writing": "CSSH", "Literature": "CSSH",
    "Linguistics": "CSSH", "Languages": "CSSH", "Modern Languages": "CSSH",
    "Spanish": "CSSH", "French": "CSSH", "Arabic": "CSSH",
    "Sign Language": "CSSH", "World Languages Center": "CSSH",
    "Criminal Justice": "CSSH", "Anthropology": "CSSH",
    "Human Services": "CSSH", "Religious Studies": "CSSH",
    "Judaic Studies": "CSSH", "International Studies": "CSSH",
    "International Affairs": "CSSH", "International Politics": "CSSH",
    "East Asian Studies": "CSSH", "Latin American Studies": "CSSH",
    "African-American Studies": "CSSH", "Women's Studies": "CSSH",
    "Women": "CSSH", "Social Science": "CSSH",
    "Public Policy": "CSSH", "Public Administration": "CSSH",
    "Urban Studies": "CSSH", "Humanities": "CSSH",
    "Education": "Professional Studies", "Professional Studies": "Professional Studies",
    "Col of Professional Studies": "Professional Studies",
    # CAEP, Bouve's Department of Applied Psychology, like Counseling Psychology above.
    "Counseling & Educational Psych": "Health Sciences",
    "Law": "Law",
}


def department_key(dept):
    """dept as COLLEGE_MAP is looked up: case and whitespace ignored, and "&"
    the same as the "amp" or bare gap it is left as when stripped upstream."""
    return re.sub(r"\s+", " ", re.sub(r"&|\bamp\b", " ", dept.lower())).strip()


# Built once: get_college runs per professor.
_COLLEGE_BY_KEY = {department_key(d): c for d, c in COLLEGE_MAP.items()}


def get_college(dept, default="Other"):
    if not isinstance(dept, str):
        return default
    return _COLLEGE_BY_KEY.get(department_key(dept), default)
