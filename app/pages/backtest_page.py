"""Would the tool have helped? Learn from July-August, replay September, score against what really happened."""
import altair as alt
import polars as pl
import streamlit as st

from app import backtest as b
from app import match, match_eval
from app.data import DUPLICATE
from app.ui import backtest_result

bt = backtest_result()
ki, cs = b.known_issue_stats(bt), b.close_stats(bt)


def metric(col, label, value, note=None, help=None):
    col.metric(label, value, note, delta_color="off", delta_arrow="off", help=help)


st.title("🧪 Backtest: would it have helped?")
st.markdown(
    f"**How the test works:** the tool learns only from **July and August** ({bt.train_size} tickets). Then we "
    f"replay **September** ({bt.test_size} tickets) as if each one were new, and compare what the tool said with "
    "what really happened. Like a mock exam: it studies two months, then answers questions it hasn't seen."
)

# ---------------------------------------------------------------- 1. duplicates
st.header("1. Does it stop duplicates before they reach engineering?")
st.caption("Problem it solves: 56 escalations came back as *'duplicate of a known issue'*, an engineering round trip "
           "for nothing.")
c1, c2, c3 = st.columns(3)
metric(c1, "Escalations the tool flagged 🟡 Known issue", ki["flagged"])
metric(c2, "Really were duplicates", f"{ki['flagged_true_duplicates']} ({ki['precision']:.0%})",
       f"by chance: {ki['base_rate']:.0%}")
metric(c3, "September duplicates caught", f"{ki['duplicates_caught']} of {ki['duplicates']}")
ex = bt.escalations.filter(pl.col("known_issue_flag") & (pl.col("actual_outcome") == DUPLICATE)).row(0, named=True)
st.markdown(f"**In simple words:** when the tool says *'known issue'*, it's right about half the time, "
            f"{ki['precision'] / ki['base_rate']:.1f}× better than guessing. So the agent links the ticket to the "
            f"open engineering ticket instead of opening a new one.  \n"
            f"**Example:** {ex['ticket_id']}, *“{ex['description']}”*. The tool said 🟡 known issue. In September "
            f"engineering really did return it as a duplicate.")

# ---------------------------------------------------------------- 2. reopens
st.header("2. Does it warn before a premature close?")
st.caption("Problem it solves: closed tickets that the client reopens, which cost a second round of work.")
c1, c2, c3 = st.columns(3)
metric(c1, "Closes the tool warned ⚠️", f"{cs['warned']} of {cs['closes']}")
metric(c2, "Warned closes that reopened", f"{cs['reopen_rate_warned']:.0%}",
       f"not warned: {cs['reopen_rate_not_warned']:.0%}")
metric(c3, "September reopens warned about", f"{cs['reopens_caught']} of {cs['reopens']}")
ex = bt.closes.filter(pl.col("warned") & pl.col("reopened")).sort("risk", descending=True).row(0, named=True)
st.markdown(f"**In simple words:** a warned ticket is "
            f"{cs['reopen_rate_warned'] / cs['reopen_rate_not_warned']:.1f}× more likely to come back. The warning "
            f"appears on only {cs['warned'] / cs['closes']:.0%} of closes, so agents don't learn to ignore it.  \n"
            f"**Example:** {ex['ticket_id']}, *“{ex['description']}”*. Predicted reopen risk {ex['risk']:.0%}, so "
            "the tool said *confirm with the client first*. The client did reopen it.")

# ---------------------------------------------------------------- 3. matching
st.header("3. Does it find the right past issue when a client words it differently?")


@st.cache_data
def matching():
    return match_eval.run(return_rows=True)


rates, rows = matching()
n_new = len(match_eval.NEW_PROBLEMS)
c1, c2 = st.columns(2)
metric(c1, "Reworded tickets matched to the right past issue",
       f"{round(rates['matched and confident'] * len(match_eval.CASES))} of {len(match_eval.CASES)}",
       f"{rates['matched and confident']:.0%}")
metric(c2, "Brand-new problems correctly called 'no close match'",
       f"{round(rates['new problems spotted as new'] * n_new)} of {n_new}",
       "so it doesn't borrow the wrong history")
st.markdown("**In simple words:** everything above depends on finding the right past tickets. A small AI model "
            "compares the *meaning* of the text (free, runs on the laptop), so *“transport never arrived, staff used "
            "their own vehicle”* finds *“Cab did not turn up, employee took own transport”* even though they share "
            "almost no words. A problem it has never seen, like *“SOS button does not alert security”*, gets "
            "*no close match* and the basic checklist instead of a wrong guess. "
            f"Matching method in use right now: **{match.method()}**.")
with st.expander(f"See all {len(rows)} test sentences"):
    st.dataframe(pl.DataFrame(rows).select("right?", "client wrote", "tool matched", "similarity"),
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------- 4. the target
st.header("4. Would it reach the 30% target?")
sim0 = b.simulate_agent(bt, 0.5, 0.5)
st.markdown(
    f"**Today:** {sim0['before_rate']:.0%} of escalations come back without a fix. **Target: 30%.**  \n"
    "The duplicate flag is measured above. The checklists (missing info, config) can't be measured from old data, "
    "because nobody used them in September. So we **simulate an agent** who follows them and catches the problem "
    "some of the time. Move the slider to see what each catch rate would give."
)
p = st.slider("How often the checklist catches a missing-info or config problem", 0, 100, 50, 10,
              format="%d%%") / 100
sim = b.simulate_agent(bt, p, p)
c1, c2, c3 = st.columns(3)
metric(c1, "🎯 Escalations returned without a fix", f"{sim['after_rate']:.0%}",
       f"today {sim['before_rate']:.0%} · target 30%")
metric(c2, "Tickets sent to engineering", f"{sim['after_sent']:.0f}", f"today {sim['before_sent']}")
metric(c3, "Real bugs still sent to engineering", f"{sim['real_bugs_sent']} of {sim['real_bugs_sent']}",
       "the checklist never blocks a bug")


@st.cache_data
def curve():
    rows = [{"catch_rate": pct / 100, "returned": b.simulate_agent(bt, pct / 100, pct / 100, runs=200)["after_rate"]}
            for pct in range(0, 101, 10)]
    return pl.DataFrame(rows), b.catch_rate_needed(bt)


cv, needed = curve()
line = alt.Chart(cv).mark_line(point=True).encode(
    x=alt.X("catch_rate:Q", title="How often the checklist catches the problem", axis=alt.Axis(format="%")),
    y=alt.Y("returned:Q", title="Escalations returned without a fix", axis=alt.Axis(format="%")),
    tooltip=[alt.Tooltip("catch_rate:Q", format=".0%"), alt.Tooltip("returned:Q", format=".0%")])
target = alt.Chart(pl.DataFrame({"y": [0.30]})).mark_rule(strokeDash=[4, 4], color="gray").encode(y="y:Q")
st.altair_chart((line + target).properties(height=240), width="stretch")
st.markdown(f"**In simple words:** if agents catch about **{needed:.0%}** of these problems with the checklist, "
            "returned escalations fall to the 30% target. That is the one number the **2-week pilot** measures "
            "(*Weekly metrics → Pilot*).")
st.caption("Why a checklist and not a prediction? We tried predicting which escalations are avoidable from history. "
           "It didn't work: the same issue can be a real bug one day and a config setting the next. So the tool "
           "asks the same short questions every time, and uses history only as evidence.")
