"""
Make small WebP copies of every professor photo, served from the site itself.

The photos are hotlinked from ~165 university hosts at full size (up to ~1 MB,
1400 px wide) and shown in 54-160 px boxes, so each one took 2+ seconds to
appear. This downloads each professors.image_url once, shrinks its short side
to SHORT_SIDE (2x the tallest box, for retina) keeping the aspect ratio so
focus_x / focus_y still crop it the same way, and writes it to
frontend/public/photos/<thumb_name(url)>. The frontend computes the same name
(frontend/src/utils/photoThumb.ts) and falls back to the original URL when a
file is missing, so a photo added since the last run still shows.

Existing files are skipped, so a rerun only fetches new photos. A photo
replaced at the same URL keeps its old thumbnail until a --refresh run, which
downloads everything again and rewrites only the files whose image changed.
Run it after photos change, then commit frontend/public/photos/.

Reads ORACLE_DATABASE_URL from backend/.env.

Run:  python backend/photo_thumbs.py            # fetch what's missing
      python backend/photo_thumbs.py --refresh  # also re-check existing ones
      python backend/photo_thumbs.py --prune    # also delete files no professor uses
"""

import argparse
import io
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

SHORT_SIDE = 320
QUALITY = 72
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "public", "photos")


def _imul(a, b):
    return (a * b) & 0xFFFFFFFF


def thumb_name(url):
    """cyrb53 of the URL in hex, plus .webp. Must match photoThumb.ts exactly:
    JavaScript hashes UTF-16 code units, so this does too."""
    data = url.encode("utf-16-le")
    h1, h2 = 0xDEADBEEF, 0x41C6CE57
    for i in range(0, len(data), 2):
        ch = data[i] | (data[i + 1] << 8)
        h1 = _imul(h1 ^ ch, 2654435761)
        h2 = _imul(h2 ^ ch, 1597334677)
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507)
    h1 ^= _imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507)
    h2 ^= _imul(h1 ^ (h1 >> 13), 3266489909)
    return format(4294967296 * (2097151 & h2) + h1, "x") + ".webp"


def make_thumbnail(raw):
    """WebP bytes of the image with its short side at most SHORT_SIDE."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    if img.mode in ("RGBA", "LA", "P", "PA") or "transparency" in img.info:
        img = img.convert("RGBA")
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    elif img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    scale = SHORT_SIDE / min(w, h)
    if scale < 1:
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=QUALITY, method=6)
    return out.getvalue()


def photo_urls():
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    url = os.getenv("ORACLE_DATABASE_URL")
    if not url:
        sys.exit("Missing ORACLE_DATABASE_URL in backend/.env")
    conn = psycopg2.connect(url, sslmode="require", connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT image_url FROM professors WHERE image_url IS NOT NULL AND image_url <> ''")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_one(session, url, path):
    """Returns (url, outcome, error or None); outcome is "new", "updated",
    "unchanged" or "failed". Never raises: one bad photo must not stop the run."""
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code != 200 or not resp.content:
            return url, "failed", f"HTTP {resp.status_code}"
        thumb = make_thumbnail(resp.content)
    except Exception as e:
        return url, "failed", f"{type(e).__name__}: {e}"

    existed = os.path.exists(path)
    tmp = path + ".tmp"
    try:
        if existed:
            with open(path, "rb") as f:
                if f.read() == thumb:   # same photo: leave the file alone, so git sees no change
                    return url, "unchanged", None
        with open(tmp, "wb") as f:
            f.write(thumb)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return url, "failed", f"write {type(e).__name__}: {e}"
    return url, "updated" if existed else "new", None


def remove_partial_writes(out_dir):
    """Delete .tmp files a killed run left behind, so they can't be committed."""
    leftovers = [f for f in os.listdir(out_dir) if f.endswith(".tmp")]
    for f in leftovers:
        os.remove(os.path.join(out_dir, f))
    return len(leftovers)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--prune", action="store_true", help="delete thumbnails no professor uses any more")
    ap.add_argument("--refresh", action="store_true",
                    help="re-download photos that already have thumbnails and rewrite any that changed")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    import requests

    os.makedirs(OUT_DIR, exist_ok=True)
    leftovers = remove_partial_writes(OUT_DIR)
    if leftovers:
        print(f"removed {leftovers} partial .tmp files from an earlier run")
    urls = photo_urls()
    wanted = {thumb_name(u): u for u in urls}
    todo = [(u, os.path.join(OUT_DIR, name)) for name, u in wanted.items()
            if args.refresh or not os.path.exists(os.path.join(OUT_DIR, name))]
    print(f"{len(urls)} photos, {len(urls) - len(todo)} already have thumbnails, fetching {len(todo)}")

    # One Session per worker thread: requests doesn't promise a shared one is thread-safe
    local = threading.local()

    def worker_session():
        if not hasattr(local, "session"):
            local.session = requests.Session()
            local.session.headers["User-Agent"] = "Mozilla/5.0 (compatible; RateMyHusky photo thumbnails)"
        return local.session

    counts = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
    failed = []
    with ThreadPoolExecutor(args.workers) as pool:
        for i, (url, outcome, err) in enumerate(pool.map(lambda t: fetch_one(worker_session(), *t), todo), 1):
            counts[outcome] += 1
            if err:
                failed.append((url, err))
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}")

    if args.prune:
        stale = [f for f in os.listdir(OUT_DIR) if f.endswith(".webp") and f not in wanted]
        for f in stale:
            os.remove(os.path.join(OUT_DIR, f))
        print(f"pruned {len(stale)} unused thumbnails")

    total = sum(os.path.getsize(os.path.join(OUT_DIR, f)) for f in os.listdir(OUT_DIR) if f.endswith(".webp"))
    print(f"done: {counts['new']} new, {counts['updated']} updated, {counts['unchanged']} unchanged, "
          f"{counts['failed']} failed (these keep the original URL); folder is {total / 1e6:.1f} MB")
    for url, err in failed:
        print(f"  FAILED {err}  {url}")


if __name__ == "__main__":
    main()
