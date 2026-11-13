import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg2

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
            "devices": 0, "new_devices": 0, "top_professors": [], "top_courses": [], "days": [(0, 0)] * 14, **kw}


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
    assert "13 days ago" in html and "1,284" in html and "412" in html
    assert "New ratings: 42\n" in text and "Live ratings, all time: 1,284" in text
    assert "Blocked at submit: 2\n" in text and "Rejected" not in text


def test_ratings_section_counts_devices_and_names_the_most_rated():
    ratings = _ratings(new=18, devices=11, new_devices=9, top_professors=[("jane-doe", 5), ("zed", 2)],
                       top_courses=[("CS2500", 4), ("MATH1341", 2)])
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, ratings=ratings, names={"jane-doe": "Jane Doe"})
    for out in (text, html):
        for label in ("Devices that rated", "New devices", "Most rated professors", "Jane Doe", "zed",
                      "Most rated courses", "CS 2500", "MATH 1341"):
            assert label in out, label
    assert "Devices that rated: 11" + chr(10) + "New devices: 9" in text and "Jane Doe: 5" in text and "CS 2500: 4" in text


def test_a_day_without_ratings_lists_no_most_rated():
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, ratings=_ratings())
    assert "Most rated" not in text and "Most rated" not in html and "Devices that rated: 0" in text


def test_failed_submissions_list_each_reason_and_stay_out_when_none():
    failures = [("captcha_failed", 9), ("unknown_course", 3), ("brand_new", 1)]
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, failures=failures)
    for out in (text, html):
        assert "Failed submissions" in out and "CAPTCHA failed" in out and "unknown course, no name given" in out
        assert "brand_new" in out
    assert "CAPTCHA failed: 9" in text and "Failed submissions: 13" in text
    assert "Failed submissions" not in review_digest.build_digest([], [], 0, 0, NOW)[1]


def test_every_failure_reason_has_its_label():
    assert set(review_digest._FAILURES) == {"invalid", "captcha_missing", "captcha_failed", "captcha_down",
                                            "unknown_professor", "unknown_course", "rule_block", "rate_limited",
                                            "error"}


def test_comment_checker_section_shows_outcomes_and_stuck_comments():
    checker = {"allow": 30, "review": 2, "block": 1, "unavailable": 4, "waiting": 6, "stuck": 3}
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, checker=checker)
    for label, n in (("Passed", 30), ("Flagged for a reviewer", 2), ("Blocked", 1), ("Check failed", 4),
                     ("Not checked yet", 6), ("Failed 3+ checks", 3)):
        assert f"{label}: {n}" in text
        assert any(label in r and f">{n}</td>" in r for r in _rows(html)), label
    assert "Comment checker" in html
    assert "Comment checker" not in review_digest.build_digest([], [], 0, 0, NOW)[1]


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


def test_meters_render():
    meters = [{"label": "Resend today", "used": 3, "limit": 100, "unit": ""},
              review_digest.groq_meter("Groq agent", 120, 38000, 6000, 1200000)]
    _, text, html = review_digest.build_digest([], [], 0, 0, NOW, meters=meters)
    assert "Resend today" in html and "3 / 100" in html and "Resend today: 3 / 100" in text
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
    meters = [{"label": "Resend today", "used": 1, "limit": 100, "unit": ""},
              {"label": "Resend month", "used": 9, "limit": 3000, "unit": ""}]
    subject, text, html = review_digest.build_digest(held, held, 1, 1, NOW, names={"a": "N" * 60}, meters=meters)
    assert not any("·" in x for x in (subject, text, html))
    labels = {review_digest.reason_label(c) for c in codes}
    assert len(labels) == 11
    reason_rows = [r for r in _rows(html) if r.count("<tr>") == 1 and any(f"<td style=\"padding:2px 0;\">{x}</td>" in r for x in labels)]
    assert len(reason_rows) == 11


def _main(monkeypatch, held, pending=(0, 0), key="re-test", comments=0, approved=(), sent_ok=True,
          record_error=None):
    posts, recorded = [], []

    def fetch(conn, sql, params=None):
        if "FROM rating_failures" in sql or "GROUP BY 1 ORDER BY n DESC" in sql:
            return []
        if "AS stuck" in sql:
            return [{"allow": 0, "review": 0, "block": 0, "unavailable": 0, "waiting": 0, "stuck": 0}]
        if "FROM email_sends" in sql:
            return [{"day": 3, "month": 40}]
        if "AS live_all" in sql:
            return [{"new": 0, "live": 0, "held": 0, "rejected": 0, "live_all": 0, "comments_all": 0,
                     "devices": 0, "new_devices": 0}]
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

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, sql, params=None):
            if record_error:
                raise record_error
            recorded.append(sql)

    monkeypatch.setattr(review_digest, "connect", lambda: SimpleNamespace(
        close=lambda: None, cursor=Cursor, commit=lambda: recorded.append("COMMIT")))
    monkeypatch.setattr(review_digest, "fetch_all", fetch)
    monkeypatch.setattr(review_digest.notify.http_requests, "post",
                        lambda url, **kw: posts.append(kw["json"]) or SimpleNamespace(ok=sent_ok, status_code=500))
    if key:
        monkeypatch.setenv("RESEND_API_KEY", key)
    else:
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
    return posts, recorded


def test_main_sends_daily_to_the_ratings_inbox_with_html(monkeypatch):
    posts, recorded = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")])
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    assert recorded == ["INSERT INTO email_sends DEFAULT VALUES", "COMMIT"]
    assert payload["to"] == ["ratings@ratemyhusky.com"]
    assert payload["from"] == "RateMyHusky <feedback@ratemyhusky.com>"
    assert payload["subject"].startswith("[RateMyHusky] 1 to review, 0 new ratings")
    assert payload["text"] and payload["html"].startswith("<!DOCTYPE html>")
    assert "Resend today: 3 / 100" in payload["text"] and "Resend month: 40 / 3,000" in payload["text"]


def test_main_sends_even_when_nothing_is_waiting(monkeypatch):
    posts, _ = _main(monkeypatch, [])
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    assert payload["subject"].startswith("[RateMyHusky] Nothing to review")


def test_main_dry_run_writes_html_and_prints_text(monkeypatch, capsys, tmp_path):
    posts, recorded = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")])
    monkeypatch.setattr(review_digest.tempfile, "gettempdir", lambda: str(tmp_path))
    assert review_digest.main(["--dry-run"], now=NOW) == 0
    out = capsys.readouterr().out
    assert posts == [] and recorded == [] and out.startswith("[RateMyHusky] 1 to review") and "Needs you" in out
    path = out.rsplit("HTML preview: ", 1)[1].strip()
    assert path == str(tmp_path / "review-digest.html")
    assert open(path, encoding="utf-8").read().startswith("<!DOCTYPE html>")


def test_main_fails_without_a_resend_key(monkeypatch):
    # The workflow run turns red, so a missing secret doesn't silently stop the digest.
    posts, recorded = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")], key=None)
    assert review_digest.main([], now=NOW) == 1 and posts == [] and recorded == []


def test_a_send_resend_refuses_is_not_counted(monkeypatch):
    posts, recorded = _main(monkeypatch, [], sent_ok=False)
    assert review_digest.main([], now=NOW) == 1 and len(posts) == 1 and recorded == []


def test_a_send_that_cannot_be_recorded_still_succeeds(monkeypatch, capsys):
    # A red run invites a rerun, which would email ratings@ a second time.
    posts, recorded = _main(monkeypatch, [], record_error=psycopg2.OperationalError("connection lost"))
    assert review_digest.main([], now=NOW) == 0 and len(posts) == 1 and recorded == []
    assert "send not recorded: OperationalError" in capsys.readouterr().out


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
