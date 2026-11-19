"""Streamlit entry point:  uv run streamlit run app/main.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `import app.*` works under streamlit

import streamlit as st  # noqa: E402

from app.ui import PILOT_AGENT, pilot_tickets_learned, tickets  # noqa: E402

st.set_page_config(page_title="RideOps L1 Pre-Check", page_icon="🚦", layout="wide")

nav = st.navigation({
    "L1 agent": [
        st.Page("pages/workbench.py", title="Agent workbench", icon="🧰", default=True),
    ],
    "Pilot: other people's side": [
        st.Page("pages/inbox.py", title="Engineering & client inbox", icon="📥"),
        st.Page("pages/checklist_editor.py", title="Checklist editor (support lead)", icon="📝"),
    ],
    "Measure": [
        st.Page("pages/weekly_metrics.py", title="Weekly metrics", icon="📈"),
        st.Page("pages/backtest_page.py", title="Backtest: would it help?", icon="🧪"),
    ],
})

with st.sidebar:
    agents = [PILOT_AGENT] + sorted(tickets()["assigned_agent"].unique().to_list())
    st.selectbox("You are", agents, key="agent")
    st.caption(f"Knowledge: 1,444 historical tickets + {pilot_tickets_learned()} finished pilot tickets.")

nav.run()
