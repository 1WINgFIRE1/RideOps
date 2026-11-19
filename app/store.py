"""Pilot log: every ticket, check, action and outcome from real use, in one SQLite file.

Three tables:
  tickets      one row per pilot ticket (status moves as it travels between L1, engineering and client)
  escalations  one row each time L1 sends a ticket to engineering, with what the tool said and what eng decided
  closes       one row each time L1 closes a ticket, with the predicted reopen risk and whether the client reopened

SQLite keeps the pilot to one file with no server. For a real rollout, point RIDEOPS_DB at Postgres instead
(same tables) so several agents can work at once.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import polars as pl

DB_PATH = Path(os.environ.get("RIDEOPS_DB", Path(__file__).resolve().parent.parent / "data" / "pilot.db"))

# Ticket statuses: where the ticket is right now.
NEW, WITH_ENG, BACK_FROM_ENG, CLOSED, REOPENED = "New", "With engineering", "Back from engineering", "Closed", "Reopened"
OPEN_FOR_L1 = (NEW, BACK_FROM_ENG, REOPENED)
# How a ticket was closed.
CLOSED_NORMAL, FIXED_AT_L1, LINKED_KNOWN = "Closed", "Fixed at L1", "Linked to known issue"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY, created_at TEXT, client_name TEXT, category TEXT, description TEXT,
  priority TEXT, agent TEXT, status TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS escalations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, at TEXT, agent TEXT, tool_verdict TEXT,
  known_issue_flag INTEGER, info_ticked INTEGER, info_total INTEGER, config_ticked INTEGER, config_total INTEGER,
  outcome TEXT, eng_note TEXT, outcome_at TEXT);
CREATE TABLE IF NOT EXISTS closes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, at TEXT, agent TEXT, how TEXT,
  reopen_risk REAL, warned INTEGER, reopened INTEGER, client_at TEXT);
"""


@contextmanager
def connect(path: Path | None = None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def version(path: Path | None = None) -> int:
    """Changes whenever anything is written. Used to refresh cached knowledge and metrics."""
    with connect(path) as con:
        return sum(con.execute(f"SELECT COUNT(*) + COALESCE(SUM(LENGTH(COALESCE({c}, ''))), 0) FROM {t}").fetchone()[0]
                   for t, c in [("tickets", "status || category"), ("escalations", "outcome"), ("closes", "reopened")])


def upsert_ticket(t: dict, path: Path | None = None) -> str:
    with connect(path) as con:
        if not t.get("id"):
            n = con.execute("SELECT COUNT(*) FROM tickets WHERE source = 'new'").fetchone()[0] + 1
            t["id"] = f"PIL-{n:04d}"
        con.execute(
            "INSERT INTO tickets (id, created_at, client_name, category, description, priority, agent, status, source) "
            "VALUES (:id, :created_at, :client_name, :category, :description, :priority, :agent, :status, :source) "
            "ON CONFLICT(id) DO NOTHING",
            {"created_at": now(), "status": NEW, "priority": "P3", "source": "new", **t},
        )
    return t["id"]


def set_category(ticket_ids: list[str], category: str, path: Path | None = None) -> None:
    """Move tickets into a category (used when the support lead creates a new one)."""
    with connect(path) as con:
        con.executemany("UPDATE tickets SET category = ? WHERE id = ?", [(category, i) for i in ticket_ids])


def set_status(ticket_id: str, status: str, path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))


def log_escalation(ticket_id, agent, verdict, known_flag, info_ticked, info_total, cfg_ticked, cfg_total,
                   path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute(
            "INSERT INTO escalations (ticket_id, at, agent, tool_verdict, known_issue_flag, info_ticked, info_total, "
            "config_ticked, config_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, now(), agent, verdict, int(known_flag), info_ticked, info_total, cfg_ticked, cfg_total))
        con.execute("UPDATE tickets SET status = ? WHERE id = ?", (WITH_ENG, ticket_id))


def record_eng_outcome(escalation_id: int, outcome: str, note: str = "", path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute("UPDATE escalations SET outcome = ?, eng_note = ?, outcome_at = ? WHERE id = ?",
                    (outcome, note.strip() or None, now(), escalation_id))
        tid = con.execute("SELECT ticket_id FROM escalations WHERE id = ?", (escalation_id,)).fetchone()[0]
        con.execute("UPDATE tickets SET status = ? WHERE id = ?", (BACK_FROM_ENG, tid))


def log_close(ticket_id, agent, how, risk, warned, path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute("INSERT INTO closes (ticket_id, at, agent, how, reopen_risk, warned) VALUES (?, ?, ?, ?, ?, ?)",
                    (ticket_id, now(), agent, how, risk, int(warned)))
        con.execute("UPDATE tickets SET status = ? WHERE id = ?", (CLOSED, ticket_id))


def record_client_response(close_id: int, reopened: bool, path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute("UPDATE closes SET reopened = ?, client_at = ? WHERE id = ?", (int(reopened), now(), close_id))
        if reopened:
            tid = con.execute("SELECT ticket_id FROM closes WHERE id = ?", (close_id,)).fetchone()[0]
            con.execute("UPDATE tickets SET status = ? WHERE id = ?", (REOPENED, tid))


def table(name: str, path: Path | None = None) -> pl.DataFrame:
    with connect(path) as con:
        cur = con.execute(f"SELECT * FROM {name}")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pl.DataFrame([dict(r) for r in rows], schema=None if rows else {c: pl.String for c in cols},
                      infer_schema_length=None)
    for c in ("created_at", "at", "outcome_at", "client_at"):
        if c in df.columns:
            df = df.with_columns(pl.col(c).cast(pl.String).str.to_datetime("%Y-%m-%d %H:%M", strict=False))
    return df


def reset(path: Path | None = None) -> None:
    with connect(path) as con:
        con.executescript("DELETE FROM tickets; DELETE FROM escalations; DELETE FROM closes;")


def as_history(path: Path | None = None) -> pl.DataFrame:
    """Pilot tickets in the same columns as the CSV, so the knowledge builder learns from them too.
    Only finished tickets are included (status Closed and the client has answered), so a ticket never
    matches against itself while it is still being worked."""
    t, e, c = table("tickets", path), table("escalations", path), table("closes", path)
    if t.is_empty():
        return pl.DataFrame()
    rows = []
    for tk in t.iter_rows(named=True):
        es = e.filter((pl.col("ticket_id") == tk["id"]) & pl.col("outcome").is_not_null()) if e.height else e
        cs = c.filter((pl.col("ticket_id") == tk["id"]) & pl.col("reopened").is_not_null()) if c.height else c
        if tk["status"] != CLOSED or cs.is_empty():
            continue
        last_close = cs.sort("at").row(-1, named=True) if cs.height else None
        rows.append({
            "ticket_id": tk["id"], "created_at": tk["created_at"], "channel": "Pilot", "client_id": "PILOT",
            "client_name": tk["client_name"], "client_tier": "Pilot", "category": tk["category"],
            "priority": tk["priority"], "description": tk["description"], "assigned_agent": tk["agent"],
            "first_response_at": tk["created_at"],
            "escalated_to_eng": "Yes" if es.height else "No",
            "eng_ticket_id": f"ENG-PIL-{es.sort('at')['id'][-1]}" if es.height else None,
            "eng_handoffs": es.height, "eng_outcome": es.sort("at")["outcome"][-1] if es.height else None,
            "status": tk["status"],
            "first_closed_at": cs.sort("at")["at"][0] if cs.height else None,
            "final_closed_at": last_close["at"] if last_close and not last_close["reopened"] else None,
            "reopen_count": int(cs["reopened"].sum()) if cs.height else 0, "csat_score": None,
        })
    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame(rows, infer_schema_length=None)
    return df.with_columns(
        [pl.col(c).cast(pl.Datetime("us")) for c in ("created_at", "first_response_at", "first_closed_at", "final_closed_at")]
        + [pl.col(c).cast(pl.String) for c in ("eng_ticket_id", "eng_outcome")]
        + [pl.col("eng_handoffs").cast(pl.Int64), pl.col("reopen_count").cast(pl.Int64), pl.col("csat_score").cast(pl.Float64)]
    )
