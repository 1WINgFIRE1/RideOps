import pytest

from app.backtest import close_stats, known_issue_stats, run
from app.data import load_tickets
from app.knowledge import build_knowledge
from app.precheck import (CHECK_CONFIG, ESCALATE, KNOWN_ISSUE, MISSING_INFO, checklist,
                          close_check, escalation_check)

ROSTER = "Roster / booking not syncing"
CUTOFF = "We changed the booking cutoff to 6 PM but tomorrow's roster still uses 8 PM"


@pytest.fixture(scope="module")
def df():
    return load_tickets()


@pytest.fixture(scope="module")
def kb(df):
    return build_knowledge(df)


def test_data_loads_with_expected_shape(df):
    assert df.height == 1444
    assert int(df["escalated"].sum()) == 486
    assert int(df["is_open"].sum()) == 48


def test_free_text_matches_past_issue(kb):
    r = escalation_check(kb, ROSTER, CUTOFF)
    assert r.matched_description == "Booking cutoff changed but roster still uses old cutoff"
    assert r.evidence.escalated == 34 and r.evidence.outcomes["Fixed"] == 14


def test_gate_order_missing_info_then_config_then_escalate(kb):
    lists = checklist(ROSTER)
    assert escalation_check(kb, ROSTER, CUTOFF, info_provided=[], config_checked=[]).verdict == MISSING_INFO
    r = escalation_check(kb, ROSTER, CUTOFF, info_provided=lists["required_info"], config_checked=[])
    assert r.verdict == CHECK_CONFIG
    r = escalation_check(kb, ROSTER, CUTOFF, info_provided=lists["required_info"],
                         config_checked=lists["config_checks"])
    assert r.verdict == ESCALATE


def test_known_issue_flag(kb):
    r = escalation_check(kb, "Report export failing", "scheduled report email not received")
    assert r.verdict == KNOWN_ISSUE and r.known_issue["last_eng_ticket"].startswith("ENG-")


def test_unknown_text_falls_back_to_category(kb):
    r = escalation_check(kb, ROSTER, "zzzz qqqq")
    assert r.matched_description is None and r.evidence_level == "category"


def test_close_check_flags_high_reopen_agent(kb):
    karan = close_check(kb, "Live tracking / GPS incorrect", "ETA showing wrong", "Karan B")
    vikram = close_check(kb, "Live tracking / GPS incorrect", "ETA showing wrong", "Vikram S")
    assert karan.warn and karan.risk > vikram.risk


def test_backtest_close_check_beats_base_rate(df):
    bt = run(df)
    cs = close_stats(bt)
    assert cs["reopen_rate_warned"] > 2 * cs["reopen_rate_not_warned"]
    ki = known_issue_stats(bt)
    assert ki["precision"] > 2 * ki["base_rate"]


def test_simulated_agent_never_blocks_real_bugs_and_improves_with_catch_rate(df):
    from app.backtest import simulate_agent
    bt = run(df)
    none, half, full = (simulate_agent(bt, p, p, runs=50) for p in (0.0, 0.5, 1.0))
    assert none["after_rate"] > half["after_rate"] > full["after_rate"]
    assert full["after_sent"] >= full["real_bugs_sent"]  # every real bug still reaches engineering


def test_usually_solved_at_l1():
    """An issue L1 keeps fixing on its own is flagged as 'usually solved at L1'."""
    import polars as pl
    from app.data import load_tickets
    from app.knowledge import build_knowledge
    from app.precheck import escalation_check

    df = load_tickets()
    l1 = (df.filter(~pl.col("escalated") & ~pl.col("reopened") & ~pl.col("is_open"))
          .group_by("category", "description").len().sort("len", descending=True).row(0, named=True))
    kb = build_knowledge(df)
    r = escalation_check(kb, l1["category"], l1["description"], [], [])
    assert r.issue_stats.l1_fixed == l1["len"] and r.usually_l1


def test_different_wordings_share_history():
    """'ads in the app' and 'Ads showing in app' are one problem: their history is added together."""
    import polars as pl
    from app.data import load_tickets
    from app.knowledge import build_knowledge
    from app.precheck import escalation_check

    base = load_tickets()
    row = base.filter(~pl.col("escalated") & ~pl.col("reopened") & ~pl.col("is_open")).head(1)
    words = ["Ads showing in app", "ads showing in my rideops app", "ads in the app, how to close it?"]
    extra = pl.concat([row.with_columns(ticket_id=pl.lit(f"T{i}"), category=pl.lit("Ads"), description=pl.lit(w))
                       for i, w in enumerate(words)])
    kb = build_knowledge(pl.concat([base, extra]))
    r = escalation_check(kb, "Ads", "ads in the app", [], [])
    assert r.issue_stats.tickets == 3 and r.usually_l1
