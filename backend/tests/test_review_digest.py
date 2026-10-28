from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import review_digest
from tests.razzaq_bomb import BOMB

NOW = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)


def H(slug, code, reasons, hours_ago=1, id="00000000-0000", pending_professor_id=None, agent_decision=None, **extra):
    return {"id": id, "professor_slug": slug, "course_code": code, "hold_reasons": reasons,
            "pending_professor_id": pending_professor_id, "agent_decision": agent_decision,
            "created_at": NOW - timedelta(hours=hours_ago), **extra}


def test_nothing_waiting_sends_nothing():
    assert review_digest.build_digest([], [], 0, 0, NOW) is None


def test_the_digest_counts_reasons_new_holds_and_pending_names():
    held = [H("jane-doe", "CS2500", "burst_prof_day"),
            H("jane-doe", "CS3500", "burst_prof_day,unverified_pair"),
            H(None, None, "no_timer"),  # a pending professor's rating
            H("bob-lee", "CS2500", "weekly_surge", hours_ago=48)]
    subject, text = review_digest.build_digest(held, [], 1, 2, NOW)
    assert subject == "[RateMyHusky] To review: 4 held ratings, 1 new professor, 2 new courses"
    assert "Held ratings: 4 (3 in the last 24 hours)" in text
    assert "  burst_prof_day: 2\n  no_timer: 1\n  unverified_pair: 1\n  weekly_surge: 1" in text
    assert "  jane-doe: 2" in text and "bob-lee" not in text.split("Most held")[1]
    assert "  CS2500: 1" in text and "  CS3500: 1" in text
    assert "python review_ratings.py list" in text


def _main(monkeypatch, held, pending=(0, 0), key="re-test", approved=()):
    posts = []

    def fetch(conn, sql):
        if "FROM survey_ratings" in sql:
            return list(approved) if "agent_decision = 'approve'" in sql else held
        if "resolved_code" in sql or "resolved_slug" in sql or "professor_aliases" in sql:
            return []
        return [{"n": pending[0] if "professors" in sql else pending[1]}]

    monkeypatch.setattr(review_digest, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(review_digest, "fetch_all", fetch)
    monkeypatch.setattr(review_digest.notify.http_requests, "post",
                        lambda url, **kw: posts.append(kw["json"]) or SimpleNamespace(ok=True))
    if key:
        monkeypatch.setenv("RESEND_API_KEY", key)
    else:
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
    return posts


def test_main_sends_one_email_to_the_feedback_inbox(monkeypatch):
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")])
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    assert payload["to"] == ["feedback@ratemyhusky.com"]
    assert payload["subject"].startswith("[RateMyHusky] To review: 1 held rating")


def test_main_dry_run_and_an_empty_queue_send_nothing(monkeypatch, capsys):
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")])
    assert review_digest.main(["--dry-run"], now=NOW) == 0
    assert posts == [] and "Held ratings: 1" in capsys.readouterr().out
    posts = _main(monkeypatch, [])
    assert review_digest.main([], now=NOW) == 0 and posts == []


def test_main_fails_without_a_resend_key(monkeypatch):
    # The workflow run turns red, so a missing secret doesn't silently stop the digest.
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")], key=None)
    assert review_digest.main([], now=NOW) == 1 and posts == []


def _bomb_rows():
    start = datetime(2025, 4, 11, 1, 0, tzinfo=timezone.utc)
    return [{"id": f"{i:08x}-aaaa", "professor_slug": "leena-razzaq", "course_code": b["course"],
             "hold_reasons": "burst_prof,near_duplicate", "pending_professor_id": None,
             "agent_decision": "reject", "created_at": start + timedelta(minutes=b["minute"], seconds=i)}
            for i, b in enumerate(BOMB)]


def test_recommended_rejects_are_one_group_per_attack_with_one_command():
    rows = _bomb_rows()
    _, text = review_digest.build_digest(list(reversed(rows)), [], 0, 0, NOW)
    ids = " ".join(r["id"][:8] for r in rows)
    assert "Recommended rejections: 1 attack\n" in text
    assert ("  leena-razzaq: 23 ratings, 2025-04-11 01:00-02:01 UTC [burst_prof, near_duplicate]\n"
            f"    python review_ratings.py reject-rating --abuse {ids}") in text
    assert text.count("reject-rating") == 1


def test_agent_approvals_are_listed_for_spot_checks():
    approved = [H("jane-doe", "CS2500", "no_timer", id="abcdef12-0000", agent_decision="approve"),
                H("bob-lee", "CS3500", "too_fast,stale", id="12345678-0000", agent_decision="approve")]
    _, text = review_digest.build_digest([], approved, 0, 0, NOW)
    assert "Agent approved in the last 24 hours: 2" in text
    assert "  abcdef12 jane-doe CS2500 [no_timer]" in text
    assert "  12345678 bob-lee CS3500 [too_fast, stale]" in text


def test_escalations_and_unreviewed_are_counted():
    held = [H("a", "CS1", "near_duplicate", agent_decision="escalate") for _ in range(3)]
    held.append(H("b", "CS2", "no_timer"))
    _, text = review_digest.build_digest(held, [], 0, 0, NOW)
    assert "Escalated without a recommendation: 3" in text
    assert "Not yet reviewed by the agent: 1" in text
    assert "Recommended rejections" not in text


def test_approvals_alone_still_send():
    approved = [H("jane-doe", "CS2500", "no_timer", agent_decision="approve")]
    assert review_digest.build_digest([], approved, 0, 0, NOW) is not None
    assert review_digest.build_digest([], [], 0, 0, NOW) is None


def test_no_comment_or_agent_reason_reaches_the_email():
    held = [H("a", "CS1", "near_duplicate", agent_decision="reject", comment="SECRET-COMMENT",
              agent_reason="SECRET-REASON")]
    approved = [H("b", "CS2", "no_timer", agent_decision="approve", comment="SECRET-COMMENT2",
                  agent_reason="SECRET-REASON2")]
    _, text = review_digest.build_digest(held, approved, 0, 0, NOW)
    assert "SECRET" not in text


def test_an_attack_spanning_midnight_prints_the_end_date():
    rows = [{**r, "created_at": datetime(2025, 4, 11, 23, 50, tzinfo=timezone.utc) + timedelta(minutes=10 * i)}
            for i, r in enumerate(_bomb_rows()[:4])]
    _, text = review_digest.build_digest(rows, [], 0, 0, NOW)
    assert "4 ratings, 2025-04-11 23:50-2025-04-12 00:20 UTC [" in text


def test_a_decision_older_than_an_edit_counts_as_not_yet_reviewed():
    reviewed, edited = NOW - timedelta(hours=5), NOW - timedelta(hours=2)
    held = [H("b", "CS2", "near_duplicate", agent_decision="escalate", agent_reviewed_at=reviewed, updated_at=edited),
            H("c", "CS3", "near_duplicate", agent_decision="escalate", agent_reviewed_at=reviewed, updated_at=reviewed)]
    _, text = review_digest.build_digest(held, [], 0, 0, NOW)
    assert "Recommended rejections" not in text and "--abuse" not in text
    assert "Escalated without a recommendation: 1" in text
    assert "Not yet reviewed by the agent: 1" in text


def test_an_edited_reject_stays_in_the_attack_command_and_a_held_approve_is_unreviewed():
    reviewed, edited = NOW - timedelta(hours=5), NOW - timedelta(hours=2)
    held = [H("a", "CS1", "burst_prof", agent_decision="reject", id="aaaa1111-0", agent_reviewed_at=reviewed,
              updated_at=edited),
            H("b", "CS2", "no_timer", agent_decision="approve", agent_reviewed_at=reviewed, updated_at=reviewed)]
    _, text = review_digest.build_digest(held, [], 0, 0, NOW)
    assert "reject-rating --abuse aaaa1111" in text
    assert "Not yet reviewed by the agent: 1" in text


def test_attack_times_are_printed_in_utc_whatever_the_session_timezone():
    eastern = timezone(timedelta(hours=-4))
    rows = [{**r, "created_at": r["created_at"].astimezone(eastern)} for r in _bomb_rows()]
    _, text = review_digest.build_digest(rows, [], 0, 0, NOW)
    assert "  leena-razzaq: 23 ratings, 2025-04-11 01:00-02:01 UTC" in text


def test_agent_course_merges_are_listed():
    merges = [{"code": "BIO2299", "resolved_code": "BIOL2299", "n": 2},
              {"code": "ACC1201", "resolved_code": "ACCT1201", "n": 1}]
    subject, text = review_digest.build_digest([], [], 0, 0, NOW, merges)
    assert "Agent course merges in the last 24 hours: 2" in text
    assert "  BIO2299 -> BIOL2299 (2 ratings)" in text
    assert "  ACC1201 -> ACCT1201 (1 rating)" in text
    assert review_digest.build_digest([], [], 0, 0, NOW) is None


def test_agent_professor_merges_are_listed_without_comment_text():
    merges = [{"name": "Herc Tsekourakis", "resolved_slug": "iraklis-tsekourakis", "n": 1}]
    subject, text = review_digest.build_digest([], [], 0, 0, NOW, professor_merges=merges)
    assert "Agent professor merges in the last 24 hours: 1" in text
    assert "  Herc Tsekourakis -> iraklis-tsekourakis (1 rating)" in text
    assert "professor merges" not in review_digest.build_digest([], [], 1, 0, NOW)[1]


def test_pending_nickname_suggestions_are_listed_and_alone_enough():
    aliases = [{"id": 12, "alias_key": "herc", "slug": "iraklis-tsekourakis", "source": "comment"}]
    subject, text = review_digest.build_digest([], [], 0, 0, NOW, aliases=aliases)
    assert "Nickname suggestions: 1" in text
    assert "  #12 herc -> iraklis-tsekourakis (comment)" in text
    assert "Approve with: python review_ratings.py approve-alias ID" in text
    assert "Nickname suggestions" not in review_digest.build_digest([], [], 1, 0, NOW)[1]
