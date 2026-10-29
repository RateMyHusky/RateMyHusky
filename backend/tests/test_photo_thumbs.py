"""photo_thumbs: file names match the frontend's, and thumbnails are small."""

import io

from PIL import Image

import photo_thumbs

# Computed with the reference cyrb53 in JavaScript; frontend/src/utils/photoThumb.selftest.ts
# checks the same vectors, so the two sides name every file the same way.
VECTORS = [
    ("", "bdcb81aee8d83"),
    ("a", "1c2ba782c97901"),
    ("https://cssh.northeastern.edu/wp-content/uploads/2020/01/Block-Aaron-414-x-512-px.png", "4fd4a9c944f20"),
    ("https://example.com/José-😀.jpg", "18a7399017e0d"),
]


def test_thumb_name_matches_javascript():
    for url, expected in VECTORS:
        assert photo_thumbs.thumb_name(url) == f"{expected}.webp", url


def _png(w, h, mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (w, h), (200, 100, 50, 255) if mode == "RGBA" else (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


def test_shrinks_short_side_and_keeps_aspect():
    out = Image.open(io.BytesIO(photo_thumbs.make_thumbnail(_png(1400, 933))))
    assert out.format == "WEBP"
    assert min(out.size) == photo_thumbs.SHORT_SIDE
    assert abs(out.size[0] / out.size[1] - 1400 / 933) < 0.01


def test_never_upscales_small_photos():
    out = Image.open(io.BytesIO(photo_thumbs.make_thumbnail(_png(200, 250))))
    assert out.size == (200, 250)


def test_flattens_transparency():
    out = Image.open(io.BytesIO(photo_thumbs.make_thumbnail(_png(800, 800, "RGBA"))))
    assert out.mode == "RGB"


def test_color_keyed_transparency_becomes_white():
    # An RGB PNG with a transparent color key used to lose its alpha and come out black
    img = Image.new("RGB", (400, 400), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG", transparency=(0, 0, 0))
    out = Image.open(io.BytesIO(photo_thumbs.make_thumbnail(buf.getvalue())))
    assert min(out.getpixel((200, 200))) > 240


class _Resp:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


class _Session:
    """Stands in for requests.Session: every get() returns the same photo."""
    def __init__(self, content, status_code=200):
        self.resp = _Resp(content, status_code)

    def get(self, url, timeout):
        return self.resp


def test_new_then_unchanged_then_updated(tmp_path):
    path = str(tmp_path / "x.webp")
    assert photo_thumbs.fetch_one(_Session(_png(400, 500)), "u", path)[1:] == ("new", None)
    first = open(path, "rb").read()

    # Same photo again: reported unchanged and the file is not rewritten
    mtime = (tmp_path / "x.webp").stat().st_mtime_ns
    assert photo_thumbs.fetch_one(_Session(_png(400, 500)), "u", path)[1:] == ("unchanged", None)
    assert (tmp_path / "x.webp").stat().st_mtime_ns == mtime

    # A different photo at the same URL replaces the file
    assert photo_thumbs.fetch_one(_Session(_png(500, 400)), "u", path)[1:] == ("updated", None)
    assert open(path, "rb").read() != first


def test_write_failure_is_reported_not_raised(tmp_path):
    path = str(tmp_path / "missing-dir" / "x.webp")
    url, outcome, err = photo_thumbs.fetch_one(_Session(_png(400, 500)), "u", path)
    assert outcome == "failed" and err.startswith("write ")
    assert not (tmp_path / "missing-dir").exists()


def test_download_failure_is_reported(tmp_path):
    outcome, err = photo_thumbs.fetch_one(_Session(b"", 404), "u", str(tmp_path / "x.webp"))[1:]
    assert (outcome, err) == ("failed", "HTTP 404")
    assert list(tmp_path.iterdir()) == []


def test_removes_partial_writes_only(tmp_path):
    (tmp_path / "a.webp").write_bytes(b"keep")
    (tmp_path / "b.webp.tmp").write_bytes(b"partial")
    assert photo_thumbs.remove_partial_writes(str(tmp_path)) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.webp"]
