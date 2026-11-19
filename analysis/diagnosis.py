"""Reproduce every headline number in docs/DIAGNOSIS.md.

Run:  uv run python analysis/diagnosis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl  # noqa: E402

from app.data import load_tickets  # noqa: E402

pl.Config.set_tbl_rows(50).set_tbl_cols(12).set_fmt_str_lengths(60).set_tbl_width_chars(200)
df = load_tickets()
total_hours = df["hours_open"].sum()


def section(title):
    print(f"\n=== {title} ===")


section("Volume by month")
print(df.group_by("month").len().sort("month"))

section("Buckets: share of tickets and of backlog hours")
print(
    df.group_by("bucket").agg(
        tickets=pl.len(),
        pct_tickets=(pl.len() / df.height * 100).round(1),
        pct_backlog_hours=(pl.col("hours_open").sum() / total_hours * 100).round(1),
        median_hours=pl.col("hours_open").median().round(0),
        csat=pl.col("csat_score").mean().round(1),
    ).sort("tickets", descending=True)
)
avoid = df.filter(pl.col("avoidable"))
print(f"Avoidable escalations: {avoid.height} tickets, "
      f"{avoid['hours_open'].sum() / total_hours:.1%} of backlog hours")

section("Trips to engineering vs time to close")
print(df.group_by("eng_handoffs").agg(tickets=pl.len(), median_hours=pl.col("hours_open").median().round(0))
      .sort("eng_handoffs"))

section("Agents: reopen rate vs expected for their category mix")
cat_rate = df.group_by("category").agg(cat_reopen=pl.col("reopened").mean())
print(
    df.join(cat_rate, on="category").group_by("assigned_agent").agg(
        tickets=pl.len(),
        escalation_rate=pl.col("escalated").mean().round(2),
        reopen_rate=pl.col("reopened").mean().round(3),
        expected_reopen=pl.col("cat_reopen").mean().round(3),
        median_first_close_h=pl.col("first_close_h").median().round(1),
        csat=pl.col("csat_score").mean().round(2),
    ).sort("reopen_rate", descending=True)
)

section("Escalation quality by agent (share of escalations actually fixed)")
print(df.filter(pl.col("escalated")).group_by("assigned_agent").agg(
    escalations=pl.len(), fixed_share=(pl.col("eng_outcome") == "Fixed").mean().round(2)).sort("fixed_share"))

section("Top recurring real bugs")
print(df.filter(pl.col("eng_outcome") == "Fixed").group_by("description").len().sort("len", descending=True).head(10))

section("Category growth July -> September")
print(df.group_by("category").agg(
    jul=(pl.col("month") == "2026-07").sum(), sep=(pl.col("month") == "2026-09").sum()
).with_columns(delta=pl.col("sep") - pl.col("jul")).sort("delta", descending=True))

section("Median first response (hours) by priority and month")
print(df.pivot(on="month", index="priority", values="first_response_h", aggregate_function="median")
      .sort("priority").with_columns(pl.exclude("priority").round(2)))
