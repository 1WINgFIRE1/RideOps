"""Stand-in for the people the L1 agent hands tickets to. In a real rollout these answers come from
the helpdesk (engineering ticket status, client replies); in the pilot you play those roles here."""
import polars as pl
import streamlit as st

from app import store
from app.data import CONFIG, DUPLICATE, FIXED, HOWTO, INFO, NOT_REPRO

st.title("📥 Engineering & client inbox")
st.caption("In the pilot you play engineering and the client here. In production these answers come from the "
           "helpdesk automatically: the engineering ticket's resolution and the client's reply.")
if msg := st.session_state.pop("flash_inbox", None):
    st.success(msg)

tickets = store.table("tickets")
info = {r["id"]: r for r in tickets.iter_rows(named=True)} if tickets.height else {}

eng_tab, client_tab = st.tabs(["🔧 Engineering: escalations waiting", "🙋 Client: closed tickets waiting for a reply"])

with eng_tab:
    esc = store.table("escalations")
    waiting = esc.filter(pl.col("outcome").is_null()) if esc.height else esc
    if waiting.is_empty():
        st.info("Nothing escalated is waiting. Escalate a ticket from the workbench first.")
    for e in waiting.sort("at").iter_rows(named=True):
        t = info.get(e["ticket_id"], {})
        with st.container(border=True):
            st.markdown(f"**{e['ticket_id']}** · {t.get('category')} · *{t.get('description')}*")
            st.caption(f"Escalated {e['at']:%d %b %H:%M} by {e['agent']} · tool said **{e['tool_verdict']}** · "
                       f"info {e['info_ticked']}/{e['info_total']} · config checks {e['config_ticked']}/{e['config_total']}")
            c1, c2, c3 = st.columns([2, 3, 1])
            outcome = c1.selectbox("Engineering's verdict", [FIXED, INFO, CONFIG, DUPLICATE, HOWTO, NOT_REPRO],
                                   key=f"o-{e['id']}")
            note = c2.text_input("What was missing / what was wrong? (feeds the checklist editor)",
                                 key=f"n-{e['id']}",
                                 placeholder="e.g. no booking ID; cutoff was saved as 8 PM in client settings")
            if c3.button("Save", key=f"s-{e['id']}", type="primary"):
                store.record_eng_outcome(e["id"], outcome, note)
                st.session_state["flash_inbox"] = f"{e['ticket_id']}: {outcome}. It's back in the agent's queue."
                st.rerun()

with client_tab:
    cl = store.table("closes")
    waiting = cl.filter(pl.col("reopened").is_null()) if cl.height else cl
    if waiting.is_empty():
        st.info("No closed tickets are waiting for the client.")
    for c in waiting.sort("at").iter_rows(named=True):
        t = info.get(c["ticket_id"], {})
        with st.container(border=True):
            st.markdown(f"**{c['ticket_id']}** · {t.get('client_name')} · *{t.get('description')}*")
            st.caption(f"{c['how']} {c['at']:%d %b %H:%M} by {c['agent']} · predicted reopen risk "
                       f"{c['reopen_risk']:.0%}{' ⚠️ warned' if c['warned'] else ''}")
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("👍 Client confirms it's fixed", key=f"ok-{c['id']}"):
                store.record_client_response(c["id"], reopened=False)
                st.session_state["flash_inbox"] = f"{c['ticket_id']} confirmed fixed."
                st.rerun()
            if b2.button("↩️ Client reopens it", key=f"re-{c['id']}"):
                store.record_client_response(c["id"], reopened=True)
                st.session_state["flash_inbox"] = f"{c['ticket_id']} reopened. It's back in the agent's queue."
                st.rerun()

with st.expander("Full pilot log"):
    st.markdown("**Tickets**"); st.dataframe(tickets, hide_index=True, width="stretch")
    st.markdown("**Escalations**"); st.dataframe(store.table("escalations"), hide_index=True, width="stretch")
    st.markdown("**Closes**"); st.dataframe(store.table("closes"), hide_index=True, width="stretch")
    if st.button("🗑️ Reset pilot log (start over)"):
        store.reset()
        st.rerun()
