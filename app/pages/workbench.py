import altair as alt
import polars as pl
import streamlit as st

from app import store
from app.data import FIXED
from app.knowledge import OUTCOMES
from app.llm import draft_message, llm_available
from app.precheck import (ESCALATE, KNOWN_ISSUE, MISSING_INFO, NEW_CATEGORY, TRY_L1, category_options, checklist, close_check,
                          escalation_check)
from app.match import similar
from app.precheck import GROUP_AT
from app.ui import current_agent, knowledge, tickets

df, kb = tickets(), knowledge()
me = current_agent()

st.title("🧰 Agent workbench")
st.caption("Run this before you escalate a ticket to engineering, or before you close it. "
           "Every action you take here is saved to the pilot log.")
if msg := st.session_state.pop("flash", None):
    st.success(msg)

# ---------------------------------------------------------------- pick a ticket
queue = store.table("tickets")
my_queue = queue.filter(pl.col("status").is_in(store.OPEN_FOR_L1)) if queue.height else queue
mode = st.segmented_control("Ticket", [f"My pilot queue ({my_queue.height})", "Open tickets from the CSV", "New ticket"],
                            default="New ticket" if my_queue.is_empty() else f"My pilot queue ({my_queue.height})")
categories = category_options(kb)
priority, source, eng_back = "P3", "new", None

if mode == "New ticket":
    c1, c2, c3 = st.columns([2, 1, 1])
    description = c1.text_input("What did the client report?",
                                "We changed the booking cutoff to 6 PM but tomorrow's roster still uses 8 PM")
    category = c2.selectbox("Category", categories, index=categories.index("Roster / booking not syncing"),
                            help=f"Nothing fits? Pick '{NEW_CATEGORY}'. The support lead turns repeated ones into a "
                                 "new category.")
    client_name = c3.text_input("Client", "Harbor Health")
    ticket_id = None
elif mode.startswith("My pilot queue"):
    if my_queue.is_empty():
        st.info("Your queue is empty. Start with a **New ticket** or pick an **open ticket from the CSV**.")
        st.stop()
    labels = {f"{r['id']} · {r['status']} · {r['description']} ({r['client_name']})": r
              for r in my_queue.sort("created_at").iter_rows(named=True)}
    t = labels[st.selectbox("Tickets waiting for you", list(labels))]
    ticket_id, description, category, client_name, priority, source = (
        t["id"], t["description"], t["category"], t["client_name"], t["priority"], t["source"])
    esc = store.table("escalations")
    if esc.height:
        last = esc.filter(pl.col("ticket_id") == ticket_id).sort("at")
        if last.height and last["outcome"][-1]:
            eng_back = last.row(-1, named=True)
    if t["status"] == store.BACK_FROM_ENG and eng_back:
        note = f" Engineering's note: *{eng_back['eng_note']}*" if eng_back["eng_note"] else ""
        (st.success if eng_back["outcome"] == FIXED else st.warning)(
            f"**Back from engineering:** {eng_back['outcome']}.{note} "
            + ("Close it below (✅ Before closing)." if eng_back["outcome"] == FIXED else
               "Fix it at L1, or complete the checklist and escalate again."))
    if t["status"] == store.REOPENED:
        st.error("**The client reopened this ticket.** Check what is still wrong before closing again.")
else:
    open_t = df.filter(pl.col("is_open")).sort("created_at")
    labels = {f"{r['ticket_id']} · {r['description']} ({r['client_name']})": r for r in open_t.iter_rows(named=True)}
    t = labels[st.selectbox(f"{open_t.height} tickets open on 30 Sep", list(labels))]
    description, category, client_name, ticket_id, priority, source = (
        t["description"], t["category"], t["client_name"], t["ticket_id"], t["priority"], "csv")
    st.caption(f"**{category}** · {t['priority']} · {t['client_tier']} · {t['channel']} · owner {t['assigned_agent']} · "
               f"status *{t['status']}* · trips to engineering so far: {t['eng_handoffs']}")

key = ticket_id or "new"
if category == NEW_CATEGORY:
    st.info("**New kind of ticket.** The tool has no history for it, so it shows the basic checklist. "
            "It goes to the support lead's *Unsorted tickets* list, and once the same problem shows up a few times "
            "they create a proper category for it.")
elif category not in kb.categories:  # created in the checklist editor, nothing finished yet
    st.info(f"**{category}** is a new category with no finished tickets yet, so it shows its checklist without history.")


def ensure_ticket() -> str:
    """Create the pilot ticket the first time an action is taken on it."""
    return store.upsert_ticket({"id": ticket_id, "client_name": client_name, "category": category,
                                "description": description, "priority": priority, "agent": me, "source": source})


def done(message: str):
    st.session_state["flash"] = message
    st.rerun()


esc_tab, close_tab = st.tabs(["🚀 Before escalating", "✅ Before closing"])

# ---------------------------------------------------------------- escalation check
with esc_tab:
    lists = checklist(category)
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("**1. Info engineering needs**")
        info = [i for i in lists["required_info"] if st.checkbox(i, key=f"info-{key}-{i}")]
        st.markdown("**2. Config checks you can do yourself**")
        cfg = [c for c in lists["config_checks"] if st.checkbox(c, key=f"cfg-{key}-{c}")]

    r = escalation_check(kb, category, description, info_provided=info, config_checked=cfg)

    with right:
        box = {ESCALATE: st.success, KNOWN_ISSUE: st.warning, MISSING_INFO: st.error, TRY_L1: st.info}.get(
            r.verdict, st.warning)
        box(f"### {r.icon} {r.verdict}\n{r.headline}")
        if r.evidence_level == "none":
            pass
        elif r.matched_description:
            n_alike = r.issue_stats.tickets if r.issue_stats else 0
            st.caption(f"Matched past issue: *{r.matched_description}* (similarity {r.match_score:.0f}%). "
                       f"History covers {n_alike} past ticket(s) worded like this.")
        else:
            st.caption("No close match in past tickets, so this uses the whole category's history.")

        alike = ([d for d, _ in similar(description, kb.descriptions(category), GROUP_AT)] or [r.matched_description]
                 if r.matched_description else [])
        if r.verdict == TRY_L1:
            esc_all, tk_all = store.table("escalations"), store.table("tickets")
            if esc_all.height:
                notes = (esc_all.filter(pl.col("eng_note").is_not_null() & (pl.col("eng_note") != ""))
                         .join(tk_all.select(pl.col("id").alias("ticket_id"), "category", "description"), on="ticket_id")
                         .filter(pl.col("category") == category).sort("at"))
                if notes.height:
                    st.caption(f"💡 Engineering's last note for this category: *{notes['eng_note'][-1]}*")

        if r.known_issue:
            k = r.known_issue
            st.info(f"**Known issue:** fixed {k['times_fixed']}× and flagged duplicate {k['times_duplicate']}× before. "
                    f"Last engineering ticket **{k['last_eng_ticket']}** ({k['last_seen']:%d %b}). "
                    "Link this ticket to it and tell the client a fix is in progress. "
                    "If it is clearly a different problem, carry on with the checklist.")

        if r.missing_info:
            if st.button("✉️ Draft message asking the client for the missing info"):
                msg, source = draft_message(client_name, description, r.missing_info)
                st.text_area(f"Draft ({source})", msg, height=220)
            if not llm_available():
                st.caption("Drafts use a template. Set ANTHROPIC_API_KEY to have Claude write them.")

        if r.verdict == ESCALATE:
            note = (f"Ticket: {ticket_id or '(new)'}\nIssue: {description}\nCategory: {category}\n\n"
                    "Info collected:\n" + "\n".join(f"- {i}: <fill in>" for i in info) +
                    "\n\nConfig checks done (all OK):\n" + "\n".join(f"- {c}" for c in cfg) +
                    f"\n\nSimilar past issue: {r.matched_description or 'none'}")
            st.text_area("Pre-filled escalation note", note, height=260)

        st.markdown("**What did you do?**")
        a1, a2, a3 = st.columns(3)
        lists_now = checklist(category)
        if a1.button("🚀 Escalate to engineering", type="primary" if r.verdict == ESCALATE else "secondary",
                     key=f"esc-{key}", help="Allowed at any time. The log records whether the checklist was complete."):
            tid = ensure_ticket()
            store.log_escalation(tid, me, r.verdict, r.known_issue is not None, len(info), len(lists_now["required_info"]),
                                 len(cfg), len(lists_now["config_checks"]))
            done(f"{tid} escalated to engineering. It now waits in the Engineering & client inbox.")
        if a2.button("🛠️ I fixed it at L1", key=f"fix-{key}", help="Config change or how-to answer. No escalation."):
            tid = ensure_ticket()
            cc = close_check(kb, category, description, me)
            store.log_close(tid, me, store.FIXED_AT_L1, cc.risk, cc.warn)
            done(f"{tid} fixed at L1 and closed. The client's answer goes in the inbox.")
        if r.known_issue and a3.button("🔗 Linked to known issue", key=f"link-{key}"):
            tid = ensure_ticket()
            cc = close_check(kb, category, description, me)
            store.log_close(tid, me, store.LINKED_KNOWN, cc.risk, cc.warn)
            done(f"{tid} linked to {r.known_issue['last_eng_ticket']} and closed.")

    st.divider()
    if r.evidence_level != "none":
        seen = r.issue_stats or kb.categories[category]
        scope = (f"{seen.tickets} past tickets worded like this" if r.issue_stats
                 else f"all {seen.tickets} past tickets in this category (no close match)")
        st.markdown(f"**Why: how {scope} ended**")
        L1, BUG, BACK, OTHER = "Solved at L1", "Real bug", "Came back without a fix", "Reopened or still open"
        rows = [("Solved at L1, stayed closed", seen.l1_fixed, L1)]
        rows += [(f"Escalated → {o}", seen.outcomes.get(o, 0), BUG if o == FIXED else BACK) for o in OUTCOMES]
        rows.append(("Reopened or still open", max(seen.tickets - seen.l1_fixed - seen.escalated, 0), OTHER))
        ev = pl.DataFrame(rows, schema=["ended", "tickets", "group"], orient="row")
        chart = alt.Chart(ev).mark_bar().encode(
            x=alt.X("tickets:Q", title="Past tickets", axis=alt.Axis(format="d", tickMinStep=1)),
            y=alt.Y("ended:N", sort=[r_[0] for r_ in rows], title=None, axis=alt.Axis(labelLimit=320)),
            color=alt.Color("group:N", title=None, scale=alt.Scale(domain=[L1, BUG, BACK, OTHER],
                                                                    range=["#1e88e5", "#2e7d32", "#ef6c00", "#9e9e9e"])),
            tooltip=["ended", "tickets"],
        ).properties(height=260)
        st.altair_chart(chart, width="stretch")

        if alike:
            past = (kb.history.filter((pl.col("category") == category) & pl.col("description").is_in(alike))
                    .sort("created_at", descending=True)
                    .select("ticket_id", "created_at", "description", "client_name", "escalated", "eng_outcome",
                            "reopened", pl.col("hours_open").round(0).alias("hours_open"))
                    .head(10))
            with st.expander(f"The similar past tickets ({past.height} most recent)"):
                st.dataframe(past, hide_index=True, width="stretch")

# ---------------------------------------------------------------- close check
with close_tab:
    c = close_check(kb, category, description, me)
    (st.error if c.warn else st.success)(f"### {'⚠️' if c.warn else '👍'} {c.headline}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Predicted reopen risk", f"{c.risk:.0%}")
    m2.metric("Reopen rate for this issue", f"{c.issue_rate:.0%}",
              help=f"{c.evidence.reopened} of {c.evidence.tickets} similar past tickets reopened (smoothed)")
    m3.metric(f"{me}'s reopen factor", f"{c.agent_factor:.1f}×",
              help="Actual reopens vs what this agent's ticket mix would predict. 1.0× is normal.")
    st.markdown("**Before you close, confirm:**")
    for item in c.checks:
        st.checkbox(item, key=f"close-{key}-{item}")
    if c.agent_factor > 1.5:
        st.caption("Your tickets reopen more often than expected for their mix. Confirming with the client before "
                   "closing is the quickest fix.")
    if st.button("✅ Close ticket", type="primary", key=f"close-btn-{key}"):
        tid = ensure_ticket()
        store.log_close(tid, me, store.CLOSED_NORMAL, c.risk, c.warn)
        done(f"{tid} closed ({c.risk:.0%} predicted reopen risk). The client's answer goes in the inbox.")
