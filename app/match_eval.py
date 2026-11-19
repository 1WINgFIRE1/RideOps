"""How often does the matcher find the right past issue when a client words it differently?

36 client-style rewordings, each with the past issue it really is. We check whether the
top match (within the ticket's category) is the right one.

    uv run python analysis/matching_eval.py   (or the Backtest page)
"""
import re

from rapidfuzz import fuzz, utils

from app import match
from app.data import load_tickets

CASES = [  # (category, how a client might write it, the past issue it really is)
    ("Roster / booking not syncing", "We changed the booking cutoff to 6 PM but tomorrow's roster still uses 8 PM",
     "Booking cutoff changed but roster still uses old cutoff"),
    ("Roster / booking not syncing", "cutoff time updated in settings, roster not picking it up",
     "Booking cutoff changed but roster still uses old cutoff"),
    ("Roster / booking not syncing", "people who cancelled are still on tomorrow's list",
     "Cancelled bookings still appearing in tomorrow's roster"),
    ("Roster / booking not syncing", "uploaded the excel sheet, 20 people didn't come through",
     "Roster uploaded via Excel but N employees missing"),
    ("Roster / booking not syncing", "same employee appears twice in the roster",
     "Roster shows duplicate entries for N employees"),
    ("Roster / booking not syncing", "admin made a booking but the employee can't see it",
     "Ad-hoc booking done by admin not reflecting for employee"),
    ("Live tracking / GPS incorrect", "cab icon keeps jumping around on the map",
     "Driver app GPS jumping between locations"),
    ("Live tracking / GPS incorrect", "map stuck, cab hasn't moved in 15 minutes",
     "Cab location frozen on map for last N mins"),
    ("Live tracking / GPS incorrect", "security can't open the tracking link",
     "Tracking link not opening for security team"),
    ("Live tracking / GPS incorrect", "ETA is wrong so people miss the pickup",
     "ETA showing wrong, employees missing pickup"),
    ("Live tracking / GPS incorrect", "app says cab is far away but it's already at the gate",
     "Employee app shows cab N km away while cab is at gate"),
    ("OTP / boarding issue", "employee never got the OTP to board",
     "Employee not receiving boarding OTP"),
    ("OTP / boarding issue", "driver app says the OTP is invalid",
     "OTP shown as invalid on driver app"),
    ("OTP / boarding issue", "employee was in the cab but shows not boarded",
     "Employee marked not boarded despite boarding"),
    ("OTP / boarding issue", "entered OTP but trip won't start",
     "Trip not starting even after OTP entry"),
    ("Billing / invoice discrepancy", "toll charged two times on the bill",
     "Toll charges added twice in invoice"),
    ("Billing / invoice discrepancy", "number of trips on invoice is different from ours",
     "Invoice trip count does not match our records"),
    ("Billing / invoice discrepancy", "we are paying dead km for trips that were cancelled",
     "Dead-km charged for cancelled trips"),
    ("Report export failing", "billing report excel comes out empty",
     "Excel export of billing report is blank"),
    ("Report export failing", "monthly report keeps loading and never downloads",
     "Monthly trip report download stuck at loading"),
    ("Report export failing", "didn't get the scheduled report in email",
     "Scheduled report email not received"),
    ("Login / access issue", "after resetting password employee can't get in",
     "Employee locked out after password reset"),
    ("Login / access issue", "SSO not working for some users",
     "SSO login failing for N users"),
    ("Login / access issue", "new manager needs access to reports",
     "Need access to reports module for new manager"),
    ("Cab delay / no-show complaint", "cab never came, employee had to take an auto",
     "Cab did not turn up, employee took own transport"),
    ("Cab delay / no-show complaint", "driver marked no-show but never reached the pickup",
     "Driver marked employee no-show without arriving"),
    ("Employee address / geocode change", "employee shifted house but pickup is still the old address",
     "Employee moved, pickup point still old address"),
    ("Employee address / geocode change", "pins are wrong for the new apartment complex",
     "Pin location wrong for N employees in new society"),
    ("Driver / vehicle compliance docs", "can't upload the fitness certificate",
     "Unable to upload fitness certificate"),
    ("How-to / feature request", "how do I add a new shift time?",
     "How to add a new shift timing?"),
    # Same problem, almost no shared words: this is where matching on meaning matters.
    ("Login / access issue", "can't sign in through single sign-on", "SSO login failing for N users"),
    ("Cab delay / no-show complaint", "transport never arrived, staff used their own vehicle",
     "Cab did not turn up, employee took own transport"),
    ("Live tracking / GPS incorrect", "vehicle position not updating for a while",
     "Cab location frozen on map for last N mins"),
    ("OTP / boarding issue", "attendance shows she didn't board but she rode the cab",
     "Employee marked not boarded despite boarding"),
    ("Roster / booking not syncing", "duplicate names in the roster", "Roster shows duplicate entries for N employees"),
    ("Billing / invoice discrepancy", "new vendor's prices not used on the bill", "Rate card for new vendor not applied"),
]


# Problems the history has never seen, typed into the nearest category. The right answer is "no close match".
NEW_PROBLEMS = [
    ("Cab delay / no-show complaint", "driver was rude and played loud music"),
    ("Live tracking / GPS incorrect", "app showing unwanted ads"),
    ("Roster / booking not syncing", "need invoice copy for last month"),
    ("OTP / boarding issue", "SOS button does not alert security"),
    ("Login / access issue", "dashboard is in the wrong language"),
    ("Billing / invoice discrepancy", "GST number wrong on invoice"),
    ("Report export failing", "want a new column for cost centre in report"),
]


def canon(d: str) -> str:
    return re.sub(r"\d+", "N", d)


def run(return_rows: bool = False):
    df = load_tickets()
    by_cat = {c: g["description"].unique().to_list() for (c,), g in df.group_by(["category"])}
    hits = {"shared words only (old)": 0, "meaning + words (now)": 0}
    rows = []
    for cat, text, truth in CASES:
        choices = by_cat[cat]
        words = max(choices, key=lambda d: fuzz.token_set_ratio(text, d, processor=utils.default_process))
        now, score = match.scores(text, choices)[0]
        hits["shared words only (old)"] += canon(words) == truth
        hits["meaning + words (now)"] += canon(now) == truth
        ok = canon(now) == truth and score >= match.MIN_SCORE
        hits["matched and confident"] = hits.get("matched and confident", 0) + ok
        rows.append({"client wrote": text, "tool matched": now if score >= match.MIN_SCORE else "(no close match)",
                     "similarity": round(score), "right?": "✅" if ok else "❌", "words-only matched": words})
    rates = {k: v / len(CASES) for k, v in hits.items()}
    new_ok = 0
    for cat, text in NEW_PROBLEMS:
        top, score = match.scores(text, by_cat[cat])[0]
        new_ok += score < match.MIN_SCORE
        rows.append({"client wrote": f"[new problem] {text}",
                     "tool matched": top if score >= match.MIN_SCORE else "(no close match)",
                     "similarity": round(score), "right?": "✅" if score < match.MIN_SCORE else "❌",
                     "words-only matched": ""})
    rates["new problems spotted as new"] = new_ok / len(NEW_PROBLEMS)
    return (rates, rows) if return_rows else rates


