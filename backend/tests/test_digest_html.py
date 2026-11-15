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
    assert "height:10px;background:#27ae60" in out  # today is green like every other day
    assert out.count('<td align="center">') == 14
    assert ">40</div><div>0</div>" in out  # the scale tops out at the busiest day
    assert "13 days ago" in out and "Today" in out


def test_every_day_has_a_track_so_a_lone_bar_has_something_to_sit_beside():
    out = h.day_bars([(0, 0)] * 13 + [(1, 0)])
    days = out.split('<td align="center">')[1:]
    assert all(f"height:40px;background:{h.TRACK}" in d for d in days[:13])
    assert "height:40px;background:#27ae60" in days[13] and h.TRACK not in days[13]
    assert ">1</div><div>0</div>" in out


def test_day_bars_on_a_quiet_fortnight():
    out = h.day_bars([(0, 0)] * 14)
    assert out.count(f"height:40px;background:{h.TRACK}") == 14
    assert "height:0px" not in out


def test_a_tiny_day_still_shows():
    out = h.day_bars([(1, 0)] + [(0, 0)] * 12 + [(1000, 0)])
    first = out.split('<td align="center">')[1]
    assert f"height:39px;background:{h.TRACK}" in first and "height:1px;background:#27ae60" in first


def test_every_day_column_adds_up_to_the_chart_height():
    # Rounding each segment up to 1px on its own used to push these columns past 40px.
    for days in ([(79, 1)], [(1, 1000)], [(1, 999), (1001, 0)]):
        out = h.day_bars([(0, 0)] * (14 - len(days)) + days)
        cols = [c.split("</td>")[0] for c in out.split('<td align="center">')[1:]]
        assert all(sum(int(px) for px in re.findall(r"height:(\d+)px", c)) == 40 for c in cols)
    assert f"background:{h.AMBER}" in cols[12] and f"background:{h.GREEN}" in cols[12]


def test_day_bar_segments_have_no_line_height_floor():
    # Outlook and Gmail grow an empty div to the line height unless the font is zeroed.
    out = h.day_bars([(0, 0)] * 13 + [(3, 1)])
    segs = re.findall(r'<div style="(width:8px;[^"]*)">', out)
    assert segs and all("font-size:0;line-height:0;" in s for s in segs)


def test_day_bars_scale_uses_thousands_separators():
    assert ">1,500</div><div>0</div>" in h.day_bars([(0, 0)] * 13 + [(1500, 0)])


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
