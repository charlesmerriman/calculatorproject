# Income Calculation Reference

This document records the game mechanics behind every carat and ticket income source encoded in the backend fixtures and reflected in the frontend projection engine. Update this file whenever real game values change.

---

## Daily Base Income

Every day grants **75 carats**.

On top of that, certain days within a rolling 7-day cycle grant bonuses. The cycle is anchored to the current date (the day the user opens the calculator):

| Days since anchor (mod 7) | Bonus |
|---|---|
| 0 (first day of each week) | +25 carats |
| 3 | +25 carats |
| 5 | +25 carats |
| 6 (last day of each week) | +75 carats |

The cycle repeats every 7 days. Day 0 is anchored to the day the user opens the calculator.

---

## Daily Carat Bonus (opt-in)

If the user enables the **Daily Carat** toggle, an additional **50 carats/day** is added for every day in the projection window. This represents a separate daily login reward distinct from the base 75.

---

## Training Pass (monthly, day 24)

> **Available from August 15, 2027.** No training pass income is projected for any period before this date — neither the paid reward nor the free tier.

| State | Income |
|---|---|
| Training pass active | **+2,200 carats** on the 24th of each month |
| No training pass | **+500 carats** per calendar month (free tier) |

The 500-carat figure is the free tier of the Training Pass — it applies to all accounts once the feature launches, regardless of whether the paid pass is active.

---

## Club Rank (monthly, 1st of each month)

Paid once per calendar month on the 1st. The projection counts how many month boundaries fall between the previous banner's end date and the current banner's end date.

| Rank | Monthly income (carats) |
|---|---|
| D+ | 225 |
| C | 450 |
| C+ | 900 |
| B | 1,350 |
| B+ | 1,800 |
| A | 2,250 |
| A+ | 2,700 |
| S | 3,150 |
| S+ | 3,600 |
| SS | 4,500 |

---

## Team Trials Rank (weekly, every Monday)

Paid once per week on Monday. The projection counts how many Mondays fall in the window.

| Rank | Weekly income (carats) |
|---|---|
| Class 1 | 0 |
| Class 2 | 35 |
| Class 3 | 75 |
| Class 4 | 150 |
| Class 5 | 225 |
| Class 5.5 | 262 |
| Class 6 | 375 |

---

## Champions Meeting Rank (per event)

Paid once per Champions Meeting event. The projection adds this payout for each `ChampionsMeeting` whose `end_date` falls within the window.

| Placement | Income per event (carats) |
|---|---|
| Champion | 3,300 |
| Second | 2,400 |
| Third | 1,700 |
| Group B 1st | 1,600 |
| Group B 2nd | 1,250 |
| Open League | 1,100 |

---

## League of Heroes Rank (per event)

Paid once per League of Heroes event. The projection adds this payout for each `LeagueOfHeroes` whose `end_date` falls within the window.

| Rank | Income (carats) |
|---|---|
| Silver 4 | 390 |
| Gold 1 | 540 |
| Gold 2 | 690 |
| Gold 3 | 990 |
| Gold 4 | 1,290 |
| Platinum 1 | 1,790 |
| Platinum 2 | 2,290 |
| Platinum 3 | 2,790 |
| Platinum 4 | 3,290 |

---

## Event Rewards

Each `GameEvent` carries its own reward amounts directly (no separate reward model): `carat_amount`, `carats_throughout`, `uma_ticket_amount`, `support_ticket_amount`, `sr_shard_amount` / `sr_crystal_amount`, `ssr_shard_amount` / `ssr_crystal_amount`. These fall into two categories:

- **Immediate (`carat_amount` + all ticket/shard/crystal amounts)**: earned in full as soon as the event's own resolved `start_date` passes. The projection adds these if `start_date` falls strictly after the previous banner's end date and on or before the current banner's end date, same rule as the other date-gated income sources.
- **Throughout (`carats_throughout`)**: carats only, prorated by elapsed time across the event's own `start_date`..`end_date` span rather than granted in one lump. A banner window earns `carats_throughout × (overlap between the window and the event's span) / (event's total span)`. This is computed on real elapsed time (milliseconds), not calendar days — the event's `end_date` isn't guaranteed midnight-aligned (it trails the linked banner's resolved end by a flat 4 days) — and is independent of `start_date`. See `getThroughoutCaratsInWindow` in `frontend/src/utils/incomeCalculationUtils.ts`.

---

## Pull Costs

After recording the forecast for a banner, the projection deducts the pull cost:

| Banner type | Ticket used first | Carat cost per remaining pull |
|---|---|---|
| Uma banner | Uma tickets | 150 carats |
| Support banner | Support tickets | 150 carats |

Free pulls granted by the banner (`free_pulls`) are subtracted from `number_of_pulls` before any cost is calculated.
