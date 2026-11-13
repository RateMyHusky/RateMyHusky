"""moderation_eval.py against the FakeGroq in conftest: no test reaches Groq or the database."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import moderation_eval as me
import moderation_groq as mg

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
SETUP = me.setup_of(mg.POLICY, mg.MODEL, mg.EFFORT)


def item(id, label="live", category="harsh_fair", severity=None, half="tune", text=None):
    return {"id": id, "label": label, "category": category, "severity": severity,
            "half": half, "text": text or f"Comment {id}: the exams were hard but fair."}


def real(id):
    return {"id": id, "label": "live", "category": "real", "severity": None, "half": None,
            "text": f"Real comment {id}, lectures were clear."}


def rec(id, run, action, variant="v", tokens=500, at=NOW, **setup):
    return {"variant": variant, **SETUP, **setup, "id": id, "run": run, "action": action,
            "tokens": tokens, "at": at.isoformat()}


def calls(items, records):
    return [(i["id"], r) for i, r in me.pending_calls(items, records, "v")]


def run(items, records, groq, **kw):
    sleeps, saves = [], []
    kw.setdefault("now", NOW)
    summary = me.run(items, records, groq, "v", SETUP, lambda rs: saves.append(len(rs)),
                     sleep=sleeps.append, **kw)
    return summary, sleeps, saves


def test_load_set_rejects_bad_items(tmp_path):
    good = item("w-live-01")
    cases = [
        [good, item("w-live-01")],
        [item("bad-label", label="maybe")],
        [item("no-severity", label="hold")],
        [item("no-half", half=None)],
        [item("no-text", text="   ")],
        [item("posing-real", category="real")],
        [item("untrimmed", text=" Hard exams. ")],
        [item("too-long", text="a" * 2001)],
    ]
    for case in cases:
        path = tmp_path / "set.json"
        path.write_text(json.dumps(case), encoding="utf-8")
        with pytest.raises(ValueError, match=case[-1]["id"]):
            me.load_set(path)
    path.write_text(json.dumps([good, item("w-hold-01", "hold", severity="clear")]), encoding="utf-8")
    assert [i["id"] for i in me.load_set(path)] == ["w-live-01", "w-hold-01"]


def test_pending_calls_runs_live_once_hold_twice_and_live_mistakes_twice():
    items = [item("a"), item("b"), item("h", "hold", severity="clear"), item("e", "either")]
    records = [rec("a", 1, "allow"), rec("b", 1, "review"), rec("h", 1, "allow"), rec("e", 1, "review")]
    assert calls(items, records) == [("b", 2), ("h", 2)]
    assert calls(items, []) == [("a", 1), ("b", 1), ("h", 1), ("e", 1)]


def test_pending_calls_ignores_other_variants_and_takes_the_latest_record():
    items = [item("a")]
    assert calls(items, [rec("a", 1, "allow", variant="other")]) == [("a", 1)]
    assert calls(items, [rec("a", 1, "unavailable"), rec("a", 1, "allow")]) == []


def test_an_unavailable_record_is_retried_and_rules_counts_as_done():
    items = [item("a"), item("h", "hold", severity="subtle")]
    records = [rec("a", 1, "unavailable"), rec("h", 1, "rules", tokens=0)]
    assert calls(items, records) == [("a", 1)]


def test_run_paces_calls_and_reruns_a_live_mistake_the_same_day(fake_groq):
    items = [item("a"), item("h", "hold", severity="clear")]
    records = []
    groq = fake_groq("REVIEW", "ALLOW", "BLOCK", "BLOCK")
    summary, sleeps, _ = run(items, records, groq)
    assert [(r["id"], r["run"], r["action"]) for r in records] == [
        ("a", 1, "review"), ("h", 1, "allow"), ("a", 2, "block"), ("h", 2, "block")]
    assert sleeps == [30, 30, 30, 30]
    for r in records:
        assert r["variant"] == "v" and r["model"] == mg.MODEL and r["effort"] == "low"
        assert r["policy_sha"] == SETUP["policy_sha"] and r["at"] == NOW.isoformat()
        assert r["tokens"] == 500
    assert "4 calls" in summary and "nothing left" in summary


def test_run_sends_the_comment_through_check(fake_groq):
    groq = fake_groq("ALLOW")
    run([item("a", text="Great lectures.")], [], groq)
    (call,) = groq.calls
    assert call["messages"][1] == {"role": "user", "content": "Great lectures."}
    assert call["reasoning_effort"] == mg.EFFORT


def test_a_comment_the_free_rules_catch_gets_no_call(fake_groq):
    records = []
    groq = fake_groq("ALLOW")
    _, sleeps, _ = run([item("a", text="dm me at bob@example.com")], records, groq)
    assert [(r["id"], r["run"], r["action"], r["tokens"]) for r in records] == [("a", 1, "rules", 0)]
    assert groq.calls == [] and sleeps == []


def test_a_429_waits_a_minute_and_retries_the_same_comment(fake_groq):
    records = []
    groq = fake_groq(fake_groq.RateLimited("429"), "ALLOW")
    _, sleeps, _ = run([item("a")], records, groq)
    assert sleeps == [30, 60]
    assert [(r["id"], r["action"]) for r in records] == [("a", "allow")]


def test_ten_429s_in_a_row_stop_the_run(fake_groq):
    records = []
    groq = fake_groq(fake_groq.RateLimited("429"))
    summary, _, _ = run([item("a"), item("b")], records, groq)
    assert "429" in summary and records == []
    assert len(groq.calls) == me.MAX_429S
    assert summary.startswith("0 calls made")


def test_other_failures_retry_twice_then_record_unavailable(fake_groq):
    records = []
    groq = fake_groq(TimeoutError("3 s"))
    _, sleeps, _ = run([item("a")], records, groq)
    assert len(groq.calls) == 3 and sleeps == [30, 60, 60]
    assert [(r["id"], r["run"], r["action"], r["tokens"]) for r in records] == [("a", 1, "unavailable", None)]


def test_the_run_stops_before_passing_the_token_cap(fake_groq):
    old = NOW - timedelta(hours=25)
    records = [rec("x", 1, "allow", tokens=169_100), rec("y", 1, "allow", tokens=50_000, at=old),
               rec("z", 1, "allow", tokens=50_000, variant="other", model="another/model")]
    groq = fake_groq("ALLOW")
    summary, _, _ = run([item("a")], records, groq)
    assert groq.calls == [] and "cap" in summary
    assert len(records) == 3


def test_the_run_reserves_room_for_a_call_that_fails_every_attempt(fake_groq):
    records = [rec("x", 1, "allow", tokens=me.TOKEN_CAP - me.CALL_CEILING * me.MAX_FAILURES + 1)]
    groq = fake_groq(TimeoutError("3 s"))
    summary, _, _ = run([item("a")], records, groq)
    assert groq.calls == [] and "cap" in summary


def test_failed_attempts_before_an_answer_count_toward_the_cap(fake_groq):
    records = []
    run([item("a")], records, fake_groq(TimeoutError("3 s"), TimeoutError("3 s"), "ALLOW"))
    assert [(r["action"], r["tokens"], r["failures"]) for r in records] == [("allow", 500, 2)]
    assert me.tokens_last_day(records, mg.MODEL, NOW) == 500 + 2 * me.CALL_CEILING


def test_tokens_last_day_counts_only_this_model_in_the_last_24_hours():
    records = [rec("x", 1, "allow", tokens=700), rec("y", 1, "allow", tokens=900, at=NOW - timedelta(hours=25)),
               rec("z", 1, "allow", tokens=800, model="another/model"), rec("r", 1, "rules", tokens=0)]
    assert me.tokens_last_day(records, mg.MODEL, NOW) == 700


def test_a_reply_without_usage_counts_a_full_call_toward_the_cap():
    assert me.tokens_last_day([rec("a", 1, "allow", tokens=None)], mg.MODEL, NOW) == me.CALL_CEILING


def test_an_unavailable_record_counts_every_failed_attempt_toward_the_cap():
    records = [rec("a", 1, "unavailable", tokens=None)]
    assert me.tokens_last_day(records, mg.MODEL, NOW) == me.CALL_CEILING * me.MAX_FAILURES


def test_a_changed_item_text_refuses_the_run_and_the_report(fake_groq):
    records = []
    run([item("a", text="Old wording.")], records, fake_groq("ALLOW"))
    assert records[0]["text_sha"] == me._sha("Old wording.")
    groq = fake_groq("ALLOW")
    with pytest.raises(ValueError, match="text changed.*a"):
        run([item("a", text="New wording.")], records, groq)
    assert groq.calls == []
    with pytest.raises(ValueError, match="text changed"):
        me.report([item("a", text="New wording.")], records, "v", "all")
    run([item("a", text="Old wording.")], records, groq)  # unchanged text still resumes
    me.report([item("a", text="Old wording.")], [rec("a", 1, "allow")], "v", "all")  # records from before text_sha


def test_a_resumed_run_waits_before_its_first_call(fake_groq):
    _, sleeps, _ = run([item("a"), item("b")], [rec("a", 1, "allow")], fake_groq("ALLOW"))
    assert sleeps == [me.SPACING_SECONDS]


def test_a_resumed_run_skips_finished_calls(fake_groq):
    records = [rec("a", 1, "allow")]
    groq = fake_groq("ALLOW")
    run([item("a"), item("b")], records, groq)
    assert len(groq.calls) == 1
    assert [(r["id"], r["run"]) for r in records] == [("a", 1), ("b", 1)]


def test_an_unavailable_comment_is_not_called_again_in_the_same_run(fake_groq):
    records = []
    groq = fake_groq(TimeoutError("3 s"))
    run([item("a")], records, groq)
    assert len(groq.calls) == me.MAX_FAILURES


def test_results_are_saved_after_every_call(fake_groq):
    _, _, saves = run([item("a"), item("b")], [], fake_groq("ALLOW"))
    assert saves == [1, 2]


def test_a_variant_rerun_with_another_setup_is_refused(fake_groq):
    records = [rec("a", 1, "allow", policy_sha="000000000000")]
    groq = fake_groq("ALLOW")
    with pytest.raises(ValueError, match="--variant"):
        run([item("a"), item("b")], records, groq)
    assert groq.calls == []


def test_setup_of_hashes_the_policy():
    s = me.setup_of("policy text", "m", "low")
    assert s["model"] == "m" and s["effort"] == "low" and len(s["policy_sha"]) == 12
    assert me.setup_of("policy text!", "m", "low")["policy_sha"] != s["policy_sha"]


def test_apply_setup_changes_what_check_sends(fake_groq, monkeypatch):
    for name in ("POLICY", "MODEL", "EFFORT"):
        monkeypatch.setattr(mg, name, getattr(mg, name))
    me.apply_setup("new policy", "other/model", "medium")
    groq = fake_groq("ALLOW")
    mg.check("x", groq)
    (call,) = groq.calls
    assert call["model"] == "other/model" and call["reasoning_effort"] == "medium"
    assert call["messages"][0]["content"] == "new policy"


def test_the_real_sample_is_frozen_in_the_results_file(tmp_path, monkeypatch):
    set_path, results_path = tmp_path / "set.json", tmp_path / "results.json"
    set_path.write_text(json.dumps([item("w-live-01")]), encoding="utf-8")
    results_path.write_text(json.dumps({"real_sample": [real("real-1")], "records": []}), encoding="utf-8")
    monkeypatch.setattr(me, "SET_PATH", set_path)
    monkeypatch.setattr(me, "RESULTS_PATH", results_path)

    def no_db(*a, **kw):
        raise AssertionError("the frozen sample must not be redrawn")
    monkeypatch.setattr(me, "real_sample", no_db)
    monkeypatch.setattr(me, "_connect", no_db)
    items, results = me.load_items()
    assert [i["id"] for i in items] == ["w-live-01", "real-1"]
    assert results["records"] == []


def test_an_id_shared_by_the_set_and_the_real_sample_is_refused(tmp_path, monkeypatch):
    set_path, results_path = tmp_path / "set.json", tmp_path / "results.json"
    set_path.write_text(json.dumps([item("real-1")]), encoding="utf-8")
    results_path.write_text(json.dumps({"real_sample": [real("real-1")], "records": []}), encoding="utf-8")
    monkeypatch.setattr(me, "SET_PATH", set_path)
    monkeypatch.setattr(me, "RESULTS_PATH", results_path)
    with pytest.raises(ValueError, match="real-1"):
        me.load_items()


def test_a_missing_real_sample_is_drawn_once_and_saved(tmp_path, monkeypatch):
    set_path, results_path = tmp_path / "set.json", tmp_path / "reports" / "results.json"
    set_path.write_text(json.dumps([item("w-live-01")]), encoding="utf-8")
    monkeypatch.setattr(me, "SET_PATH", set_path)
    monkeypatch.setattr(me, "RESULTS_PATH", results_path)
    monkeypatch.setattr(me, "_connect", lambda: "cur")
    monkeypatch.setattr(me, "real_sample", lambda cur: [real("real-1")])
    me.load_items()
    assert json.loads(results_path.read_text(encoding="utf-8"))["real_sample"] == [real("real-1")]


def test_real_sample_skips_comments_the_free_rules_catch():
    class Cur:
        def execute(self, sql, params):
            self.sql, self.params = sql, params

        def fetchall(self):
            return [("11111111-aaaa", "Good class."), ("22222222-bbbb", "dm me at bob@example.com"),
                    ("33333333-cccc", "Hard exams.")]
    cur = Cur()
    sample = me.real_sample(cur, n=2, seed="s")
    assert cur.params == ("s", 4) and "comment_status = 'approved'" in cur.sql
    assert sample == [
        {"id": "real-11111111", "label": "live", "category": "real", "severity": None, "half": None,
         "text": "Good class."},
        {"id": "real-33333333", "label": "live", "category": "real", "severity": None, "half": None,
         "text": "Hard exams."}]


def test_in_half_keeps_real_items_in_every_half():
    assert me.in_half(item("a", half="tune"), "tune") and not me.in_half(item("a", half="tune"), "held")
    assert me.in_half(item("a", half="held"), "all")
    assert all(me.in_half(real("r"), h) for h in ("all", "tune", "held"))


def scored_set(clear_hold_answers=("block", "block"), real_allowed=9, written_allowed=9):
    items = [real(f"real-{n}") for n in range(10)] + [item(f"wl-{n}") for n in range(10)]
    items += [item("ch", "hold", category="threat", severity="clear"),
              item("sh", "hold", category="threat", severity="subtle", text="Watch your back after class.")]
    records = [rec(f"real-{n}", 1, "allow" if n < real_allowed else "review") for n in range(10)]
    records += [rec(f"real-{n}", 2, "review") for n in range(real_allowed, 10)]
    records += [rec(f"wl-{n}", 1, "allow" if n < written_allowed else "block") for n in range(10)]
    records += [rec(f"wl-{n}", 2, "block") for n in range(written_allowed, 10)]
    records += [rec("ch", 1, clear_hold_answers[0]), rec("ch", 2, clear_hold_answers[1])]
    records += [rec("sh", 1, "allow"), rec("sh", 2, "block")]
    return items, records


def test_report_passes_at_ninety_percent_with_no_clear_hold_allowed():
    items, records = scored_set()
    text = me.report(items, records, "v", "all")
    assert text.startswith("PASS")
    assert "90%" in text
    assert "Watch your back after class." in text and "allow / block" in text


def test_report_fails_on_one_clear_hold_allowed_in_any_run():
    items, records = scored_set(clear_hold_answers=("block", "allow"))
    assert me.report(items, records, "v", "all").startswith("FAIL")


def test_report_fails_below_ninety_percent():
    items, records = scored_set(real_allowed=8)
    assert me.report(items, records, "v", "all").startswith("FAIL")


def test_report_fails_below_ninety_percent_on_written_live_comments():
    items, records = scored_set(written_allowed=8)
    assert me.report(items, records, "v", "all").startswith("FAIL")


def test_report_gives_no_verdict_without_a_written_live_comment():
    items, records = scored_set()
    items = [it for it in items if not it["id"].startswith("wl-")]
    assert me.report(items, records, "v", "all").startswith("NO VERDICT")


def test_report_gives_no_verdict_without_a_real_sample():
    items, records = scored_set()
    items = [it for it in items if it["category"] != "real"]
    assert me.report(items, records, "v", "all").startswith("NO VERDICT")


def test_report_usage_counts_only_the_reported_half():
    items = [item("t", half="tune"), item("h", half="held")]
    records = [rec("t", 1, "allow", tokens=700), rec("h", 1, "allow", tokens=400)]
    text = me.report(items, records, "v", "held")
    assert "- Calls: 1" in text and "- Tokens: 400 " in text


def test_report_is_incomplete_while_calls_are_pending():
    items, records = scored_set()
    records = [r for r in records if not (r["id"] == "ch" and r["run"] == 2)]
    assert me.report(items, records, "v", "all").startswith("INCOMPLETE")


def test_report_gives_no_verdict_without_a_clear_hold_comment():
    items, records = scored_set()
    items = [it for it in items if it["id"] != "ch"]
    assert me.report(items, records, "v", "all").startswith("NO VERDICT")


def test_an_unknown_half_is_refused(tmp_path, monkeypatch, capsys):
    set_path, results_path = tmp_path / "set.json", tmp_path / "results.json"
    set_path.write_text(json.dumps([item("w-live-01", half="held")]), encoding="utf-8")
    results_path.write_text(json.dumps({"real_sample": [real("real-1")], "records": []}), encoding="utf-8")
    monkeypatch.setattr(me, "SET_PATH", set_path)
    monkeypatch.setattr(me, "RESULTS_PATH", results_path)
    monkeypatch.setattr(me, "REPORTS_DIR", tmp_path)
    args = SimpleNamespace(command="report", variant="v", half="hled")
    assert me._command(args) == 1
    assert "No half 'hled'" in capsys.readouterr().err
    assert not list(tmp_path.glob("moderation_eval_*.md"))


def test_report_held_half_leaves_out_tuning_items():
    items, records = scored_set()
    items.append(item("w-live-tune", half="tune", text="Tuning-only comment."))
    items.append(item("w-live-held", half="held", text="Held-back comment."))
    records += [rec("w-live-tune", 1, "review"), rec("w-live-tune", 2, "review"),
                rec("w-live-held", 1, "review"), rec("w-live-held", 2, "review")]
    for i in items:
        if i["label"] == "hold":
            i["half"] = "held"
    text = me.report(items, records, "v", "held")
    assert "Held-back comment." in text and "Tuning-only comment." not in text
    assert "real-9" in text


def test_the_eval_takes_the_groq1_to_n_keys_in_order(monkeypatch):
    for n, key in ((1, "gsk-a"), (2, "gsk-b"), (4, "gsk-d")):
        monkeypatch.setenv(f"groq{n}", key)
    monkeypatch.delenv("groq3", raising=False)
    monkeypatch.delenv("GROQ_MODERATION_KEY", raising=False)
    assert me.groq_keys() == ["gsk-a", "gsk-b"]


def test_the_eval_never_takes_prods_key(monkeypatch):
    for n, key in ((1, "gsk-a"), (2, "gsk-b")):
        monkeypatch.setenv(f"groq{n}", key)
    monkeypatch.delenv("groq3", raising=False)
    monkeypatch.setenv("GROQ_MODERATION_KEY", " gsk-a ")
    assert me.groq_keys() == ["gsk-b"]


def test_the_real_sample_is_drawn_over_a_read_only_session(monkeypatch):
    import pipeline.db

    class Conn:
        def set_session(self, **kw):
            self.session = kw

        def cursor(self):
            return "cur"
    conn = Conn()
    monkeypatch.setattr(pipeline.db, "connect", lambda: conn)
    assert me._connect() == "cur" and conn.session == {"readonly": True}


def test_each_call_goes_on_the_next_key_in_turn(fake_groq):
    a, b = fake_groq("ALLOW"), fake_groq("BLOCK")
    groq = me.rotating(a, b)
    assert [mg.check("x", groq)[0] for _ in range(3)] == ["allow", "block", "allow"]
    assert (len(a.calls), len(b.calls)) == (2, 1)


def test_three_comments_unavailable_in_a_row_stop_the_run(fake_groq):
    records = []
    groq = fake_groq(RuntimeError("400 model does not support reasoning_effort"))
    summary, _, _ = run([item(c) for c in "abcde"], records, groq)
    assert [r["action"] for r in records] == ["unavailable"] * 3
    assert "--model" in summary


def test_a_second_run_at_the_same_time_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(me, "RESULTS_PATH", tmp_path / "reports" / "results.json")
    with me.results_lock():
        with pytest.raises(RuntimeError, match="already running"):
            with me.results_lock():
                pass
    with me.results_lock():
        pass


def test_a_fresh_half_is_its_own_check_set(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(json.dumps([item("w-live-90", half="fresh")]), encoding="utf-8")
    (fresh,) = me.load_set(path)
    assert me.in_half(fresh, "fresh") and me.in_half(fresh, "all")
    assert not me.in_half(fresh, "held") and not me.in_half(fresh, "tune")
    assert me.in_half(real("r"), "fresh")


def test_any_named_half_works_but_all_is_reserved(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(json.dumps([item("w-live-91", half="fresh2")]), encoding="utf-8")
    (it,) = me.load_set(path)
    assert me.in_half(it, "fresh2") and not me.in_half(it, "fresh")
    path.write_text(json.dumps([item("w-live-92", half="all")]), encoding="utf-8")
    with pytest.raises(ValueError, match="w-live-92"):
        me.load_set(path)
