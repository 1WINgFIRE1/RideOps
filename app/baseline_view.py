"""'Before the tool' tab of the weekly metrics page: July-September from the CSV."""
from datetime import timedelta

import altair as alt
import polars as pl
import streamlit as st

from app.data import DATA_PULL
from app.ui import tickets


def render():
    df = tickets()
    st.markdown(
        "**The before picture.** The tool didn't exist yet, so this shows the problem it has to fix. "
        "These same lines keep going after launch, and should move toward the dashed targets."
    )

    pull = pl.select(DATA_PULL).item()
    weeks = df.select(pl.col("week").unique().sort())["week"].to_list()

    def open_at(t):
        return df.filter((pl.col("created_at") < t)
                         & (pl.col("final_closed_at").is_null() | (pl.col("final_closed_at") >= t))).height

    esc = df.filter(pl.col("escalated"))
    weekly = (
        df.group_by("week").agg(reopen_rate=pl.col("reopened").mean())
        .join(esc.group_by("week").agg(returned=pl.col("avoidable").mean()), on="week")
        .sort("week")
        .with_columns(open_tickets=pl.Series([open_at(min(w + timedelta(days=7), pull)) for w in weeks]))
        .filter(pl.col("week") + timedelta(days=7) <= pull)  # full weeks only (the last one is 28-30 Sep)
    )
    first, last = weekly.row(0, named=True), weekly.row(-1, named=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("🎯 Escalations returned without a fix", f"{esc['avoidable'].mean():.0%}",
              f"all Jul–Sep · target 30%", delta_color="off", delta_arrow="off")
    c2.metric("Open tickets at week end", last["open_tickets"], f"was {first['open_tickets']} in early July",
              delta_color="off", delta_arrow="off")
    c3.metric("🛡️ Reopen rate", f"{df['reopened'].mean():.1%}", "all Jul–Sep · must not rise",
              delta_color="off", delta_arrow="off")
    st.markdown(
        f"**In simple words:** of every 100 tickets sent to engineering, about 57 came back without a fix "
        f"(missing info, config, duplicate…). Each bounce adds days, so open tickets piled up from "
        f"{first['open_tickets']} to {last['open_tickets']}. The tool attacks the 57. The reopen rate is the "
        "safety check that we don't 'fix' it by closing tickets too early."
    )

    def line(col, title, fmt, rule=None):
        ch = alt.Chart(weekly).mark_line(point=True).encode(
            x=alt.X("week:T", title=None), y=alt.Y(f"{col}:Q", title=None, axis=alt.Axis(format=fmt)),
            tooltip=[alt.Tooltip("week:T", title="Week of"), alt.Tooltip(f"{col}:Q", format=fmt)])
        if rule is not None:
            ch = ch + alt.Chart(pl.DataFrame({"y": [rule]})).mark_rule(strokeDash=[4, 4], color="gray").encode(y="y:Q")
        return ch.properties(title=title, height=230)

    l, r = st.columns(2)
    l.altair_chart(line("returned", "Escalations returned without a fix (target 30%)", ".0%", 0.30), width="stretch")
    r.altair_chart(line("open_tickets", "Open tickets at week end", "d"), width="stretch")
    st.altair_chart(line("reopen_rate", "Reopen rate (safety check)", ".0%"), width="stretch")
    st.caption("Whether the tool's own warnings are right is on the **Backtest** page (tested on September).")
