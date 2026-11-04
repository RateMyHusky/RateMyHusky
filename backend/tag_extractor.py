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


def _phrase_re(words):
    words = sorted(set(words), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


TAG_RES = {tag: [_phrase_re(group) for group in groups] for tag, groups in TAG_HINTS.items()}


def text_supports(tag, text):
    # true if the review hits every keyword group for this tag
    return bool(text) and all(r.search(text) for r in TAG_RES[tag])


def might_have_tags(text):
    return any(text_supports(tag, text) for tag in TAG_RES)


def structured_tags(row):
    tags = set()
    rmp_tags = (row.get("tags") or "").lower()
    for phrase, tag in RMP_TAG_MAP.items():
        if phrase in rmp_tags:
            tags.add(tag)
    return tags


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
    # None means the output was unusable and the batch should be retried
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None

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
    # returns None if ollama failed or sent back garbage so the batch gets retried,
    # {} just means it worked and nothing matched
    if not reviews:
        return {}

    # the model gets ids 1..N instead of the real 19 digit ones, it mangles those
    local = {str(n): r for n, r in enumerate(reviews, start=1)}
    prompt_reviews = [{"id": n, "text": r["text"]} for n, r in local.items()]
    try:
        content = _call_ollama(build_prompt(prompt_reviews))
    except Exception as e:
        print(f"  ollama call failed: {e}")
        return None

    parsed = parse_tag_response(content, local.keys())
    if parsed is None:
        print("  model sent back bad json, will retry")
        return None

    result = {}
    for n, tags in parsed.items():
        review = local[n]
        # the model sometimes makes up tags, only keep ones the review has keywords for
        kept = [t for t in tags if text_supports(t, review["text"])]
        if kept:
            result[str(review["id"])] = kept
    return result
