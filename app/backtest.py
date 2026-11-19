"""Would the tool have helped? Learn from July-August only, replay September.

Three questions, answered on September tickets the tool has never seen:
  1. Can past outcomes predict which escalations are avoidable?  (honest answer: barely)
  2. Does the known-issue match find real duplicates?            (prediction)
  3. Does the close check find tickets that later reopen?        (prediction)
Plus an impact estimate for the checklist gate, which is a process change, not a prediction.
"""
from dataclasses import dataclass
from datetime import datetime

import polars as pl

from app.data import CONFIG, DUPLICATE, FIXED, HOWTO, INFO, NOT_REPRO
from app.knowledge import build_knowledge
from app.precheck import KNOWN_ISSUE, close_check, escalation_check

SPLIT = datetime(2026, 9, 1)
SEPT_HOURS = 30 * 24
L1_MEDIAN_HOURS = 11.0  # median hours open for tickets resolved at L1 (from DIAGNOSIS.md)

GATE_TARGETS = {INFO: "Missing info", NOT_REPRO: "Missing info", CONFIG: "Config / how-to", HOWTO: "Config / how-to"}


@dataclass
class Backtest:
    escalations: pl.DataFrame   # one row per September escalation, with what the tool said
    closes: pl.DataFrame        # one row per September ticket closed at L1, with predicted reopen risk
    train_size: int
    test_size: int


def run(df: pl.DataFrame) -> Backtest:
    train = df.filter(pl.col("created_at") < SPLIT)
    test = df.filter(pl.col("created_at") >= SPLIT)
    kb = build_knowledge(train)

    esc_rows = []
    for t in test.filter(pl.col("escalated")).iter_rows(named=True):
        r = escalation_check(kb, t["category"], t["description"])
        esc_rows.append({
            "ticket_id": t["ticket_id"], "week": t["week"], "category": t["category"], "description": t["description"],
            "agent": t["assigned_agent"], "actual_outcome": t["eng_outcome"],
            "real_bug": t["eng_outcome"] == FIXED, "hours_open": t["hours_open"],
            "eng_handoffs": t["eng_handoffs"],
            "known_issue_flag": r.verdict == KNOWN_ISSUE,
            "history_avoidable_share": 1 - r.shares[FIXED],
            "gate_target": GATE_TARGETS.get(t["eng_outcome"]),
        })

    close_rows = []
    for t in test.filter(~pl.col("escalated") & pl.col("first_closed_at").is_not_null()).iter_rows(named=True):
        c = close_check(kb, t["category"], t["description"], t["assigned_agent"])
        close_rows.append({
            "ticket_id": t["ticket_id"], "week": t["week"], "category": t["category"], "description": t["description"],
            "agent": t["assigned_agent"], "risk": c.risk, "warned": c.warn, "reopened": t["reopened"],
            "hours_open": t["hours_open"],
        })
    return Backtest(pl.DataFrame(esc_rows), pl.DataFrame(close_rows), train.height, test.height)


def prediction_table(bt: Backtest) -> pl.DataFrame:
    """Question 1: group September escalations by what history predicted, compare with what happened."""
    return (
        bt.escalations.with_columns(
            order=pl.when(pl.col("history_avoidable_share") < 0.45).then(0)
            .when(pl.col("history_avoidable_share") < 0.6).then(1).otherwise(2)
        )
        .group_by("order")
        .agg(escalations=pl.len(), actually_avoidable=pl.col("real_bug").not_().mean())
        .sort("order")
        .with_columns(predicted=pl.col("order").replace_strict(
            {0: "Low (<45%)", 1: "Medium (45-60%)", 2: "High (60%+)"}, return_dtype=pl.String))
        .select("predicted", "escalations", "actually_avoidable")
    )


def known_issue_stats(bt: Backtest) -> dict:
    e = bt.escalations
    flagged = e.filter(pl.col("known_issue_flag"))
    dups = e.filter(pl.col("actual_outcome") == DUPLICATE)
    return {
        "flagged": flagged.height,
        "flagged_true_duplicates": int((flagged["actual_outcome"] == DUPLICATE).sum()),
        "flagged_real_bugs": int(flagged["real_bug"].sum()),
        "precision": (flagged["actual_outcome"] == DUPLICATE).mean() if flagged.height else 0.0,
        "base_rate": dups.height / e.height,
        "duplicates": dups.height,
        "duplicates_caught": int(dups["known_issue_flag"].sum()),
        "hours_caught": float(flagged.filter(pl.col("actual_outcome") == DUPLICATE)["hours_open"].sum()),
    }


def close_stats(bt: Backtest) -> dict:
    c = bt.closes
    w, nw = c.filter(pl.col("warned")), c.filter(~pl.col("warned"))
    return {
        "closes": c.height,
        "warned": w.height,
        "reopen_rate_warned": w["reopened"].mean() if w.height else 0.0,
        "reopen_rate_not_warned": nw["reopened"].mean() if nw.height else 0.0,
        "reopens": int(c["reopened"].sum()),
        "reopens_caught": int(w["reopened"].sum()),
    }


def gate_impact(bt: Backtest, prevented_share: float) -> dict:
    """Estimate for the checklist gate: if it prevents `prevented_share` of info/config/how-to returns,
    those tickets close at L1 in ~11h instead of bouncing. Average open tickets ~= open-hours / hours in month."""
    e = bt.escalations
    targets = e.filter(pl.col("gate_target").is_not_null())
    saved = float((targets["hours_open"] - L1_MEDIAN_HOURS).clip(lower_bound=0).sum()) * prevented_share
    ki = known_issue_stats(bt)
    saved_known = max(ki["hours_caught"] - ki["flagged_true_duplicates"] * L1_MEDIAN_HOURS, 0)
    return {
        "target_tickets": targets.height,
        "prevented_tickets": round(targets.height * prevented_share),
        "hours_saved": saved + saved_known,
        "avg_open_tickets_reduced": (saved + saved_known) / SEPT_HOURS,
        "eng_tickets_avoided": round(targets.height * prevented_share) + ki["flagged_true_duplicates"],
    }


def weekly_accuracy(bt: Backtest) -> pl.DataFrame:
    """Is the tool right? Its hit rates week by week (September = weeks it never learned from)."""
    ki = bt.escalations.group_by("week").agg(
        escalations=pl.len(),
        known_flags=pl.col("known_issue_flag").sum(),
        known_flags_correct=(pl.col("known_issue_flag") & (pl.col("actual_outcome") == DUPLICATE)).sum(),
    )
    cl = bt.closes.group_by("week").agg(
        closes=pl.len(),
        warnings=pl.col("warned").sum(),
        warnings_correct=(pl.col("warned") & pl.col("reopened")).sum(),
        reopens=pl.col("reopened").sum(),
    )
    return (
        ki.join(cl, on="week", how="full", coalesce=True).sort("week")
        .with_columns(
            known_issue_hit_rate=pl.col("known_flags_correct") / pl.col("known_flags"),
            warning_hit_rate=pl.col("warnings_correct") / pl.col("warnings"),
            reopens_caught_share=pl.col("warnings_correct") / pl.col("reopens"),
        )
    )


def simulate_agent(bt: Backtest, p_info: float, p_config: float, runs: int = 500, seed: int = 7) -> dict:
    """A simulated L1 agent replays every September escalation through the gate.

    For each ticket the agent follows the tool:
      * the tool flagged a known issue      -> agent links it instead of escalating (measured, no assumption)
      * it really was missing info / not reproducible -> checklist step 2 catches it with probability p_info
      * it really was config / how-to       -> checklist step 3 catches it with probability p_config
      * it really was a bug                 -> it still gets escalated (the checklist never blocks; at most a delay)
    Repeated `runs` times with different random draws to get a range, not one lucky number.
    """
    import random

    rng = random.Random(seed)
    rows = bt.escalations.select("actual_outcome", "known_issue_flag", "hours_open").to_dicts()
    target_probs = {INFO: p_info, NOT_REPRO: p_info, CONFIG: p_config, HOWTO: p_config}
    rates, sent, saved = [], [], []
    for _ in range(runs):
        escalated = avoidable_left = 0
        hours = 0.0
        for r in rows:
            o = r["actual_outcome"]
            if o == FIXED:
                escalated += 1              # real bug reaches engineering either way
                continue
            caught = (o == DUPLICATE and r["known_issue_flag"]) or rng.random() < target_probs.get(o, 0.0)
            if caught:
                hours += max(r["hours_open"] - L1_MEDIAN_HOURS, 0)
            else:
                escalated += 1
                avoidable_left += 1
        rates.append(avoidable_left / escalated)
        sent.append(escalated)
        saved.append(hours)
    rates.sort(); sent.sort(); saved.sort()
    lo, hi = int(runs * 0.1), int(runs * 0.9)
    n = len(rows)
    return {
        "before_rate": sum(r["actual_outcome"] != FIXED for r in rows) / n,
        "before_sent": n,
        "after_rate": sum(rates) / runs, "after_rate_range": (rates[lo], rates[hi]),
        "after_sent": sum(sent) / runs,
        "real_bugs_sent": sum(r["actual_outcome"] == FIXED for r in rows),
        "avg_open_tickets_reduced": sum(saved) / runs / SEPT_HOURS,
    }


def catch_rate_needed(bt: Backtest, target: float = 0.30) -> float:
    """Smallest checklist catch rate (same for info and config) that gets the avoidable rate to `target`."""
    for p in [i / 100 for i in range(0, 101)]:
        if simulate_agent(bt, p, p, runs=100)["after_rate"] <= target:
            return p
    return 1.0
