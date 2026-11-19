"""Live pilot scorecard, computed from the pilot log. Same definitions as the baseline so they compare directly."""
import polars as pl

from app import store
from app.data import AVOIDABLE, DUPLICATE

BASELINE = {"avoidable_rate": 0.57, "reopen_rate": 0.105}


def weekly() -> pl.DataFrame:
    esc, cl = store.table("escalations"), store.table("closes")
    frames = []
    if esc.height:
        e = esc.with_columns(
            week=pl.col("at").dt.truncate("1w"),
            decided=pl.col("outcome").is_not_null(),
            avoidable=pl.col("outcome").is_in(AVOIDABLE),
            complete=(pl.col("info_ticked") == pl.col("info_total")) & (pl.col("config_ticked") == pl.col("config_total")),
        )
        frames.append(e.group_by("week").agg(
            escalations=pl.len(),
            decided=pl.col("decided").sum(),
            returned_unfixed=(pl.col("decided") & pl.col("avoidable")).sum(),
            checklist_complete=pl.col("complete").sum(),
            complete_returned=(pl.col("complete") & pl.col("avoidable")).sum(),
            complete_decided=(pl.col("complete") & pl.col("decided")).sum(),
            flagged_escalated=pl.col("known_issue_flag").sum(),
            flagged_were_dup=((pl.col("known_issue_flag") == 1) & (pl.col("outcome") == DUPLICATE)).sum(),
        ))
    if cl.height:
        c = cl.with_columns(week=pl.col("at").dt.truncate("1w"), answered=pl.col("reopened").is_not_null())
        first_esc = (esc.group_by("ticket_id").agg(first_esc=pl.col("at").min()) if esc.height
                     else pl.DataFrame(schema={"ticket_id": pl.String, "first_esc": pl.Datetime("us")}))
        c = c.join(first_esc, on="ticket_id", how="left").with_columns(
            never_escalated=pl.col("first_esc").is_null() | (pl.col("first_esc") > pl.col("at")))
        frames.append(c.group_by("week").agg(
            closes=pl.len(),
            fixed_at_l1=((pl.col("how") == store.FIXED_AT_L1) & pl.col("never_escalated")).sum(),
            linked_known=((pl.col("how") == store.LINKED_KNOWN) & pl.col("never_escalated")).sum(),
            fixed_at_l1_held=((pl.col("how") == store.FIXED_AT_L1) & (pl.col("reopened") == 0)).sum(),
            fixed_at_l1_answered=((pl.col("how") == store.FIXED_AT_L1) & pl.col("answered")).sum(),
            answered=pl.col("answered").sum(),
            reopened=(pl.col("reopened") == 1).sum(),
            warned_answered=((pl.col("warned") == 1) & pl.col("answered")).sum(),
            warned_reopened=((pl.col("warned") == 1) & (pl.col("reopened") == 1)).sum(),
        ))
    if not frames:
        return pl.DataFrame()
    out = frames[0] if len(frames) == 1 else frames[0].join(frames[1], on="week", how="full", coalesce=True)
    return out.fill_null(0).sort("week")


def totals(w: pl.DataFrame) -> dict:
    if w.is_empty():
        return {}
    s = {c: int(w[c].sum()) for c in w.columns if c != "week"}
    for k in ["escalations", "decided", "returned_unfixed", "checklist_complete", "complete_returned",
              "complete_decided", "flagged_escalated", "flagged_were_dup", "closes", "fixed_at_l1", "linked_known",
              "fixed_at_l1_held", "fixed_at_l1_answered", "answered", "reopened", "warned_answered", "warned_reopened"]:
        s.setdefault(k, 0)
    return s
