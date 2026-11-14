import os, sys, json, argparse, time

KEY_STORE = os.path.join(os.path.dirname(__file__), "..", "groq_keys.local.json")
DEFAULT_RPD = 1000
DEFAULT_TPD = 200000  # synthesis model (gpt-oss-120b) free-tier TPD; TPD binds before RPD

def _entry(key):
    return {"key": key, "rpd_limit": DEFAULT_RPD, "tpd_limit": DEFAULT_TPD}

def load_entries():
    # Preferred: lowercase groq1, groq2, ... groqN env vars (contiguous from 1).
    env_keys = []
    n = 1
    while True:
        val = os.getenv("groq%d" % n)
        if not val:
            break
        env_keys.append(_entry(val))
        n += 1
    if env_keys:
        return env_keys
    # Or one comma-separated GROQ_API_KEYS (what the README documents).
    listed = [k.strip() for k in (os.getenv("GROQ_API_KEYS") or "").split(",") if k.strip()]
    if listed:
        return [_entry(k) for k in listed]
    # Fallback: gitignored JSON store.
    if os.path.exists(KEY_STORE):
        with open(KEY_STORE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("keys", data) if isinstance(data, dict) else data
    # Last resort: a single GROQ_API_KEY.
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        return [_entry(env_key)]
    return []

def _zero_usage(_key):
    return {"rpd": 0, "tpd": 0}

DEFAULT_COOLDOWN_SECONDS = 60

class KeyPool:
    def __init__(self, entries=None, usage_fn=None):
        self.entries = entries if entries is not None else load_entries()
        self.usage_fn = usage_fn or _zero_usage
        self.idx = 0
        self.exhausted = {}  # key -> retry_at timestamp (cooldown, not permanent)

    def _covers(self, entry, est_tokens):
        retry_at = self.exhausted.get(entry["key"])
        if retry_at is not None:
            if retry_at > time.time():
                return False
            del self.exhausted[entry["key"]]
        u = self.usage_fn(entry["key"])
        if u["rpd"] >= entry["rpd_limit"]:
            return False
        if u["tpd"] + est_tokens > entry["tpd_limit"]:
            return False
        return True

    def current(self):
        return self.entries[self.idx] if 0 <= self.idx < len(self.entries) else None

    def acquire(self, est_tokens):
        n = len(self.entries)
        for offset in range(n):
            i = (self.idx + offset) % n
            if self._covers(self.entries[i], est_tokens):
                self.idx = i
                return self.entries[i]
        return None

    def retire(self, key, cooldown_seconds=DEFAULT_COOLDOWN_SECONDS):
        self.exhausted[key] = time.time() + cooldown_seconds
        if self.current() and self.current()["key"] == key:
            self.idx = (self.idx + 1) % max(len(self.entries), 1)

def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    entries = [
        {"key": "k1", "rpd_limit": 1000, "tpd_limit": 500000},
        {"key": "k2", "rpd_limit": 1000, "tpd_limit": 500000},
    ]
    # k1 is at its RPD limit; acquire must advance to k2 before returning.
    usage = {"k1": {"rpd": 1000, "tpd": 10}, "k2": {"rpd": 0, "tpd": 0}}
    pool = KeyPool(entries, usage_fn=lambda k: usage[k])
    chosen = pool.acquire(est_tokens=1800)
    check("acquire advances past over-limit RPD entry", chosen and chosen["key"] == "k2")

    # Both entries clear the RPD check but would exceed tpd_limit with this
    # request, so the TPD predicate alone leaves no usable entry.
    usage2 = {"k1": {"rpd": 0, "tpd": 499999}, "k2": {"rpd": 0, "tpd": 499999}}
    pool2 = KeyPool(entries, usage_fn=lambda k: usage2[k])
    check("TPD overflow leaves no usable entry",
          pool2.acquire(est_tokens=1800) is None)

    # retire the current entry, then acquire resolves to the other one.
    usage3 = {"k1": {"rpd": 0, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}}
    pool3 = KeyPool(entries, usage_fn=lambda k: usage3[k])
    first = pool3.acquire(est_tokens=10)
    pool3.retire(first["key"])
    second = pool3.acquire(est_tokens=10)
    check("acquire skips a retired entry", second["key"] != first["key"])

    check("empty pool returns None", KeyPool([]).acquire(10) is None)

    # Issue 2: retirement is a cooldown, not a permanent death sentence. Retire k1, confirm
    # acquire() skips it while the clock is within the cooldown window, then advance a
    # monkeypatched clock past cooldown and confirm k1 becomes acquirable again.
    usage4 = {"k1": {"rpd": 0, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}}
    pool4 = KeyPool(entries, usage_fn=lambda k: usage4[k])
    fake_now = [1000.0]
    real_time = time.time
    time.time = lambda: fake_now[0]
    try:
        pool4.retire("k1", cooldown_seconds=60)
        during = pool4.acquire(est_tokens=10)
        check("acquire skips a key still in cooldown", during["key"] == "k2")
        fake_now[0] += 61
        after = KeyPool(entries, usage_fn=lambda k: usage4[k])
        after.exhausted = pool4.exhausted  # carry the same cooldown state past the clock jump
        recovered = after.acquire(est_tokens=10)
        check("acquire returns key once cooldown has elapsed", recovered["key"] == "k1")
        check("expired cooldown entry is removed from exhausted", "k1" not in after.exhausted)
    finally:
        time.time = real_time
    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0

def main():
    p = argparse.ArgumentParser(description="Provider-agnostic LLM access provider.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")

if __name__ == "__main__":
    main()
