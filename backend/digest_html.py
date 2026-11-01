"""Table-and-inline-style HTML fragments for the review digest email."""

from html import escape

GREEN = "#27ae60"
AMBER = "#f39c12"
AMBER_TEXT = "#e08e0b"
RED = "#e74c3c"
BRAND = "#d6394c"

_FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "Consolas,Menlo,monospace"
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0"'
_LIST = "font-size:12px;color:#444;"
_CELL = "padding:2px 0;"
_VALUE = "font-weight:700;color:#222;"
_FIGURE = "font-size:20px;font-weight:800;line-height:1;"
_CAPTION = "font-size:11px;color:#666;margin-top:4px;"


def _e(s):
    return escape(s, quote=True)


def pct(used, limit):
    return used * 100 // limit


def color(percent):
    if percent >= 80:
        return RED
    if percent >= 50:
        return AMBER
    return GREEN


def section(title, body, first=False):
    pad = "20px 20px 0" if first else "24px 20px 0"
    return (
        f'<tr><td style="padding:{pad};">'
        '<div style="font-size:11px;font-weight:700;letter-spacing:.06em;'
        f'text-transform:uppercase;color:{BRAND};margin-bottom:8px;">{_e(title)}</div>'
        f"{body}</td></tr>"
    )


def tiles(items):
    width = 100 // len(items)
    last = len(items) - 1
    cells = []
    for i, (n, label) in enumerate(items):
        bg, fg = ("#fef0f0", f"color:{BRAND};") if n else ("#f6f6f8", "color:#bbb;")
        radius = "8px 0 0 8px" if i == 0 else "0 8px 8px 0" if i == last else ""
        if i == 0 and i == last:
            radius = "8px"
        r = f"border-radius:{radius};" if radius else ""
        cells.append(
            f'<td width="{width}%" align="center" style="padding:8px 0;background:{bg};{r}">'
            f'<div style="{_FIGURE}{fg}">{n}</div>'
            f'<div style="{_CAPTION}">{_e(label)}</div></td>'
        )
    return f"<table {_TABLE}><tr>{''.join(cells)}</tr></table>"


def rows(items, title=None):
    if not items:
        return ""
    out = [f'<table {_TABLE} style="{_LIST}margin-top:12px;">']
    if title:
        out.append(
            f'<tr><td colspan="2" style="padding-bottom:4px;font-weight:700;color:#222;">{_e(title)}</td></tr>'
        )
    for label, value in items:
        out.append(
            f'<tr><td style="{_CELL}">{_e(label)}</td>'
            f'<td align="right" style="{_VALUE}white-space:nowrap;padding-left:8px;">{_e(value)}</td></tr>'
        )
    out.append("</table>")
    return "".join(out)


def callout(heading, body_html):
    return (
        '<div style="margin-top:12px;padding:10px 12px;border:1px solid #f3c6cc;border-radius:8px;">'
        f'<div style="font-size:13px;font-weight:700;">{_e(heading)}</div>'
        f'<div style="font-size:12px;color:#444;margin-top:4px;line-height:1.5;">{body_html}</div>'
        "</div>"
    )


def command(text):
    return (
        f'<div style="font-family:{_MONO};font-size:11px;color:#444;background:#f6f6f8;'
        f'border-radius:4px;padding:6px 8px;margin-top:8px;line-height:1.5;">{_e(text)}</div>'
    )


def numbers(items):
    cells = "".join(
        f'<td><div style="{_FIGURE}color:{c};">{n}</div>'
        f'<div style="{_CAPTION}">{_e(label)}</div></td>'
        for n, label, c in items
    )
    return f"<table {_TABLE}><tr>{cells}</tr></table>"


def day_bars(days, height=40):
    busiest = max((live + held for live, held in days), default=0)
    last = len(days) - 1
    cells = []
    for i, (live, held) in enumerate(days):
        segs = []
        for value, bg in (
            (held, AMBER),
            (live, BRAND if i == last else GREEN),
        ):
            if value:
                px = max(1, round(value * height / busiest))
                segs.append(f'<div style="width:8px;height:{px}px;background:{bg};"></div>')
        cells.append(f'<td align="center">{"".join(segs)}</td>')
    return (
        f'<table {_TABLE}><tr valign="bottom" style="height:{height}px;">{"".join(cells)}</tr></table>'
        '<div style="font-size:11px;color:#999;margin-top:4px;text-align:right;">Last 14 days</div>'
    )


def stacked_bar(parts):
    parts = [(n, c) for n, c in parts if n]
    if not parts:
        parts = [(1, "#cfcfd6")]
    total = sum(n for n, _ in parts)
    last = len(parts) - 1
    used = 0
    cells = []
    for i, (n, c) in enumerate(parts):
        w = 100 - used if i == last else n * 100 // total
        used += w
        radius = "4px 0 0 4px" if i == 0 else "0 4px 4px 0" if i == last else ""
        if i == 0 and i == last:
            radius = "4px"
        r = f"border-radius:{radius};" if radius else ""
        cells.append(f'<td width="{w}%" style="background:{c};{r}"></td>')
    return f'<table {_TABLE}><tr style="height:8px;">{"".join(cells)}</tr></table>'


def legend(parts):
    last = len(parts) - 1
    cells = []
    for i, (n, label, c) in enumerate(parts):
        align = ' align="right"' if i == last else ""
        cells.append(
            f'<td{align} style="white-space:nowrap;"><b style="color:{c};">{n}</b> {_e(label)}</td>'
        )
    return (
        f'<table {_TABLE} style="font-size:12px;color:#666;margin-top:8px;">'
        f'<tr>{"".join(cells)}</tr></table>'
    )


def meter(label, used, limit, shown):
    p = min(100, pct(used, limit))
    c = color(p)
    value = f"white-space:nowrap;color:{AMBER_TEXT};font-weight:700;" if c == AMBER else (
        f"white-space:nowrap;color:{c};font-weight:700;" if c == RED else "white-space:nowrap;"
    )
    fill = f'<td width="{p}%" style="background:{c};border-radius:3px 0 0 3px;"></td>' if p else ""
    return (
        f'<tr><td style="padding:4px 8px 4px 0;white-space:nowrap;">{_e(label)}</td>'
        f'<td width="45%" style="padding:4px 0;"><table {_TABLE}><tr style="height:6px;">'
        f'{fill}<td style="background:#ececf1;border-radius:0 3px 3px 0;"></td></tr></table></td>'
        f'<td align="right" style="padding:4px 0 4px 8px;{value}">{_e(shown)}</td></tr>'
    )


def meter_note(text):
    return f'<tr><td colspan="3" style="padding:4px 0;font-size:11px;color:#999;">{_e(text)}</td></tr>'


def page(subject, dateline, body, footer):
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(subject)}</title>"
        "<style>@media (max-width: 480px) {"
        ".col { display: block !important; width: 100% !important; }"
        ".col-chart { padding: 12px 0 0 !important; }}</style></head>"
        f'<body style="margin:0;background:#e9e9ee;font-family:{_FONT};color:#222;">'
        f'<table {_TABLE} style="max-width:560px;margin:16px auto 32px;background:#fff;border-radius:10px;">'
        '<tr><td style="padding:16px 20px;border-bottom:1px solid #eee;">'
        f'<div style="font-size:15px;font-weight:700;line-height:1.4;">{_e(subject)}</div>'
        f'<div style="font-size:12px;color:#888;margin-top:4px;">{_e(dateline)}</div></td></tr>'
        f"{body}"
        '<tr><td style="padding:24px 20px 16px;">'
        '<div style="border-top:1px solid #eee;padding-top:12px;font-size:11px;color:#999;line-height:1.6;">'
        f"{footer}</div></td></tr></table></body></html>"
    )
