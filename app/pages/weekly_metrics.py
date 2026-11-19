"""How we know it's working: the same few numbers, checked every Monday."""
import polars as pl
import streamlit as st

from app import pilot_metrics as pm
from app.baseline_view import render as render_baseline

st.title("📈 Weekly metrics")
st.markdown(
    "**Success = fewer escalations bouncing back from engineering, without more reopens.** "
    "Check these every Monday. The *Before* tab is July–September without the tool. The *Pilot* tab is live, "
    "from every action logged in the workbench."
)
pilot_tab, base_tab = st.tabs(["🟢 Pilot (live)", "📊 Before the tool (Jul–Sep)"])


def pct(a, b):
    return f"{a / b:.0%}" if b else "–"


def metric(col, label, value, note, help=None):
    col.metric(label, value, note, delta_color="off", delta_arrow="off", help=help)


with pilot_tab:
    w = pm.weekly()
    t = pm.totals(w)
    if not t:
        st.info("No pilot activity yet. Work some tickets in the **Agent workbench**, then answer as engineering "
                "and the client in the **inbox**. This tab fills in as you go.")
    else:
        st.subheader("1. Is the problem shrinking?")
        c1, c2, c3 = st.columns(3)
        metric(c1, "🎯 Escalations returned without a fix", pct(t["returned_unfixed"], t["decided"]),
               f"before: 57% · target: 30% · {t['decided']} answered by engineering",
               "Main measure. Of escalations engineering has answered, the share sent back as missing info, "
               "config, duplicate, how-to or not reproducible.")
        metric(c2, "Escalations avoided", t["fixed_at_l1"] + t["linked_known"],
               f"{t['fixed_at_l1']} fixed at L1 · {t['linked_known']} linked to a known issue",
               "Tickets that never went to engineering because the tool showed a fix or a known issue.")
        metric(c3, "🛡️ Reopen rate", pct(t["reopened"], t["answered"]),
               f"before: 10.5% · must not rise · {t['answered']} clients answered",
               "Safety check: we must not cut escalations by closing tickets that weren't really fixed.")
        st.markdown(
            "**Example:** 10 escalations answered, 3 sent back as *config issue* → **30%**, on target. "
            "Before the tool, 57 of every 100 came back."
        )

        st.subheader("2. Is the tool giving good advice?")
        c1, c2 = st.columns(2)
        metric(c1, "Full checklist ticked, still sent back", pct(t["complete_returned"], t["complete_decided"]),
               f"{t['complete_returned']} of {t['complete_decided']} · want far below 57%",
               "The direct test of the checklist. If agents tick every box and engineering still returns the "
               "ticket, the checklist is asking the wrong questions. Fix it in the Checklist editor.")
        metric(c2, "'Fixed at L1' that stayed fixed", pct(t["fixed_at_l1_held"], t["fixed_at_l1_answered"]),
               f"{t['fixed_at_l1_held']} of {t['fixed_at_l1_answered']} · want 90%+",
               "When the tool said 'try fixing at L1' and the agent did, did the client confirm it worked?")
        st.markdown(
            "**Example:** an agent ticks all 5 roster boxes and escalates. Engineering says *config issue*. That counts "
            "against the checklist, so the support lead reads engineering's note and adds the missing check."
        )

        st.subheader("Week by week")
        view = w.select(
            pl.col("week").dt.strftime("%d %b").alias("Week of"),
            pl.col("escalations").alias("Escalated"),
            pl.when(pl.col("decided") > 0).then((pl.col("returned_unfixed") / pl.col("decided") * 100).round(0))
            .alias("Returned without a fix %"),
            (pl.col("fixed_at_l1") + pl.col("linked_known")).alias("Avoided"),
            pl.when(pl.col("answered") > 0).then((pl.col("reopened") / pl.col("answered") * 100).round(0))
            .alias("Reopen %"),
        )
        st.dataframe(view, hide_index=True, width="stretch")

with base_tab:
    render_baseline()
