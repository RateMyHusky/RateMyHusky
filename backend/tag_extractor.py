"""
Tag extraction. Two parts:

  structured_tags(row) — free, exact: RMP's own attendance/textbook/tags fields
  extract_tags(reviews) — local model through Ollama for what's only in the comment

Ollama setup (once):
    ollama pull qwen2.5:7b
Override with OLLAMA_URL / OLLAMA_MODEL in backend/.env. Stdlib HTTP only, no new deps.
"""

import json
import os
import re
import urllib.request

from tags import RMP_TAG_MAP, TAG_HINTS, TAG_TAXONOMY

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
TIMEOUT_S = 300

_YES = {"yes", "y", "true", "mandatory"}

_HINT_RE = re.compile(
    r"\b(" + "|".join(sorted({re.escape(h) for hs in TAG_HINTS.values() for h in hs}, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def structured_tags(row) -> set[str]:
    """Tags straight from RMP's fields. "Not Mandatory" / "No" / blank give nothing."""
    out = set()
    if (row.get("attendance") or "").strip().lower() in _YES:
        out.add("mandatory_attendance")
    if (row.get("textbook") or "").strip().lower() in _YES:
        out.add("requires_textbook")
    rmp_tags = (row.get("tags") or "").lower()
    for phrase, tag in RMP_TAG_MAP.items():
        if phrase in rmp_tags:
            out.add(tag)
    return out


def might_have_tags(text: str) -> bool:
    """Cheap pre-filter: does the comment mention anything a tag could be about?"""
    return bool(text) and _HINT_RE.search(text) is not None


def build_prompt(reviews: list[dict]) -> str:
    tag_list = "\n".join(f"- {k}: {v}" for k, v in TAG_TAXONOMY.items())
    items = "\n".join(f'{r["id"]}: {json.dumps(r["text"])}' for r in reviews)
    return (
        "You are tagging student reviews of professors.\n\n"
        f"Allowed tags (use ONLY these):\n{tag_list}\n\n"
        "For each review, return only tags the text clearly supports. "
        "If a review says the opposite (e.g. \"doesn't take attendance\"), don't tag it.\n\n"
        f"Reviews:\n{items}\n\n"
        'Respond with ONLY a JSON object like {"<review_id>": ["tag1", "tag2"]}. '
        "Leave out reviews with no tags."
    )


def parse_tag_response(raw, valid_ids) -> dict[str, list[str]]:
    """Keep only known review ids and tags from the taxonomy."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    valid_ids = {str(i) for i in valid_ids}
    out = {}
    for rid, tags in raw.items():
        rid = str(rid)
        if rid not in valid_ids or not isinstance(tags, list):
            continue
        clean = sorted({t for t in tags if isinstance(t, str) and t in TAG_TAXONOMY})
        if clean:
            out[rid] = clean
    return out


def _call_ollama(prompt: str) -> str:
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read())["message"]["content"]


def extract_tags(reviews: list[dict]):
    """reviews: [{"id", "text"}, ...] -> {review_id: [tag, ...]}.
    None if the call failed (batch retries next run), {} if nothing applied."""
    if not reviews:
        return {}
    try:
        content = _call_ollama(build_prompt(reviews))
    except Exception as e:
        print(f"  ollama call failed, will retry next run: {e}")
        return None
    return parse_tag_response(content, [r["id"] for r in reviews])
