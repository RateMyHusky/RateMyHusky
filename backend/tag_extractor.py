"""
Gets tags for reviews. RMP's attendance/textbook/tags fields first since
those are free, then a local Ollama model for stuff only in the comment.

Needs: ollama pull qwen2.5:7b
"""

import json
import os
import re
import urllib.request

from tags import RMP_TAG_MAP, TAG_HINTS, TAG_TAXONOMY

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

YES = {"yes", "y", "true", "mandatory"}

all_hints = sorted({h for hints in TAG_HINTS.values() for h in hints}, key=len, reverse=True)
HINT_RE = re.compile(r"\b(" + "|".join(re.escape(h) for h in all_hints) + r")\b", re.IGNORECASE)

# same thing but per tag, used to throw out tags the review never mentions
TAG_RES = {
    tag: re.compile(r"\b(" + "|".join(re.escape(h) for h in sorted(hints, key=len, reverse=True)) + r")\b", re.IGNORECASE)
    for tag, hints in TAG_HINTS.items()
}


def structured_tags(row):
    tags = set()
    if (row.get("attendance") or "").strip().lower() in YES:
        tags.add("mandatory_attendance")
    if (row.get("textbook") or "").strip().lower() in YES:
        tags.add("requires_textbook")
    rmp_tags = (row.get("tags") or "").lower()
    for phrase, tag in RMP_TAG_MAP.items():
        if phrase in rmp_tags:
            tags.add(tag)
    return tags


def might_have_tags(text):
    return bool(text) and HINT_RE.search(text) is not None


def build_prompt(reviews):
    tag_list = "\n".join(f"- {name}: {desc}" for name, desc in TAG_TAXONOMY.items())
    review_list = "\n".join(f'{r["id"]}: {json.dumps(r["text"])}' for r in reviews)
    return (
        "Tag these student reviews of professors.\n\n"
        f"Only use these tags:\n{tag_list}\n\n"
        "Only add a tag if the review clearly says it, most reviews have one or two tags or none. If it says the opposite "
        "(like \"doesn't take attendance\") don't tag it.\n\n"
        f"Reviews:\n{review_list}\n\n"
        'Reply with only JSON like {"<review_id>": ["tag1", "tag2"]}. Skip reviews with no tags.'
    )


def parse_tag_response(raw, valid_ids):
    # model output can be messy, only keep ids we sent and tags on our list
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}

    valid_ids = {str(i) for i in valid_ids}
    result = {}
    for rid, tags in raw.items():
        rid = str(rid)
        if rid not in valid_ids or not isinstance(tags, list):
            continue
        good = sorted({t for t in tags if isinstance(t, str) and t in TAG_TAXONOMY})
        if good:
            result[rid] = good
    return result


def _call_ollama(prompt):
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["message"]["content"]


def extract_tags(reviews):
    # returns None if ollama failed so the batch gets retried next run,
    # {} just means it worked and nothing matched
    if not reviews:
        return {}
    try:
        content = _call_ollama(build_prompt(reviews))
    except Exception as e:
        print(f"  ollama call failed: {e}")
        return None
    texts = {str(r["id"]): r["text"] for r in reviews}
    parsed = parse_tag_response(content, texts.keys())

    # the model sometimes makes up tags (extra_credit on reviews that never say it),
    # so only keep a tag if the review has at least one of its keywords
    result = {}
    for rid, tags in parsed.items():
        kept = [t for t in tags if TAG_RES[t].search(texts[rid])]
        if kept:
            result[rid] = kept
    return result
