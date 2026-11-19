"""The two checkpoints: before escalating and before closing.

Rules are deliberately simple and readable. Every verdict carries the
evidence (counts of similar past tickets) that produced it.
"""
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from app.data import CONFIG, DUPLICATE, FIXED, HOWTO, INFO, NOT_REPRO
from app.knowledge import Knowledge, Stats
from app.match import best_match, similar

CHECKLISTS_FILE = Path(__file__).with_name("checklists.yaml")

# Tunable thresholds (kept in one place so they are easy to explain and change).
SMOOTHING = 5           # how many "average" tickets we blend in when an issue has little history
KNOWN_ISSUE_AT = 0.15   # flag as a likely known issue when >=15% of similar escalations were duplicates
REOPEN_WARN_AT = 0.15   # warn before closing when predicted reopen risk is at least 15%
GROUP_AT = 80           # past descriptions at least this similar (same category) count as the same issue
USUALLY_L1_AT = 0.5     # say "usually solved at L1" when at least half of similar tickets were (and 2+ of them)

ESCALATE = "Escalate"
MISSING_INFO = "Missing info"
KNOWN_ISSUE = "Known issue"
CHECK_CONFIG = "Check config first"
TRY_L1 = "Try fixing at L1"

# Picked when a ticket fits none of the known categories. It uses the _default checklist, and the
# support lead turns repeated ones into a real category in the checklist editor.
NEW_CATEGORY = "Other / new issue"

ICONS = {ESCALATE: "🟢", MISSING_INFO: "🔴", KNOWN_ISSUE: "🟡", CHECK_CONFIG: "🟠", TRY_L1: "🔵"}


@cache
def checklists() -> dict:
    return yaml.safe_load(CHECKLISTS_FILE.read_text(encoding="utf-8"))


def checklist(category: str) -> dict:
    lists = checklists()
    return {**lists["_default"], **lists.get(category, {})}


def save_checklists(lists: dict) -> None:
    """Write the checklists back to YAML, keeping the explanatory header comments."""
    header = "".join(l for l in CHECKLISTS_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
                     if l.startswith("#"))
    CHECKLISTS_FILE.write_text(header + "\n" + yaml.safe_dump(lists, sort_keys=False, allow_unicode=True),
                               encoding="utf-8")
    checklists.cache_clear()


def category_options(kb: Knowledge) -> list[str]:
    """Categories an agent can pick: ones with history, ones the support lead created, then 'Other'."""
    known = (set(kb.categories) | set(checklists())) - {"_default", NEW_CATEGORY}
    return sorted(known) + [NEW_CATEGORY]


@dataclass
class Reason:
    verdict: str
    share: float      # share of similar escalations that ended this way
    count: int
    text: str
    checks: list[str] = field(default_factory=list)


@dataclass
class EscalationResult:
    verdict: str
    headline: str
    matched_description: str | None
    match_score: float
    evidence: Stats
    evidence_level: str           # "issue", "category", or "none" (a category with no history yet)
    shares: dict[str, float]
    reasons: list[Reason]
    required_info: list[str]
    missing_info: list[str]
    unchecked_config: list[str]
    known_issue: dict | None
    issue_stats: Stats | None = None   # the matched issue's full history (escalated or not)

    @property
    def usually_l1(self) -> bool:
        """Most similar past tickets were solved by L1 without engineering, so escalating may not be needed."""
        s = self.issue_stats
        return bool(s and s.l1_fixed >= 2 and s.l1_fixed / s.tickets >= USUALLY_L1_AT)  # same rule as TRY_L1

    @property
    def icon(self) -> str:
        return ICONS[self.verdict]

    @property
    def flagged(self) -> bool:
        return self.verdict != ESCALATE


@dataclass
class CloseResult:
    risk: float
    warn: bool
    issue_rate: float
    agent_factor: float
    evidence: Stats
    checks: list[str]
    headline: str


def _shares(issue: Stats | None, category: Stats, overall: Stats) -> dict[str, float]:
    """Outcome shares for the issue, blended toward the category when history is thin."""
    def base(o: str) -> float:
        cat = (category.outcomes.get(o, 0) + SMOOTHING * overall.outcomes.get(o, 0) / max(overall.escalated, 1))
        return cat / (category.escalated + SMOOTHING)

    if issue is None:
        return {o: base(o) for o in overall.outcomes}
    return {
        o: (issue.outcomes.get(o, 0) + SMOOTHING * base(o)) / (issue.escalated + SMOOTHING)
        for o in overall.outcomes
    }


def _merge(stats: list[Stats]) -> Stats:
    out = Stats()
    for st_ in stats:
        out.tickets += st_.tickets
        out.escalated += st_.escalated
        out.reopened += st_.reopened
        out.l1_fixed += st_.l1_fixed
        for o, n in st_.outcomes.items():
            out.outcomes[o] = out.outcomes.get(o, 0) + n
    return out


def _lookup(kb: Knowledge, category: str, description: str):
    """Best-matching past issue, plus every other past wording of it in this category.

    Agents describe the same problem in different words ("ads in the app", "ads showing in my app"),
    so the history of all descriptions that match closely enough (GROUP_AT) is added together.
    """
    choices = kb.descriptions(category)
    matched, score = best_match(description, choices)
    issue = None
    if matched:
        alike = [d for d, sc in similar(description, choices, GROUP_AT)] or [matched]
        if matched not in alike:
            alike.append(matched)
        issue = _merge([kb.issues[(category, d)] for d in alike])
    cat = kb.categories.get(category, kb.overall)
    return matched, score, issue, cat


def escalation_check(
    kb: Knowledge,
    category: str,
    description: str,
    info_provided: list[str] | None = None,
    config_checked: list[str] | None = None,
) -> EscalationResult:
    """Run before escalating.

    Order of the gate:
      1. Known issue?      -> link to the existing engineering ticket instead of escalating
      2. Info complete?    -> engineering returns tickets without it
      3. Config checked?   -> L1 can often fix these without engineering
      4. All done          -> escalate, with a pre-filled note

    `info_provided` / `config_checked` = None means "not asked yet" (the backtest only
    evaluates step 1, the one step that is a prediction rather than a checklist).
    """
    matched, score, issue, cat = _lookup(kb, category, description)
    evidence = issue if issue and issue.escalated else cat
    shares = _shares(issue if issue and issue.escalated else None, cat, kb.overall)
    lists = checklist(category)
    n = evidence.escalated

    def cnt(o: str) -> int:
        return evidence.outcomes.get(o, 0)

    known = None
    if matched is not None:
        k = kb.known_issues.filter(
            (kb.known_issues["category"] == category) & (kb.known_issues["description"] == matched)
        )
        if k.height and shares[DUPLICATE] >= KNOWN_ISSUE_AT:
            known = k.row(0, named=True)

    reasons = [
        Reason(MISSING_INFO, shares[INFO] + shares[NOT_REPRO], cnt(INFO) + cnt(NOT_REPRO),
               f"{cnt(INFO) + cnt(NOT_REPRO)} of {n} similar escalations came back for missing info "
               "or could not be reproduced.", lists["required_info"]),
        Reason(CHECK_CONFIG, shares[CONFIG] + shares[HOWTO], cnt(CONFIG) + cnt(HOWTO),
               f"{cnt(CONFIG) + cnt(HOWTO)} of {n} were a config setting or how-to question L1 could handle.",
               lists["config_checks"]),
        Reason(KNOWN_ISSUE, shares[DUPLICATE], cnt(DUPLICATE),
               f"{cnt(DUPLICATE)} of {n} were duplicates of a bug engineering already knew about.",
               ["Check the known-issues list and link this ticket to the existing engineering ticket"]),
    ]

    required = lists["required_info"]
    missing = [] if info_provided is None else [i for i in required if i not in info_provided]
    unchecked = [] if config_checked is None else [c for c in lists["config_checks"] if c not in config_checked]
    has_history = category in kb.categories and category != NEW_CATEGORY
    # One plain sentence about *all* similar past tickets (not only the escalated ones).
    seen = issue if issue else cat
    if not has_history:
        history = "No history for this kind of ticket yet, so follow the basic checklist."
    else:
        e_ = seen.escalated
        history = (f"Of {seen.tickets} similar past tickets, {seen.l1_fixed} were solved at L1 and " +
                   (f"{e_} went to engineering ({seen.outcomes.get(FIXED, 0)} real bugs, {seen.avoidable} came back "
                    "without a fix)." if e_ else "none went to engineering."))
    usually_l1 = bool(issue and issue.l1_fixed >= 2 and issue.l1_fixed / issue.tickets >= USUALLY_L1_AT)

    if known:
        verdict = KNOWN_ISSUE
        headline = (f"Likely a known issue (last engineering ticket {known['last_eng_ticket']}). "
                    "Link to it and update the client instead of opening a new escalation.")
    elif usually_l1 and (missing or unchecked):
        verdict = TRY_L1
        todo = len(missing) + len(unchecked)
        headline = (f"Most tickets like this never needed engineering. {history} Try the fix yourself first. "
                    f"If it doesn't work, complete the checklist ({todo} item(s) left) and escalate.")
    elif missing:
        verdict = MISSING_INFO
        headline = f"Collect {len(missing)} missing item(s) first. {history}"
    elif unchecked:
        verdict = CHECK_CONFIG
        headline = f"Run {len(unchecked)} config check(s) first. {history}"
    else:
        verdict = ESCALATE
        headline = f"Ready to escalate with complete info. {history}"

    return EscalationResult(
        verdict=verdict, headline=headline, matched_description=matched, match_score=score,
        evidence=evidence, evidence_level="issue" if evidence is issue else "category" if has_history else "none",
        shares=shares, reasons=reasons, required_info=required, missing_info=missing, unchecked_config=unchecked, known_issue=known,
        issue_stats=issue,
    )


def close_check(kb: Knowledge, category: str, description: str, agent: str | None = None) -> CloseResult:
    """Run before closing: how likely is the client to reopen this?"""
    matched, _, issue, cat = _lookup(kb, category, description)
    cat_rate = (cat.reopened + SMOOTHING * kb.overall.reopened / kb.overall.tickets) / (cat.tickets + SMOOTHING)
    if issue:
        issue_rate = (issue.reopened + SMOOTHING * cat_rate) / (issue.tickets + SMOOTHING)
        evidence = issue
    else:
        issue_rate, evidence = cat_rate, cat
    factor = kb.agent_reopen_factor.get(agent, 1.0) if agent else 1.0
    risk = min(issue_rate * factor, 0.95)
    warn = risk >= REOPEN_WARN_AT
    checks = checklist(category)["close_checks"]
    if category not in kb.categories or category == NEW_CATEGORY:
        headline = (f"New kind of ticket, so this uses the average reopen rate ({risk:.0%}). "
                    "Confirm with the client before closing.")
    elif warn:
        headline = f"High reopen risk ({risk:.0%}). Confirm with the client before closing."
    else:
        headline = f"Low reopen risk ({risk:.0%}). OK to close."
    return CloseResult(risk, warn, issue_rate, factor, evidence, checks, headline)
