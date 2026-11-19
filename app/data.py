"""Load the ticket CSV and add the derived fields every other module uses."""
from pathlib import Path

import polars as pl

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TICKETS_CSV = DATA_DIR / "rideops_support_tickets.csv"
DATA_PULL = pl.datetime(2026, 9, 30, 23, 59)

FIXED = "Fixed"
INFO = "Insufficient info - returned to L1"
CONFIG = "Config issue - returned to L1"
DUPLICATE = "Duplicate of known issue"
HOWTO = "Not a bug - how-to"
NOT_REPRO = "Not reproducible"
AVOIDABLE = [INFO, CONFIG, DUPLICATE, HOWTO, NOT_REPRO]

DATE_COLS = ["created_at", "first_response_at", "first_closed_at", "final_closed_at"]


def load_tickets(path: Path = TICKETS_CSV) -> pl.DataFrame:
    df = pl.read_csv(path)
    df = df.with_columns(
        [pl.col(c).str.to_datetime("%Y-%m-%d %H:%M", strict=False) for c in DATE_COLS]
    )
    return derive(df)


def derive(df: pl.DataFrame) -> pl.DataFrame:
    """Add the fields every module uses. Works for the CSV and for pilot tickets in the same columns."""
    hours = lambda end, start: (end - start).dt.total_minutes() / 60  # noqa: E731
    return df.with_columns(
        escalated=pl.col("escalated_to_eng") == "Yes",
        reopened=pl.col("reopen_count") > 0,
        is_open=pl.col("final_closed_at").is_null(),
        hours_open=hours(pl.col("final_closed_at").fill_null(DATA_PULL), pl.col("created_at")),
        first_response_h=hours(pl.col("first_response_at"), pl.col("created_at")),
        first_close_h=hours(pl.col("first_closed_at"), pl.col("created_at")),
        month=pl.col("created_at").dt.strftime("%Y-%m"),
        week=pl.col("created_at").dt.truncate("1w"),
    ).with_columns(
        bucket=pl.when(~pl.col("escalated") & ~pl.col("reopened")).then(pl.lit("Resolved at L1"))
        .when(~pl.col("escalated")).then(pl.lit("Resolved at L1, then reopened"))
        .otherwise(pl.lit("Eng: ") + pl.col("eng_outcome")),
        avoidable=pl.col("eng_outcome").is_in(AVOIDABLE),
    )
