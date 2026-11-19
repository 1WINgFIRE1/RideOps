"""Cached loaders shared by the Streamlit pages.

Knowledge is rebuilt automatically whenever the pilot log changes (keyed on store.version()),
so every outcome engineering or a client records is learned from on the next page load.
"""
import polars as pl
import streamlit as st

from app import backtest, store
from app.data import derive, load_tickets
from app.knowledge import build_knowledge

PILOT_AGENT = "Me (pilot agent)"


@st.cache_resource
def tickets():
    return load_tickets()


@st.cache_resource
def _knowledge(version: int):
    pilot = store.as_history()
    if pilot.is_empty():
        history = tickets()
    else:  # a CSV ticket worked in the pilot is replaced by its pilot version
        csv = tickets().filter(~pl.col("ticket_id").is_in(pilot["ticket_id"].to_list()))
        history = pl.concat([csv, derive(pilot)], how="diagonal_relaxed")
    return build_knowledge(history), pilot.height


def knowledge():
    return _knowledge(store.version())[0]


def pilot_tickets_learned() -> int:
    return _knowledge(store.version())[1]


@st.cache_resource
def backtest_result():
    return backtest.run(tickets())


def current_agent() -> str:
    return st.session_state.get("agent", PILOT_AGENT)
