"""The pilot loop end to end: agent acts -> engineering/client answer -> metrics and knowledge update."""
import polars as pl

from app import pilot_metrics, store
from app.data import CONFIG, derive, load_tickets
from app.knowledge import build_knowledge


def test_pilot_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "pilot.db")
    v0 = store.version()

    # Agent escalates with a complete checklist; engineering returns it as config.
    tid = store.upsert_ticket({"client_name": "Acme", "category": "Roster / booking not syncing",
                               "description": "Booking cutoff changed but roster still uses old cutoff", "agent": "Me"})
    store.log_escalation(tid, "Me", "Escalate", False, 5, 5, 4, 4)
    store.record_eng_outcome(int(store.table("escalations")["id"][0]), CONFIG, "cutoff saved as 8 PM")
    assert store.table("tickets")["status"][0] == store.BACK_FROM_ENG

    # Agent fixes it at L1; client confirms. A second ticket is fixed at L1 without ever escalating.
    store.log_close(tid, "Me", store.FIXED_AT_L1, 0.1, False)
    store.record_client_response(int(store.table("closes")["id"][0]), reopened=False)
    t2 = store.upsert_ticket({"client_name": "Beta", "category": "Login / access issue",
                              "description": "Need access to reports module", "agent": "Me"})
    store.log_close(t2, "Me", store.FIXED_AT_L1, 0.05, False)
    assert store.version() != v0

    t = pilot_metrics.totals(pilot_metrics.weekly())
    assert t["escalations"] == 1 and t["returned_unfixed"] == 1 and t["complete_returned"] == 1
    assert t["fixed_at_l1"] == 1  # only the ticket that was never escalated counts as avoided

    # Knowledge learns from the finished pilot ticket.
    hist = store.as_history()
    assert hist.height == 1 and hist["eng_outcome"][0] == CONFIG
    kb = build_knowledge(pl.concat([load_tickets(), derive(hist)], how="diagonal_relaxed"))
    stats = kb.issues[("Roster / booking not syncing", "Booking cutoff changed but roster still uses old cutoff")]
    assert stats.escalated == 35 and stats.outcomes[CONFIG] == 8  # was 34 and 7


def test_new_category_flow(tmp_path, monkeypatch):
    """A ticket that fits no category -> 'Other' with the basic checklist -> support lead creates a category."""
    from app import precheck

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "pilot.db")
    yaml_copy = tmp_path / "checklists.yaml"
    yaml_copy.write_text(precheck.CHECKLISTS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(precheck, "CHECKLISTS_FILE", yaml_copy)
    precheck.checklists.cache_clear()
    kb = build_knowledge(load_tickets())

    other = precheck.NEW_CATEGORY
    assert precheck.category_options(kb)[-1] == other
    r = precheck.escalation_check(kb, other, "SOS button does not alert security", [], [])
    assert r.evidence_level == "none" and "No history" in r.headline
    assert r.required_info == precheck.checklists()["_default"]["required_info"]

    tid = store.upsert_ticket({"client_name": "Acme", "category": other,
                               "description": "SOS button does not alert security", "agent": "Me"})
    v = store.version()
    lists = precheck.checklists()
    lists["SOS / panic button"] = dict(lists["_default"])
    precheck.save_checklists(lists)
    store.set_category([tid], "SOS / panic button")

    assert store.version() != v  # knowledge cache refreshes
    assert store.table("tickets")["category"][0] == "SOS / panic button"
    assert "SOS / panic button" in precheck.category_options(kb)
    precheck.checklists.cache_clear()
