# 06 — Milestone calendar

Times in CET/CEST (Stockholm). Machine-readable version: [`plan/calendar.yaml`](../plan/calendar.yaml) — the planner reads that file. `[B]` Blizzard-confirmed, `[R]` reported, `[H]` our hypothesis.

## Dates

| Date | Event | Source |
|---|---|---|
| until 2026-10-22 (Oct 21 PST) | Beta ends, cap 30, AH open on US beta houses | [B] |
| 2026-10-27 → 11-03 | Early name reservation (any upgrade pack, up to 3 chars) | [B] |
| **2026-11-05 00:00 CET** | **Launch** (Nov 4 15:00 PST). Cap 60. EU AHs open | [B] |
| 2026-11-04 → 11-11 | Invite-A-Friend week (extra players, extra demand) | [R] |
| **2026-12-09** | **Raids unlock**: Barrow Deeps (10), Hyjal Summit (20), Onyxia's Lair (40) | [B] |
| Winter 2026/27 | Hardcore ruleset launches (own AH = fresh market) | [B] date TBD |
| Spring 2027 | 2 raids (10/20), 2 dungeons, legendary questline, PvP refresh | [B] date TBD |
| Summer 2027 | Revamped classic raid + new raid, 2 dungeons, profession + Legacy updates | [B] date TBD |

## What to do when

### Now → beta end (Oct 11–22)
- Run test plan T1–T6 ([07](07-test-plan.md)). Most important: scanner works, SavedVariables size OK, commodity question answered.
- Collect beta prices from AHledger as practice data (not representative — beta prices swing 700 %+).
- Build reference tables: vendor prices, Black Market stock, recipes seen in beta.

### Pre-launch (Oct 22 – Nov 4)
- Pipeline: hourly AHledger pull scheduled; dashboard skeleton running on beta data.
- Choose house (ruleset + faction). Plan professions: one gathering + one crafting early (gathering pays from minute one).
- Name reservation window: reserve main + bank alt.

### Launch week (Nov 5–11) — "sell to levelers"
- Sell all raw cloth/ore/herbs/leather as you level; short durations.
- Don't buy except for own leveling needs. Target: level 40 mount (~120g [R]).
- Scan every time you pass an AH — these launch curves are gold for later (Hardcore).

### Weeks 2–4 (Nov 12 – Dec 1) — "levelers → 60"
- Low-tier mats deflating; stop farming them, switch to mid/high tier.
- Buy endgame mats levelers dump below 30-day p25 (Swiftthistle, Small Flame Sac, Golden Pearl, fire resistance mats, Arcane Crystal < 50g).
- Start cooldown crafts as soon as available.

### Pre-raid window (Dec 1 – Dec 8) — "stock the raiders"
- Craft/buy flasks, elixirs, potions, food, enchants, BoE pre-raid gear ahead of demand.
- Watch datamining / patch notes for raid mechanics needing resistances or specific consumables — adjust watchlist.
- Sell into the hype before Dec 9; keep stock for the first raid weeks.

### Raid economy (Dec 9 →)
- Weekly cycle: buy Thu–Mon, sell Tue–Wed (EU reset Wednesday [H] — confirm for Forever).
- Track one-off demand (attunements, Onyxia) vs recurring demand (consumables).
- Holidays Dec 19 – Jan 6: more playtime → more demand; possibly more supply too [H].

### Hardcore launch (TBD)
- Replay launch-week playbook on a fresh AH using our own launch curves as forecast.

### Each content update (spring/summer 2027)
- On announcement: tag affected items in `calendar.yaml`, start pre-event drift tracking.
- Sell ~50 % into announcement hype, rest before launch day. Avoid big hoards of tunable supply (herbs, vendor-capped mats).

## Recurring cadence (built into the planner)

| Cadence | Task |
|---|---|
| Every AH visit | Scan (auto, throttled 15 min) |
| Daily | Open dashboard → today's plan: buy list, sell list, craft list, cancel/repost list, cooldowns |
| Weekly (Tue) | Weekly review: P&L per strategy, stock levels vs targets, next-week events |
| Per phase | Update `calendar.yaml` + watchlist; review what worked last phase |
