"""The support lead keeps the checklists sharp, using engineering's notes on returned tickets."""
import polars as pl
import streamlit as st

from app import store
from app.data import CONFIG, DUPLICATE, HOWTO, INFO, NOT_REPRO
from app.match import similar
from app.precheck import GROUP_AT, NEW_CATEGORY, checklists, save_checklists

st.title("📝 Checklist editor")
st.caption("For the support lead. When engineering returns a ticket, its note says what was missing. "
           "Turn repeated notes into checklist items so the next agent asks for it before escalating.")
if msg := st.session_state.pop("flash_cl", None):
    st.success(msg)

lists = checklists()
cats = sorted(k for k in lists if k not in ("_default", NEW_CATEGORY))

esc = store.table("escalations")
tickets = store.table("tickets")
returns = pl.DataFrame()
if esc.height and tickets.height:
    returns = (esc.filter(pl.col("outcome").is_in([INFO, CONFIG, DUPLICATE, HOWTO, NOT_REPRO]))
               .join(tickets.select(pl.col("id").alias("ticket_id"), "category", "description"), on="ticket_id"))

st.subheader("Returned tickets in the pilot, by category")
if returns.is_empty():
    st.info("No returned escalations yet. When engineering returns a ticket in the inbox, its note shows up here.")
else:
    st.dataframe(returns.group_by("category", "outcome").agg(returns=pl.len()).sort("returns", descending=True),
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------- unsorted tickets -> new category
st.subheader(f"Unsorted tickets ('{NEW_CATEGORY}')")
unsorted = tickets.filter(pl.col("category") == NEW_CATEGORY) if tickets.height else tickets
if unsorted.is_empty():
    st.info(f"None yet. When an agent picks **{NEW_CATEGORY}** for a ticket that fits no category, it shows up here.")
else:
    descs = unsorted["description"].to_list()
    # How many other unsorted tickets describe the same problem (same matching the workbench uses).
    alike = [len(similar(d, descs, GROUP_AT)) - 1 for d in descs]
    view = unsorted.select("id", "created_at", "description", "client_name", "status").with_columns(
        similar_tickets=pl.Series(alike))
    st.dataframe(view.sort("similar_tickets", descending=True), hide_index=True, width="stretch")
    st.caption("**Rule of thumb:** when 3 or more tickets describe the same problem, make it a category. "
               "It starts with the basic checklist, which you can then sharpen below.")
    with st.form("new-category"):
        picked = st.multiselect("Tickets to move into the new category", unsorted["id"].to_list(),
                                format_func=lambda i: f"{i} · {dict(zip(unsorted['id'], descs))[i]}")
        name = st.text_input("New category name", placeholder="e.g. SOS / panic button")
        if st.form_submit_button("➕ Create category", type="primary"):
            name = name.strip()
            if not name or not picked:
                st.error("Give the category a name and pick at least one ticket.")
            elif name in lists or name == NEW_CATEGORY:
                st.error(f"'{name}' already exists.")
            else:
                lists[name] = {k: list(v) for k, v in lists["_default"].items()}
                save_checklists(lists)
                store.set_category(picked, name)
                st.session_state["flash_cl"] = (f"Created '{name}' and moved {len(picked)} ticket(s) into it. "
                                                "Agents can pick it now. Sharpen its checklist below.")
                st.session_state["edit_cat"] = name
                st.rerun()

st.subheader("Edit a category's checklist")
cat = st.selectbox("Category", cats, index=cats.index(st.session_state.pop("edit_cat")) if
                   st.session_state.get("edit_cat") in cats else 0)
notes = returns.filter((pl.col("category") == cat) & pl.col("eng_note").is_not_null()) if returns.height else returns
if notes.height:
    st.markdown("**Engineering's notes for this category** (candidates for new items):")
    for n in notes.iter_rows(named=True):
        st.markdown(f"- *{n['eng_note']}* · {n['outcome']} · {n['ticket_id']}")

cur = {**lists["_default"], **lists[cat]}
with st.form(f"edit-{cat}"):
    st.caption("One item per line.")
    req = st.text_area("Info engineering needs (missing = 'Insufficient info' returns)", "\n".join(cur["required_info"]))
    cfg = st.text_area("Config checks L1 can do (missing = 'Config issue' returns)", "\n".join(cur["config_checks"]))
    cls = st.text_area("Confirm before closing (missing = reopens)", "\n".join(cur["close_checks"]))
    if st.form_submit_button("💾 Save checklist", type="primary"):
        lines = lambda t: [x.strip() for x in t.splitlines() if x.strip()]  # noqa: E731
        lists[cat] = {"required_info": lines(req), "config_checks": lines(cfg), "close_checks": lines(cls)}
        save_checklists(lists)
        st.session_state["flash_cl"] = f"Saved. Agents see the new '{cat}' checklist on their next check."
        st.rerun()
