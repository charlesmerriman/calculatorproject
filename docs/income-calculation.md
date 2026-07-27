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

## Misc Earnings Approximation (monthly, toggle — on by default)

A flat **1,800 carats/month** approximating miscellaneous earnings the projection doesn't
model individually — gifts, Team Trials extras, and career-mode rewards. This mirrors the
source sheet's "Misc Earnings" figure, which the projection is calibrated against.

Gated behind the user's `misc_earnings` boolean (`CustomUser.misc_earnings`,
`default=True`). Credited on month boundaries, the same mechanism as Club Rank (the
projection counts how many 1st-of-month boundaries fall in the window). Constant:
`MISC_EARNINGS_PER_MONTH` in `frontend/src/constants/gameConstants.ts`.

---

## Monthly Shop Tickets (monthly, opt-in — off by default)

Each month the in-game shop lets you buy **3 uma tickets** and **4 support tickets** with a
currency the calculator doesn't track, so when enabled these are credited as pure ticket
income at **no carat cost**. Gated behind `CustomUser.monthly_shop_tickets` (`default=False`).
Credited on month boundaries, the same mechanism as Club Rank. Constants
`MONTHLY_SHOP_UMA_TICKETS` / `MONTHLY_SHOP_SUPPORT_TICKETS` in
`frontend/src/constants/gameConstants.ts`.

---

## 50-Day Login Bonus (monthly, always on)

A flat **~170 carats/month** from the game's recurring 50-day login campaign. This is
universal income (like the base daily carats), so there is **no toggle** — it always
applies. Credited on month boundaries. Constant: `FIFTY_DAY_LOGIN_PER_MONTH` in
`frontend/src/constants/gameConstants.ts` (approximate; tune there).

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

Paid once per Champions Meeting event. The projection adds this payout for each `ChampionsMeeting` whose `end_date` falls within the window. Placements grant both carats and pull tickets; the in-game pull-ticket reward is split evenly between uma and support tickets.

| Placement | Carats | Uma tickets | Support tickets |
|---|---|---|---|
| Champion | 3,300 | 5 | 5 |
| Second | 2,400 | 4 | 4 |
| Group B 1st | 1,800 | 3 | 3 |
| Third | 1,600 | 3 | 3 |
| Open League 1st | 1,500 | 3 | 3 |
| Group B 2nd | 1,250 | 2 | 2 |
| Open League 2nd | 1,250 | 2 | 2 |
| Group B 3rd | 1,000 | 1 | 1 |
| Open League 3rd | 1,000 | 1 | 1 |

---

## League of Heroes Rank (per event)

Paid once per League of Heroes event. The projection adds this payout for each `LeagueOfHeroes` whose `end_date` falls within the window. Ranks grant both carats and pull tickets; the in-game pull-ticket reward is split evenly between uma and support tickets.

| Rank | Carats | Uma tickets | Support tickets |
|---|---|---|---|
| Silver 4 | 400 | 0 | 0 |
| Gold 1 | 550 | 0 | 0 |
| Gold 2 | 700 | 1 | 1 |
| Gold 3 | 1,000 | 1 | 1 |
| Gold 4 | 1,300 | 2 | 2 |
| Platinum 1 | 1,800 | 2 | 2 |
| Platinum 2 | 2,300 | 2 | 2 |
| Platinum 3 | 2,800 | 2 | 2 |
| Platinum 4 | 3,300 | 2 | 2 |

---

## Event Rewards

Each `GameEvent` carries its own reward amounts directly (no separate reward model): `carat_amount`, `carats_throughout`, `uma_ticket_amount`, `support_ticket_amount`, `sr_shard_amount` / `sr_crystal_amount`, `ssr_shard_amount` / `ssr_crystal_amount`. These fall into two categories:

- **Immediate (`carat_amount` + all ticket/shard/crystal amounts)**: earned in full as soon as the event's own resolved `start_date` passes. The projection adds these if `start_date` falls strictly after the previous banner's end date and on or before the current banner's end date, same rule as the other date-gated income sources.
- **Throughout (`carats_throughout`)**: carats only, front-loaded across the event's own `start_date`..`end_date` span rather than granted in one lump or spread at a flat rate. More of the pool is earned early in the event's life, tapering off toward `end_date` (where it reaches exactly 100% earned, with no early cutoff — the event's `end_date` already trails the linked banner's resolved end by a flat 4 days, and that whole span earns continuously through to the last day). The decay curve blends a fast exponential leg with a slower linear leg; see `remainingShare` and `getThroughoutCaratsInWindow` in `frontend/src/utils/incomeCalculationUtils.ts` for the exact formula. Independent of `start_date`.

---

## Pull Costs

After recording the forecast for a banner, the projection deducts the pull cost. Carats are
tracked as two separate balances: **free carats** (`current_carat`, which receive all
income) and **paid carats** (`current_paid_carat`, purchased with money — they never grow).
The spend order for a banner's `number_of_pulls`, after subtracting the banner's `free_pulls`,
is:

1. **Matching tickets** — uma tickets for an uma banner, support tickets for a support banner.
2. **Discounted paid pulls** *(if `discounted_paid_pulls` on)* — a once-per-day option to
   spend **50 paid carats** instead of 150 for a single pull. Capped at one pull per active
   day of the banner's window and by the paid-carat balance (paid-carats only; the discount
   stops the moment they run out).
3. **Free carats** — 150 per pull.
4. **Full-price paid carats** *(if `full_price_paid_pulls` on, default)* — 150 per pull. When
   this toggle is off, paid carats are held in reserve and never spent at full price.

Free carats are spent before full-price paid carats so more daily discounts stay available
for later banners. Full-price pulls treat free + (enabled) paid carats as one fungible
150-carat pool. Any pulls that still can't be paid for become a negative free-carat balance,
signalling an unaffordable plan (which cascades to later banners). See
`applyPullStrategy` in `frontend/src/utils/bannerHelpers.ts`, which also computes the
banner's "Max Pulls" figure from the same strategy.

Constants: `PULL_COST_CARATS` (150) and `DISCOUNTED_PULL_COST_CARATS` (50) in
`frontend/src/constants/gameConstants.ts`. Toggles live on `CustomUser`
(`discounted_paid_pulls` `default=False`, `full_price_paid_pulls` `default=True`).
