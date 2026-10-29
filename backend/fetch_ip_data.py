"""Boot-time download of the ipinfo ASN database and Apple's Private Relay ranges.

Runs before gunicorn (see Procfile) and always exits 0: missing data only makes
network types "unknown", which never holds a rating. A file fetched in the last
day is kept, and each download gives up after DEADLINE seconds in total, so a
slow server can't hold up the boot for long.
"""

import os
import sys
import time

import requests as http_requests

IPINFO_URL = "https://ipinfo.io/data/ipinfo_lite.mmdb?token={token}"
RELAY_URL = "https://mask-api.icloud.com/egress-ip-ranges.csv"
DEADLINE = 60
FRESH_SECONDS = 86400


def _fetch(url: str, path: str) -> None:
    # requests' timeout is per socket read, so check the total time between chunks.
    deadline = time.monotonic() + DEADLINE
    tmp = path + ".tmp"
    with http_requests.get(url, timeout=20, stream=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"not done after {DEADLINE} s")
                f.write(chunk)
    os.replace(tmp, path)


def main() -> int:
    data_dir = os.environ.get("IP_DATA_DIR", "/tmp/ipdata")
    token = os.environ.get("IPINFO_TOKEN")
    os.makedirs(data_dir, exist_ok=True)
    jobs = [("ipinfo_lite.mmdb", IPINFO_URL.format(token=token) if token else None),
            ("relay.csv", RELAY_URL)]
    for name, url in jobs:
        if url is None:
            print(f"[fetch_ip_data] {name} skipped: IPINFO_TOKEN not set")
            continue
        path = os.path.join(data_dir, name)
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < FRESH_SECONDS:
            print(f"[fetch_ip_data] {name} kept: fetched in the last day")
            continue
        try:
            _fetch(url, path)
            print(f"[fetch_ip_data] {name} fetched")
        except Exception as e:
            reason = str(e).replace(token, "***") if token else str(e)
            print(f"[fetch_ip_data] {name} failed: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
