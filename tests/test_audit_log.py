import sqlite3

from db.audit_log import append_audit_event, list_audit_events, verify_audit_chain


def test_audit_events_append_and_verify_chain(tmp_path):
    db_path = str(tmp_path / "audit.db")

    first = append_audit_event(db_path, "paper_cycle_started", {"universe": "mega_cap"}, run_id="run-1")
    second = append_audit_event(db_path, "paper_cycle_completed", {"logged_count": 1}, run_id="run-1")
    listed = list_audit_events(db_path, run_id="run-1", limit=10)
    verified = verify_audit_chain(db_path)

    assert first["ok"] is True
    assert second["ok"] is True
    assert listed["count"] == 2
    assert listed["events"][0]["event_type"] == "paper_cycle_completed"
    assert verified["ok"] is True
    assert verified["event_count"] == 2


def test_tampered_audit_event_fails_verification(tmp_path):
    db_path = str(tmp_path / "audit_tampered.db")
    event = append_audit_event(db_path, "candidate_selected", {"ticker": "AAPL"}, run_id="run-1")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE audit_events SET payload_json = ? WHERE event_id = ?",
            ('{"ticker":"MSFT"}', event["event"]["event_id"]),
        )

    verified = verify_audit_chain(db_path)

    assert verified["ok"] is False
    assert verified["errors"][0]["type"] == "event_hash_mismatch"


def test_audit_chain_preserves_previous_hash_continuity(tmp_path):
    db_path = str(tmp_path / "audit_chain.db")

    first = append_audit_event(db_path, "one", {"n": 1})
    second = append_audit_event(db_path, "two", {"n": 2})

    assert second["event"]["previous_hash"] == first["event"]["event_hash"]

