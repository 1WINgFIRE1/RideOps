"""Turn past tickets into "what usually happens" statistics.

This is just counting, like an Excel pivot table:
for each issue (category + description) and each category we count how
escalations ended and how often tickets reopened.
"""
from dataclasses import dataclass, field

from datetime import timedelta

import polars as pl

from app.data import AVOIDABLE, CONFIG, DUPLICATE, FIXED, HOWTO, INFO, NOT_REPRO

AGENT_WINDOW_DAYS = 28  # four weeks

OUTCOMES = [FIXED, INFO, CONFIG, DUPLICATE, HOWTO, NOT_REPRO]


@dataclass
class Stats:
    tickets: int = 0
    escalated: int = 0
    reopened: int = 0
    l1_fixed: int = 0      # closed by L1 without engineering, and the client did not reopen
    outcomes: dict[str, int] = field(default_factory=dict)

    @property
    def avoidable(self) -> int:
        return sum(self.outcomes.get(o, 0) for o in AVOIDABLE)


@dataclass
class Knowledge:
    issues: dict[tuple[str, str], Stats]   # (category, description) -> stats
    categories: dict[str, Stats]
    overall: Stats
    agent_reopen_factor: dict[str, float]  # 1.0 = normal, 2.0 = reopens twice as often as expected
    known_issues: pl.DataFrame             # past bugs engineering already knows about
    history: pl.DataFrame                  # the tickets this was built from

    def descriptions(self, category: str | None = None) -> list[str]:
        return sorted({d for (c, d) in self.issues if category is None or c == category})


def _stats(df: pl.DataFrame) -> Stats:
    esc = df.filter(pl.col("escalated"))
    counts = dict(esc.group_by("eng_outcome").len().iter_rows())
    return Stats(
        tickets=df.height,
        escalated=esc.height,
        reopened=int(df["reopened"].sum()),
        l1_fixed=df.filter(~pl.col("escalated") & ~pl.col("reopened") & ~pl.col("is_open")).height,
        outcomes={o: int(counts.get(o, 0)) for o in OUTCOMES},
    )


def build_knowledge(df: pl.DataFrame) -> Knowledge:
    issues = {
        (key[0], key[1]): _stats(g)
        for key, g in df.group_by(["category", "description"])
    }
    categories = {key[0]: _stats(g) for key, g in df.group_by(["category"])}

    # Agent reopen factor: actual reopens vs what their category mix would predict.
    # Only the last AGENT_WINDOW_DAYS count, so the factor follows how an agent works *now*:
    # someone who improves drops back toward 1.0, and a new joiner starts at 1.0.
    cat_rate = df.group_by("category").agg(cat_reopen=pl.col("reopened").mean())
    recent = df.filter(pl.col("created_at") > df["created_at"].max() - timedelta(days=AGENT_WINDOW_DAYS))
    by_agent = (
        recent.join(cat_rate, on="category")
        .group_by("assigned_agent")
        .agg(actual=pl.col("reopened").sum(), expected=pl.col("cat_reopen").sum())
    )
    # Smoothed so an agent with few tickets is not judged harshly: add 5 "expected" reopens to both sides.
    agent_factor = {
        a: (act + 5) / (exp + 5) for a, act, exp in by_agent.iter_rows()
    }

    known = (
        df.filter(pl.col("eng_outcome").is_in([FIXED, DUPLICATE]))
        .group_by(["category", "description"])
        .agg(
            times_fixed=(pl.col("eng_outcome") == FIXED).sum(),
            times_duplicate=(pl.col("eng_outcome") == DUPLICATE).sum(),
            last_seen=pl.col("created_at").max(),
            last_eng_ticket=pl.col("eng_ticket_id").sort_by("created_at").last(),
        )
        .filter((pl.col("times_duplicate") >= 1) | (pl.col("times_fixed") >= 3))
        .sort(["times_fixed", "times_duplicate"], descending=True)
    )

    return Knowledge(
        issues=issues,
        categories=categories,
        overall=_stats(df),
        agent_reopen_factor=agent_factor,
        known_issues=known,
        history=df,
    )
