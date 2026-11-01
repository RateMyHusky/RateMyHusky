import re
from html import escape
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import review_digest
from tests.razzaq_bomb import BOMB

NOW = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)


def H(slug, code, reasons, hours_ago=1, id="00000000-0000", pending_professor_id=None, agent_decision=None, **extra):
    return {"id": id, "professor_slug": slug, "course_code": code, "hold_reasons": reasons,
            "pending_professor_id": pending_professor_id, "agent_decision": agent_decision,
            "created_at": NOW - timedelta(hours=hours_ago), **extra}


def _rows(html):
    return re.findall(r"<tr>.*?</tr>", html)


def _ratings(**kw):
    return {"new": 0, "live": 0, "held": 0, "rejected": 0, "live_all": 0, "comments_all": 0,
            "days": [(0, 0)] * 14, **kw}


def test_a_quiet_day_still_builds_an_email():
    subject, text, html = review_digest.build_digest([], [], 0, 0, NOW)
    assert subject == "[RateMyHusky] Nothing to review, 0 new ratings, limits OK"
    assert "Monday, Nov 2. Covers the last 24 hours." in html


def test_subject_counts_everything_waiting_and_new_ratings():
    held = [H("a", "CS1", "no_timer", id=str(i)) for i in range(3)]
    aliases = [{"id": 1, "alias_key": "herc", "slug": "a", "source": "comment"}]
    subject, _, _ = review_digest.build_digest(held, [], 1, 0, NOW, aliases=aliases, pending_comments=2,
                                               ratings=_ratings(new=42))
    assert subject == "[RateMyHusky] 7 to review, 42 new ratings, limits OK"
    assert review_digest.build_digest([], [], 0, 0, NOW, ratings=_ratings(new=1))[0].count("1 new rating,") == 1


def test_subject_names_amber_and_red_meters_fullest_first():
    meters = [{"label": "Resend today", "used": 31, "limit": 100, "unit": ""},
              review_digest.groq_meter("Groq checker", 850, 1000, 1000, 200000),
              {"label": "Resend month", "used": 1600, "limit": 3000, "unit": ""}]
    subject, _, _ = review_digest.build_digest([], [], 0, 0, NOW, meters=meters)
    assert subject.endswith(", Groq checker at 85%, Resend month at 53%")


def test_reasons_get_plain_labels_one_row_each():
    held = [H("a", "CS1", "burst_prof_day"),
            H("a", "CS2", "burst_prof_day,burst_prof,unverified_pair"),
            H("b", "CS3", "near_duplicate"),
            H("c", "CS4", "weekly_surge")]
    _, text, html = review_digest.build_digest(held, [], 0, 0, NOW)
    for label, n in (("rating burst", 2), ("copied comment", 1), ("course not taught per Banner", 1),
                     ("weekly_surge", 1)):
        assert any(label in r and f">{n}</td>" in r and r.count("<tr>") == 1 for r in _rows(html)), label
        assert f"{label}: {n}" in text


def test_every_reason_code_has_its_label():
    expected = {"unverified_pair": "course not taught per Banner", "unverified_term": "wrong term per Banner",
                "too_fast": "filled in too fast", "no_timer": "no form timer",
                "stale": "form left open too long", "datacenter": "sent from a data center",
                "skew_week": "unusual week for this professor", "duplicate_comment": "copied comment",
                "near_duplicate": "copied comment", "moderation_block": "comment blocked by the checker",
                "silent_hold": "device held after an abuse reject", "burst_anything": "rating burst",
                "burst_prof_day": "rating burst"}
    for code, label in expected.items():
        assert review_digest.reason_label(code) == label
    assert review_digest.reason_label("weekly_surge") == "weekly_surge"


def _bomb_rows():
    start = datetime(2025, 4, 11, 1, 0, tzinfo=timezone.utc)
    return [{"id": f"{i:08x}-aaaa", "professor_slug": "leena-razzaq", "course_code": b["course"],
             "hold_reasons": "burst_prof,near_duplicate", "pending_professor_id": None,
             "agent_decision": "reject", "created_at": start + timedelta(minutes=b["minute"], seconds=i)}
            for i, b in enumerate(BOMB)]


def test_an_attack_is_one_callout_with_one_command():
    rows = _bomb_rows()
    _, text, html = review_digest.build_digest(list(reversed(rows)), [], 0, 0, NOW,
                                               names={"leena-razzaq": "Leena Razzaq"})
    cmd = "python review_ratings.py reject-rating --abuse " + " ".join(r["id"][:8] for r in rows)
    for out in (html, text):
        assert "Reject 1 attack" in out and "23 ratings for Leena Razzaq in" in out and cmd in out
    assert text.count("reject-rating") == 1


def _span_text(minutes_apart, count=4):
    start = datetime(2025, 4, 11, 1, 0, tzinfo=timezone.utc)
    rows = [{**r, "created_at": start + timedelta(minutes=minutes_apart * i)}
            for i, r in enumerate(_bomb_rows()[:count])]
    return review_digest.build_digest(rows, [], 0, 0, NOW)[1]


def test_attack_spans_read_in_minutes_hours_or_days():
    assert "all within 6 minutes" in _span_text(2)
    assert "all within 5 hours" in _span_text(100)
    # group_held never spans days, so check the day wording on _span directly.
    rows = [{"created_at": NOW - timedelta(days=3)}, {"created_at": NOW}]
    assert review_digest._span(rows) == "3 days"


def test_professors_by_name_and_courses_spaced():
    approved = [H("jane-doe", "CS2500", "no_timer", id="abcdef12-0", agent_decision="approve"),
                H("zed", "CS3500", "no_timer", id="12345678-0", agent_decision="approve"),
                H(None, None, "no_timer", id="99999999-0", agent_decision="approve")]
    _, text, html = review_digest.build_digest([], approved, 0, 0, NOW, names={"jane-doe": "Jane Doe"})
    for out in (text, html):
        assert "Agent approved: Jane Doe, CS 2500" in out
        assert "Agent approved: zed, CS 3500" in out
        assert "Agent approved: a new professor, -" in out
    assert "abcdef12" in html
    assert review_digest.course_label("CS3500") == "CS 3500"
    assert review_digest.course_label(None) == "-"


def test_merges_and_nicknames_are_short_rows():
    aliases = [{"id": 12, "alias_key": "herc", "slug": "iraklis", "source": "comment"}]
    _, text, html = review_digest.build_digest(
        [], [], 0, 0, NOW, [{"code": "BIO2299", "resolved_code": "BIOL2299", "n": 2}],
        [{"id": "0a1b2c3d-4", "resolved_slug": "chris", "n": 2, "held": 2}], aliases,
        names={"iraklis": "Iraklis Tsekourakis", "chris": "Christopher Smith"})
    for out in (text, html):
        assert "Merged BIO 2299 into BIOL 2299" in out and "2 ratings" in out
        assert "Merged a new professor into Christopher Smith" in out and "2 ratings, 2 held" in out
        assert 'Nickname "herc" for Iraklis Tsekourakis' in out.replace("&quot;", '"') and "#12" in out
        assert out.count("approve-alias ID") == 1


def test_ratings_section_numbers_chart_and_totals():
    ratings = _ratings(new=42, live=36, held=4, rejected=2, live_all=1284, comments_all=412,
                       days=[(i, 1) for i in range(14)])
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, ratings=ratings)
    for n in ("42", "36", "4", "2"):
        assert f">{n}</div>" in html
    assert "Last 14 days" in html and "1,284" in html and "412" in html
    assert "New ratings: 42\n" in text and "Live ratings, all time: 1,284" in text


def test_agent_bar_counts_decisions():
    approved = [H("a", "CS1", "no_timer", agent_decision="approve") for _ in range(6)]
    recent = {"agent_reviewed_at": NOW - timedelta(hours=2), "updated_at": NOW - timedelta(hours=3)}
    held = ([H("a", "CS1", "no_timer", agent_decision="reject", **recent) for _ in range(3)]
            + [H("b", "CS2", "no_timer", agent_decision="escalate", **recent), H("c", "CS3", "no_timer")])
    merges = [{"code": "A1", "resolved_code": "B1", "n": 1}, {"code": "A2", "resolved_code": "B2", "n": 1}]
    _, text, html = review_digest.build_digest(held, approved, 0, 0, NOW, merges)
    assert "Checked 10 held ratings and made 2 merges." in html
    assert "Checked 10 held ratings and made 2 merges." in text
    for n, label in ((6, "approved"), (3, "reject"), (1, "escalated"), (1, "pending")):
        assert f"{n}</b> {label}</td>" in html
        assert f"{label}: {n}" in text


def test_agent_sentence_and_bar_cover_only_decisions_from_the_last_24_hours():
    def reject(hours, id, slug):
        at = NOW - timedelta(hours=hours)
        return H(slug, "CS1", "burst_prof", agent_decision="reject", id=id, agent_reviewed_at=at, updated_at=at)
    held = [reject(72, "oldoldol-0", "z"), reject(2, "newnewne-0", "a"),
            H("b", "CS2", "no_timer", agent_decision="escalate", agent_reviewed_at=None, updated_at=NOW - timedelta(hours=9))]
    _, text, html = review_digest.build_digest(held, [], 0, 0, NOW)
    assert "Checked 1 held rating." in text and "Checked 1 held rating." in html
    assert "reject: 1" in text and "escalated: 0" in text and "1</b> reject</td>" in html
    assert "--abuse oldoldol" in text and "--abuse newnewne" in text and "Reject 2 attacks" in html


def test_subject_flags_unknown_resend_usage_instead_of_limits_ok():
    note = {"label": "Resend", "note": "Resend usage unavailable: key can't read usage"}
    checker = {"label": "Groq checker", "used": 170000, "limit": 200000, "unit": "tokens"}
    ok = {"label": "Groq agent", "used": 1, "limit": 100, "unit": "tokens"}
    assert review_digest.build_digest([], [], 0, 0, NOW, meters=[note, ok])[0].endswith(", 0 new ratings, Resend usage unknown")
    assert review_digest.build_digest([], [], 0, 0, NOW, meters=[note, checker, ok])[0].endswith(
        ", Groq checker at 85%, Resend usage unknown")
    assert review_digest.build_digest([], [], 0, 0, NOW, meters=[ok])[0].endswith(", limits OK")


def test_meters_render_and_a_note_replaces_resend():
    note = "Resend usage unavailable: key can't read usage"
    meters = [{"label": "Resend", "note": note},
              review_digest.groq_meter("Groq agent", 120, 38000, 6000, 1200000)]
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, meters=meters)
    assert html.count("Resend usage unavailable: key can&#x27;t read usage") == 1
    assert "Groq agent" in html and "38K / 1.2M tokens" in html and "38K / 1.2M tokens" in text
    assert [review_digest.fmt(n) for n in (1212, 38000, 1200000, 2000000)] == ["1,212", "38K", "1.2M", "2M"]
    assert [review_digest.fmt(n) for n in (38412, 129400, 999950)] == ["38K", "129K", "1M"]
    assert "Usage limits" not in review_digest.build_digest([], [], 0, 0, NOW)[2]


def test_groq_meter_shows_the_fuller_limit():
    assert review_digest.groq_meter("Groq checker", 850, 1000, 1000, 200000) == {
        "label": "Groq checker", "used": 850, "limit": 1000, "unit": "requests"}
    assert review_digest.groq_meter("Groq checker", 850, 190000, 1000, 200000) == {
        "label": "Groq checker", "used": 190000, "limit": 200000, "unit": "tokens"}


def test_user_strings_are_escaped():
    aliases = [{"id": 1, "alias_key": "<b>x</b>&", "slug": "ab", "source": "comment"}]
    _, _, html = review_digest.build_digest(_bomb_rows()[:2], [], 0, 0, NOW, aliases=aliases,
                                            names={"ab": "A & B", "leena-razzaq": "<i>L</i>"})
    assert "&lt;b&gt;x&lt;/b&gt;&amp;" in html and "A &amp; B" in html and "&lt;i&gt;L&lt;/i&gt;" in html
    assert "<b>x</b>" not in html and "<i>L</i>" not in html


def test_no_middot_and_one_reason_per_row():
    codes = ["unverified_pair", "unverified_term", "too_fast", "no_timer", "stale", "datacenter", "skew_week",
             "near_duplicate", "moderation_block", "silent_hold", "burst_prof"]
    held = [H("a", "CS1", ",".join(codes))]
    meters = [{"label": "Resend", "note": "note"}, {"label": "Resend today", "used": 1, "limit": 100, "unit": ""}]
    subject, text, html = review_digest.build_digest(held, held, 1, 1, NOW, names={"a": "N" * 60}, meters=meters)
    assert not any("·" in x for x in (subject, text, html))
    labels = {review_digest.reason_label(c) for c in codes}
    assert len(labels) == 11
    reason_rows = [r for r in _rows(html) if r.count("<tr>") == 1 and any(f"<td style=\"padding:2px 0;\">{x}</td>" in r for x in labels)]
    assert len(reason_rows) == 11


def _main(monkeypatch, held, pending=(0, 0), key="re-test", comments=0, approved=(), usage_status=200):
    posts = []

    def fetch(conn, sql, params=None):
        if "AS live_all" in sql:
            return [{"new": 0, "live": 0, "held": 0, "rejected": 0, "live_all": 0, "comments_all": 0}]
        if "AS day" in sql:
            return []
        if "FROM professors WHERE slug" in sql:
            return []
        if "FROM review_agent_runs" in sql:
            return [{"requests": 0, "tokens": 0, "keys": None}]
        if "FROM moderation_calls" in sql:
            return [{"requests": 0, "tokens": 0}]
        if "comment_status" in sql:
            return [{"n": comments}]
        if "FROM survey_ratings" in sql:
            return list(approved) if "agent_decision = 'approve'" in sql else held
        if "resolved_code" in sql or "resolved_slug" in sql or "professor_aliases" in sql:
            return []
        return [{"n": pending[0] if "professors" in sql else pending[1]}]

    usage = {"emails": {"daily": {"used": 3, "limit": 100}, "monthly": {"used": 40, "limit": 3000}}}
    monkeypatch.setattr(review_digest, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(review_digest, "fetch_all", fetch)
    monkeypatch.setattr(review_digest.notify.http_requests, "post",
                        lambda url, **kw: posts.append(kw["json"]) or SimpleNamespace(ok=True))
    monkeypatch.setattr(review_digest.notify.http_requests, "get",
                        lambda url, **kw: SimpleNamespace(ok=usage_status == 200, status_code=usage_status,
                                                          json=lambda: usage))
    if key:
        monkeypatch.setenv("RESEND_API_KEY", key)
    else:
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
    return posts


def test_main_sends_daily_to_the_ratings_inbox_with_html(monkeypatch):
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")])
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    assert payload["to"] == ["ratings@ratemyhusky.com"]
    assert payload["from"] == "RateMyHusky <feedback@ratemyhusky.com>"
    assert payload["subject"].startswith("[RateMyHusky] 1 to review, 0 new ratings")
    assert payload["text"] and payload["html"].startswith("<!DOCTYPE html>")
    assert "Resend today" in payload["html"]


def test_main_sends_even_when_nothing_is_waiting(monkeypatch):
    posts = _main(monkeypatch, [])
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    assert payload["subject"].startswith("[RateMyHusky] Nothing to review")


def test_main_dry_run_writes_html_and_prints_text(monkeypatch, capsys, tmp_path):
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")])
    monkeypatch.setattr(review_digest.tempfile, "gettempdir", lambda: str(tmp_path))
    assert review_digest.main(["--dry-run"], now=NOW) == 0
    out = capsys.readouterr().out
    assert posts == [] and out.startswith("[RateMyHusky] 1 to review") and "Needs you" in out
    path = out.rsplit("HTML preview: ", 1)[1].strip()
    assert path == str(tmp_path / "review-digest.html")
    assert open(path, encoding="utf-8").read().startswith("<!DOCTYPE html>")


def test_main_fails_without_a_resend_key(monkeypatch):
    # The workflow run turns red, so a missing secret doesn't silently stop the digest.
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")], key=None)
    assert review_digest.main([], now=NOW) == 1 and posts == []


def test_a_sending_only_key_still_sends_with_the_unavailable_row(monkeypatch):
    posts = _main(monkeypatch, [], usage_status=401)
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    note = "Resend usage unavailable: key can't read usage"
    assert payload["html"].count(escape(note)) == 1 and payload["text"].count(note) == 1


def test_no_comment_or_agent_reason_reaches_the_email():
    held = [H("a", "CS1", "near_duplicate", agent_decision="reject", comment="SECRET-COMMENT",
              agent_reason="SECRET-REASON")]
    approved = [H("b", "CS2", "no_timer", agent_decision="approve", comment="SECRET-COMMENT2",
                  agent_reason="SECRET-REASON2")]
    _, text, html = review_digest.build_digest(held, approved, 0, 0, NOW)
    assert "SECRET" not in text and "SECRET" not in html


def test_an_attack_spanning_midnight_keeps_the_command_and_span():
    rows = [{**r, "created_at": datetime(2025, 4, 11, 23, 50, tzinfo=timezone.utc) + timedelta(minutes=10 * i)}
            for i, r in enumerate(_bomb_rows()[:4])]
    _, text, _ = review_digest.build_digest(rows, [], 0, 0, NOW)
    assert "4 ratings for leena-razzaq in" in text and "all within 30 minutes" in text
    assert "reject-rating --abuse 00000000 00000001 00000002 00000003" in text


def test_attack_command_is_unchanged_by_the_session_timezone():
    eastern = timezone(timedelta(hours=-4))
    rows = [{**r, "created_at": r["created_at"].astimezone(eastern)} for r in _bomb_rows()]
    _, text, _ = review_digest.build_digest(rows, [], 0, 0, NOW)
    assert "23 ratings for leena-razzaq in" in text and "all within 62 minutes" in text
    assert "reject-rating --abuse " + " ".join(r["id"][:8] for r in rows) in text


def test_a_decision_older_than_an_edit_counts_as_not_yet_reviewed():
    reviewed, edited = NOW - timedelta(hours=5), NOW - timedelta(hours=2)
    held = [H("b", "CS2", "near_duplicate", agent_decision="escalate", agent_reviewed_at=reviewed, updated_at=edited),
            H("c", "CS3", "near_duplicate", agent_decision="escalate", agent_reviewed_at=reviewed, updated_at=reviewed)]
    _, text, html = review_digest.build_digest(held, [], 0, 0, NOW)
    assert "Reject" not in html and "--abuse" not in text
    assert "escalated: 1" in text and "pending: 1" in text and "1</b> pending</td>" in html


def test_an_edited_reject_stays_in_the_attack_command_and_a_held_approve_is_unreviewed():
    reviewed, edited = NOW - timedelta(hours=5), NOW - timedelta(hours=2)
    held = [H("a", "CS1", "burst_prof", agent_decision="reject", id="aaaa1111-0", agent_reviewed_at=reviewed,
              updated_at=edited),
            H("b", "CS2", "no_timer", agent_decision="approve", agent_reviewed_at=reviewed, updated_at=reviewed)]
    _, text, _ = review_digest.build_digest(held, [], 0, 0, NOW)
    assert "reject-rating --abuse aaaa1111" in text
    assert "pending: 1" in text
