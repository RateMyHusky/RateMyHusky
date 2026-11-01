import re

import digest_html as h


def test_tiles_emphasize_nonzero_and_grey_zero():
    out = h.tiles([(3, "held"), (0, "courses")])
    assert "#fef0f0" in out and ">3<" in out
    assert "color:#bbb" in out and ">0<" in out


def test_rows_put_each_item_in_its_own_row():
    out = h.rows([("a", "1"), ("b", "2"), ("c", "3")], title="Why")
    assert out.count("<tr>") == 4  # title row + three items
    assert h.rows([("a", "1"), ("b", "2"), ("c", "3")]).count("<tr>") == 3
    assert h.rows([]) == ""


def test_strings_are_escaped():
    raw = "<b>x</b> & y"
    esc = "&lt;b&gt;x&lt;/b&gt; &amp; y"
    outs = [
        h.rows([(raw, "1")]),
        h.tiles([(1, raw)]),
        h.legend([(1, raw, "#27ae60")]),
        h.meter(raw, 1, 10, "1 / 10"),
        h.command(raw),
    ]
    for out in outs:
        assert esc in out
        assert "<b>x</b>" not in out


def test_day_bars_scale_to_the_busiest_day():
    out = h.day_bars([(0, 0)] * 12 + [(30, 10), (10, 0)])
    assert "height:30px;background:#27ae60" in out
    assert "height:10px;background:#f39c12" in out
    assert "height:10px;background:#d6394c" in out
    assert out.count("<td") == 14
    assert "Last 14 days" in out


def test_day_bars_on_a_quiet_fortnight():
    out = h.day_bars([(0, 0)] * 14)
    assert out.count("<td") == 14
    assert "height:0px" not in out


def test_a_tiny_day_still_shows():
    out = h.day_bars([(1, 0)] + [(0, 0)] * 12 + [(1000, 0)])
    first = out.split("<td")[1]
    assert "height:1px" in first


def test_stacked_bar_widths_sum_to_100():
    out = h.stacked_bar(
        [(6, "#27ae60"), (3, "#e74c3c"), (1, "#f39c12"), (1, "#cfcfd6")]
    )
    widths = [int(w) for w in re.findall(r'<td width="(\d+)%"', out)]
    assert len(widths) == 4 and sum(widths) == 100
    out = h.stacked_bar([(6, "#27ae60"), (0, "#e74c3c")])
    assert out.count("<td") == 1
    out = h.stacked_bar([(0, "#27ae60")])
    assert out.count("<td") == 1 and "#cfcfd6" in out and 'width="100%"' in out


def test_meter_colors():
    assert h.pct(49, 100) == 49
    assert h.color(49) == "#27ae60"
    assert h.color(50) == "#f39c12"
    assert h.color(79) == "#f39c12"
    assert h.color(80) == "#e74c3c"
    out = h.meter("Groq checker", 129000, 200000, "129K / 200K tokens")
    assert 'width="64%"' in out
    assert "#f39c12" in out
    assert "color:#e08e0b;font-weight:700" in out
    assert 'width="100%"' in h.meter("x", 150, 100, "150 / 100")


def test_no_middot_anywhere():
    html = "".join([
        h.section("Title", "body", first=True),
        h.tiles([(1, "a"), (0, "b")]),
        h.rows([("a", "1")], title="t"),
        h.callout("Head", "body"),
        h.command("python x.py"),
        h.numbers([(1, "new", "#222")]),
        h.day_bars([(1, 1)] * 14),
        h.stacked_bar([(1, "#27ae60")]),
        h.legend([(1, "a", "#27ae60"), (2, "b", "#e74c3c")]),
        h.meter("m", 1, 2, "1 / 2"),
        h.meter_note("note"),
        h.page("s", "d", "b", "f"),
    ])
    assert "\u00b7" not in html


def test_page_is_a_full_document():
    out = h.page("A & B", "Sat <1>", "<tr><td>x</td></tr>", "foot")
    assert out.startswith("<!DOCTYPE html>")
    assert "A &amp; B" in out and "Sat &lt;1&gt;" in out
    assert "max-width:560px" in out
    assert "<script" not in out and "<svg" not in out


def test_row_values_never_wrap():
    assert "white-space:nowrap" in h.rows([("a", "2 ratings, 2 held")])
