"""Build the per-college master professor list for the photo re-scrape.

Merges rmp_professors.csv + trace_courses.csv, dedups by normalized name,
attaches college (pipeline.names.COLLEGE_MAP), aliases, and any existing photo URL.
Writes output_data/prof_list.json.
"""
import os
import sys
import csv
import json
import re
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pipeline.names import normalize_name  # noqa: E402
import photo_research as pr  # noqa: E402


def load_existing_photos(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = str(row.get("name", "")).strip()
            url = str(row.get("image_url", "")).strip()
            if name and url:
                out[normalize_name(name)] = url
    return out


def build_records(data_dir):
    idx = pr.build_alias_index()
    existing = load_existing_photos(os.path.join(data_dir, "professor_photos.csv"))
    seen = {}

    def add(name, dept):
        key = normalize_name(name)
        if not key or key in seen:
            return
        eq = pr.aliases_for(name, idx) - {key}
        seen[key] = {
            "name": name,
            "department": dept or "",
            "college": pr.dept_to_college(dept),
            "aliases": sorted(eq),
            "existing_url": existing.get(key, ""),
        }

    rmp = os.path.join(data_dir, "rmp_professors.csv")
    if os.path.exists(rmp):
        with open(rmp, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                add(str(row.get("name", "")).strip(),
                    str(row.get("department", "")).strip())

    trace = os.path.join(data_dir, "trace_courses.csv")
    if os.path.exists(trace):
        with open(trace, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                first = str(row.get("instructorFirstName", "")).strip()
                last = str(row.get("instructorLastName", "")).strip()
                if first and last:
                    add(f"{first} {last}".title(),
                        str(row.get("departmentName", "")).strip())

    return list(seen.values())


def _name_tokens(name):
    """Normalize a name and return its word tokens (lowercase alphanum only)."""
    s = re.sub(r"[^a-z0-9 ]", " ", normalize_name(name))
    return [t for t in s.split() if t]


def collapse_duplicates(records, idx):
    """Collapse records that refer to the same person (alias or name-swap).

    Two records are the same person if:
      1. Alias-equivalent: aliases_for(a) & aliases_for(b) is non-empty.
      2. First/last swap (2-token names only): sorted token lists are equal.

    Uses union-find over record indices.  Returns one merged record per group.
    """
    n = len(records)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # --- Rule 1: alias equivalence ---
    # Map each record to its alias root (min of aliases_for set) then union
    # records sharing the same root.
    alias_root_to_idx = {}
    for i, rec in enumerate(records):
        eq = pr.aliases_for(rec["name"], idx)
        root = min(eq)  # stable canonical key
        if root in alias_root_to_idx:
            union(i, alias_root_to_idx[root])
        else:
            alias_root_to_idx[root] = i

    # --- Rule 2: name-swap / reorder for 2-token names ---
    # Bucket by frozenset of tokens; records in the same bucket that have
    # equal sorted-token lists are swap-equivalent.
    bucket = {}  # frozenset(tokens) -> list of (i, tokens)
    for i, rec in enumerate(records):
        toks = _name_tokens(rec["name"])
        if len(toks) == 2:
            key = frozenset(toks)
            bucket.setdefault(key, []).append((i, toks))

    for group in bucket.values():
        if len(group) < 2:
            continue
        # All entries in this bucket have the same frozenset; for 2-token
        # names that means sorted() matches — union all of them.
        first_idx = group[0][0]
        for j in range(1, len(group)):
            union(first_idx, group[j][0])

    # --- Build groups ---
    from collections import defaultdict
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    # --- Merge each group into one record ---
    result = []
    for members_idx in groups.values():
        if len(members_idx) == 1:
            result.append(records[members_idx[0]])
            continue

        members = [records[i] for i in members_idx]

        # Canonical: (has_existing_url desc, token_count desc, name asc)
        def sort_key(rec):
            has_url = 0 if rec["existing_url"] else 1
            tok_count = -len(_name_tokens(rec["name"]))
            return (has_url, tok_count, normalize_name(rec["name"]))

        members_sorted = sorted(members, key=sort_key)
        canonical = members_sorted[0]
        others = members_sorted[1:]

        # Merge existing_url: canonical's first, already chosen above
        existing_url = canonical["existing_url"]
        if not existing_url:
            for o in others:
                if o["existing_url"]:
                    existing_url = o["existing_url"]
                    break

        # Merge aliases: union of all members' aliases + other members'
        # normalized names, minus the canonical's own normalized name.
        canonical_norm = normalize_name(canonical["name"])
        merged_aliases = set(canonical["aliases"])
        for o in others:
            merged_aliases.update(o["aliases"])
            merged_aliases.add(normalize_name(o["name"]))
        merged_aliases.discard(canonical_norm)

        result.append({
            "name": canonical["name"],
            "department": canonical["department"],
            "college": canonical["college"],
            "aliases": sorted(merged_aliases),
            "existing_url": existing_url,
        })

    return result


def main():
    p = argparse.ArgumentParser(description="Build per-college professor list")
    p.add_argument("--data-dir", default=None)
    p.add_argument("-o", "--output", default=None)
    args = p.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = args.data_dir or os.path.join(script_dir, "output_data")
    out_path = args.output or os.path.join(data_dir, "prof_list.json")

    records = build_records(data_dir)
    import photo_research as pr
    idx = pr.build_alias_index()
    before = len(records)
    records = collapse_duplicates(records, idx)
    print(f"  collapsed {before - len(records)} duplicate (alias/name-swap) records -> {len(records)}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)

    from collections import Counter
    counts = Counter(r["college"] for r in records)
    print(f"  {len(records)} unique professors")
    for college, n in counts.most_common():
        print(f"    {n:5d}  {college}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
