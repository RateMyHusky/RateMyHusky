from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import review_digest

NOW = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)


def H(slug, code, reasons, hours_ago=1):
    return {"professor_slug": slug, "course_code": code, "hold_reasons": reasons,
            "created_at": NOW - timedelta(hours=hours_ago)}


def test_nothing_waiting_sends_nothing():
    assert review_digest.build_digest([], 0, 0, NOW) is None
    assert review_digest.build_digest([], 0, 0, NOW, pending_comments=0) is None


def test_waiting_comments_alone_send_a_digest():
    # An accepted rating's comment isn't a held rating, but it still waits for a reviewer.
    subject, text = review_digest.build_digest([], 0, 0, NOW, pending_comments=3)
    assert subject == "[RateMyHusky] To review: 0 held ratings, 3 comments, 0 new professors, 0 new courses"
    assert "Comments to review: 3" in text


def test_the_digest_counts_reasons_new_holds_and_pending_names():
    held = [H("jane-doe", "CS2500", "burst_prof_day"),
            H("jane-doe", "CS3500", "burst_prof_day,unverified_pair"),
            H(None, None, "no_timer"),  # a pending professor's rating
            H("bob-lee", "CS2500", "weekly_surge", hours_ago=48)]
    subject, text = review_digest.build_digest(held, 1, 2, NOW, pending_comments=1)
    assert subject == "[RateMyHusky] To review: 4 held ratings, 1 comment, 1 new professor, 2 new courses"
    assert "Held ratings: 4 (3 in the last 24 hours)" in text
    assert "  burst_prof_day: 2\n  no_timer: 1\n  unverified_pair: 1\n  weekly_surge: 1" in text
    assert "  jane-doe: 2" in text and "bob-lee" not in text.split("Most held")[1]
    assert "  CS2500: 1" in text and "  CS3500: 1" in text
    assert "python review_ratings.py list" in text


def _main(monkeypatch, held, pending=(0, 0), key="re-test", comments=0):
    posts = []

    def fetch(conn, sql):
        if "comment_status" in sql:
            return [{"n": comments}]
        if "FROM survey_ratings" in sql:
            return held
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


def test_main_sends_for_waiting_comments_alone(monkeypatch):
    posts = _main(monkeypatch, [], comments=2)
    assert review_digest.main([], now=NOW) == 0
    (payload,) = posts
    assert ", 2 comments, " in payload["subject"]


def test_main_fails_without_a_resend_key(monkeypatch):
    # The workflow run turns red, so a missing secret doesn't silently stop the digest.
    posts = _main(monkeypatch, [H("jane-doe", "CS2500", "burst_pause")], key=None)
    assert review_digest.main([], now=NOW) == 1 and posts == []
