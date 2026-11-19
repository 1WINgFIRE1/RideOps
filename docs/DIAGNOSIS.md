# RideOps Support: Diagnosis

Based on `rideops_support_tickets.csv`: 1,444 tickets raised 2 Jul to 30 Sep 2026, pulled on 30 Sep 2026.

## TL;DR

- **Only 15% of tickets genuinely needed engineering to fix something.**
- **19% of tickets were escalated to engineering and came back unfixed.** They account for **47% of all the time tickets spent open.**
- Those tickets bounce: L1 escalates, engineering returns it, L1 escalates again. This bouncing is what the support lead means by tickets "disappearing".
- One agent (Karan B) closes tickets too early and they reopen. That's real, but it's only about 7% of the backlog.
- **Recommended fix:** a pre-check for L1 agents that runs before a ticket is escalated or closed. No new hires needed.

---

## Key terms

| Term | Meaning |
|---|---|
| **L1 agent** | A human first-line support agent. The data has 8 of them (`assigned_agent`). |
| **Escalation** | L1 sends the ticket to engineering (`escalated_to_eng = Yes`). |
| **Handoff** | One trip from L1 to engineering (`eng_handoffs`). 1 means it went once. 2 means it went, came back to L1, and was sent again. The maximum is 3. |
| **Engineering outcome** | Engineering's final verdict (`eng_outcome`): *Fixed*, *Insufficient info*, *Config issue*, *Duplicate of known issue*, *Not a bug / how-to*, or *Not reproducible*. |
| **Reopen** | The ticket was marked closed, but the client said it wasn't solved and reopened it (`reopen_count > 0`). |
| **Priority P1 to P4** | How urgent the ticket is. P1 = critical (e.g. cabs not running). P2 = high. P3 = normal. P4 = low (e.g. access for a new manager). |
| **First response time** | Hours from the client raising the ticket to the first L1 reply (`first_response_at − created_at`). |
| **CSAT** | Client satisfaction score, 1 (bad) to 5 (great). |
| **Backlog hours** | Hours each ticket stayed open (`final_closed_at − created_at`, or up to 30 Sep if still open), summed per group. See below. |

### Why "backlog hours"?

Leadership tracks the number of **open tickets**. That number depends on two things: how many tickets arrive, and **how long each one stays open**. A ticket open for 5 days sits in the open count 10 times longer than one closed in 12 hours.

So to see which kind of ticket is filling the backlog, I add up the hours each one was open. A group's **% of backlog hours** is its share of the open count over the quarter.

---

## Where every ticket ends up

Each ticket goes into exactly one bucket.

| # | Bucket | Tickets | % of tickets | % of backlog hours | Median hours open | Avg CSAT |
|---|---|---|---|---|---|---|
| 1 | Resolved by L1, stayed closed | 862 | 59.7% | 20.3% | 11 | 4.2 |
| 2 | **Real bug, engineering fixed it** | 211 | **14.6%** | 24.5% | 65 | 3.4 |
| 3 | Escalated, returned: *insufficient info* | 89 | 6.2% | 17.8% | 117 | 2.7 |
| 4 | Escalated, returned: *config issue* | 84 | 5.8% | 17.6% | 129 | 2.4 |
| 5 | Escalated: *duplicate of known issue* | 56 | 3.9% | 6.6% | 67 | 3.5 |
| 6 | Escalated: *not a bug / how-to* | 24 | 1.7% | 2.6% | 67 | 3.2 |
| 7 | Escalated: *not reproducible* | 22 | 1.5% | 2.3% | 63 | 3.4 |
| 8 | Resolved by L1, then client reopened | 96 | 6.6% | 8.2% | 45 | 2.4 |

**What each bucket means**

1. **Resolved by L1, stayed closed.** The healthy path. L1 solved it in about half a day and the client was happy (4.2). This is 60% of tickets but only 20% of the backlog.
2. **Real bug, engineering fixed it.** This is what escalation is for. It's slow (about 2.7 days) but legitimate. These 211 tickets are the only ones that genuinely needed engineering.
3. **Insufficient info.** L1 escalated without the details engineering needs, such as which employee, which booking, a screenshot or the time. Engineering sent it back to ask. These tickets average almost 5 days open.
4. **Config issue.** The fault was a setting in the client's account, such as a cutoff time, a shift window or a geofence. L1 could have fixed it without engineering. This is the slowest bucket (5.4 days) and the unhappiest (2.4).
5. **Duplicate of known issue.** Engineering already knew about the bug. L1 had no list of known issues to check against, so it escalated again.
6. **Not a bug / how-to.** The client didn't know how to use a feature. L1 should have answered it.
7. **Not reproducible.** Engineering couldn't make the problem happen. Usually this is also a sign of missing info.
8. **Reopened.** L1 marked the ticket closed, but it wasn't solved, so the client came back. This is the worst CSAT in the data (2.4).

**Buckets 3 to 7 are "avoidable escalations":** 275 tickets, **19% of volume, 47% of backlog hours.** All escalated tickets together (buckets 2 to 7) are a third of volume but **71% of backlog hours**.

---

## What "disappearing" means: the bounce

The support lead says escalated tickets "disappear for days". The data shows why.

- The `eng_handoffs` column counts trips to engineering.
- **Every** *insufficient info* and *config issue* ticket has 2 or 3 handoffs. In each case, engineering sent the ticket back and L1 escalated it again, often still without the fix.
- 38 of the genuine fixes also bounced once before being fixed.

Resolution time rises with every trip:

| Trips to engineering | Tickets | Median hours open (incl. still-open tickets) |
|---|---|---|
| 0 | 958 | 13 |
| 1 | 257 | 58 |
| 2 | 167 | 110 |
| 3 | 62 | 164 |

The client sees one ticket stuck for a week, with no updates. Behind the scenes it is bouncing between two teams. Neither team owns it while it's with the other, so nobody can tell the client what's happening.

---

## Is it Karan's fault?

**Partly, but he isn't the main problem.**

- **Karan B closes the fastest.** His median first close is 8 hours, against about 20 hours for the others. This is the "some agents close in a few hours" the support lead mentioned.
- **29.5% of his tickets reopen.** Given the categories he handles, about 10.6% would be expected, and the other agents are at 5 to 9%. He accounts for 64 of the 151 reopened tickets.
- **It isn't harder tickets.** His mix of priority, client tier and channel matches everyone else's. On cab-delay tickets he reopens 43% vs 2% for the others. On GPS tickets it's 44% vs 11%.
- **He under-escalates.** He sends 16% of his tickets to engineering when about 34% would be expected for his mix. He closes issues that weren't really solved.
- **His CSAT is the lowest on the team (3.1).** It drops to 2.0 on his reopened tickets.
- **But his reopens are only about 7% of backlog hours.** Fixing Karan alone will not bring the open-ticket number down.

**The lesson:** closing fast is not the same as resolving. A speed target on its own would make the problem worse.

---

## Two different L1 mistakes, one tool

| | Avoidable escalation | Premature close (reopen) |
|---|---|---|
| What L1 does | Sends to engineering something L1 could handle | Closes something that isn't actually fixed |
| Direction | Over-escalating | Under-resolving |
| Example agent | Rahul T (escalates 62%, only 25% fixed) | Karan B (escalates 16%, 29.5% reopen) |
| Share of backlog hours | 47% | 8% |
| When to catch it | **Before escalating** | **Before closing** |

These are opposite mistakes, made at two different moments. Both come down to L1 making a decision without a checklist. So one tool can cover both: a pre-check that runs when an agent is about to **escalate** (is the info complete? is it a config issue or a known duplicate?) and when an agent is about to **close** (does this category usually reopen? was the client's issue confirmed?).

### Why check before closing at all?

The close check is secondary, but the data gives three reasons to include it:

1. **Reopens add real backlog.** 151 tickets reopened (bucket 8 plus 55 escalated tickets that reopened after the fix). Each reopen kept the ticket open a median of **38 extra hours** after it was first marked closed. That's about **10% of all backlog hours**, and Karan alone accounts for about 4%.
2. **Reopens hurt clients the most.** Average CSAT is 3.8 on tickets that stay closed and **2.35** on reopened ones, the lowest of any group.
3. **It stops the main fix from backfiring.** The escalation check tells agents to escalate less. An agent who escalates too little closes unsolved tickets, which is Karan's pattern: 16% escalated and 29.5% reopened. Without a close check, fewer escalations could just turn into more reopens. Reopen rate is therefore the guardrail metric next to escalation quality.

**Priority:** build the escalation check first (47% of backlog). The close check can be a light add-on, or just a tracked metric if time is short.

---

## Other findings

- **The same few bugs keep coming back.** The top 10 issue descriptions make up 53% of all engineering fixes. "Cancelled bookings still appearing in tomorrow's roster" was "fixed" 20 times. Either the fixes don't hold, or L1 can't see that it's a known bug. A known-issues list helps both teams.
- **Escalation quality varies a lot by agent.** Vikram S escalates 30% of his tickets and 60% of them get fixed. Rahul T escalates 62% and only 25% get fixed. Different agents use different judgement, which is a process gap that a shared checklist addresses.
- **Not all growth is software.** Volume rose from 390 tickets in July to 592 in September (+52%). The fastest-growing category is **cab delay / no-show** (29 to 72 a month, 2.5x). That's a driver and fleet-ops problem, and software support can't fix it. Report export (+33) and address change (+26) come next.
- **The team is getting stretched.** Median first response on P3 (normal) tickets went from 2.4h in July to 3.6h in September, and on P4 (low) from 4.5h to 7.1h. The team is busier, partly because bounced tickets keep coming back to them.
- **The "up 60%" claim checks out.** Open tickets averaged about 27 at each week-end in August and reached 50 by 27 September.
- **Roster sync and live tracking are the heart of it.** They make up 40% of all tickets and 30 of the 48 tickets still open.

---

## Method notes and assumptions

- "Open" means `final_closed_at` is blank as of 30 Sep 2026 (48 tickets).
- Backlog hours run from `created_at` to `final_closed_at`, or to 30 Sep 23:59 for tickets still open.
- "Expected" rates for an agent are the overall rate for each category, weighted by that agent's own category mix.
- The data has no per-handoff timestamps, so time spent with L1 and time spent with engineering can't be separated.
- CSAT is missing for 55% of tickets. Averages use only the tickets that have a rating.
- Every number here can be reproduced with `uv run python analysis/diagnosis.py`.
