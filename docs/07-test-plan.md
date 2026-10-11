# 07 — Test plan: can we pull data automatically?

Status legend: ✅ pass · ❌ fail · ⏳ todo · ⚠️ partial

| # | Test | Where | Status |
|---|---|---|---|
| T1 | AHledger API reachable, schema as documented | Web | ✅ 2026-10-11 |
| T1b | Pricetable fields match docs | Python | ⏳ |
| T2 | Blizzard Game Data API has Forever auctions | Web | ⏳ (at launch) |
| T3 | `ReplicateItems` full scan works in Forever client | Beta | ⏳ before Oct 22 |
| T4 | SavedVariables size, write on logout, Python parse | Beta | ⏳ |
| T5 | Commodities included in replicate? AH type? | Beta | ⏳ |
| T6 | Ledger captures post/sold/bought/expired | Beta | ⏳ |
| T7 | Own scan vs AHledger agree on same hour | Beta/launch | ⏳ |
| T8 | Scheduled hourly pull runs unattended for 48h | PC | ⏳ |

## T1 — AHledger API ✅

Run 2026-10-11 (beta data).

- `GET /v1/markets` → 14 markets: 12 Forever (`forever.{normal,pvp,rp}.{alliance,horde}.{us,eu}`) + 2 retail. Fields: `id, game, ruleset, faction, region, label`. No open/last-scan flag.
- `GET /v1/prices/forever.pvp.horde.us/2589?range=7d` (Linen Cloth) → `latest {observedAt, source:"Addon scan", minBuyout:15, median:18, quantity:9372, auctions:404, median7d, median30d, median90d}`; `series` of 100 points `{t, min, median, p25, p75, quantity, auctions}`; `sales {estimatedPerDay, windowDays:7, coveredHours:37}`; `attribution {text, url, html}`.
- `GET /v1/economy/forever.pvp.horde.us` → latest 88,212 auctions, 533,590 units, 3,127 distinct items; daily array with `{day, value, auctions, units, scans}` (7 scans that day).
- `GET /v1/pricetable/forever.pvp.horde.us` → header `AHL1|forever/pvp/horde/us|<unix>|3097`, ~3.1k rows, ~130 KB.
- From the cloud workspace, `curl` to the API was blocked by the sandbox proxy — irrelevant for the home PC, but re-test there (T8).

**Finding:** coverage is irregular — 37 covered hours of 168 in the 7-day window, gaps up to ~9h. Confirms: AHledger fills gaps, can't be the only source.

## T2 — Blizzard API (at launch)

1. Create client at develop.battle.net → client credentials token (`POST https://oauth.battle.net/token`).
2. Try `GET https://eu.api.blizzard.com/data/wow/connected-realm/index` with namespaces `dynamic-eu`, `dynamic-classic-eu`, `dynamic-classic1x-eu`, and anything new (search the API forum / changelog for "Forever").
3. Look for Forever realms; if found, `.../connected-realm/{id}/auctions/index` and `.../auctions/{ahId}`.
- Pass: hourly snapshot with item, quantity, buyout/unit_price, time_left for our house.
- Fail: rely on own scans + AHledger. Re-check monthly.

## T3 — In-game scan (beta)

Minimal test addon: on `AUCTION_HOUSE_SHOW`, call `ReplicateItems`, count rows, print timing.
Measure: rows vs AHledger auction count for the same house; seconds to process; frame drops; `hasAllInfo=false` share; behaviour when throttled (expect `n == 0`).
- Pass: ≥ 95 % of AHledger's auction count, no disconnect, < 30 s processing.

## T4 — SavedVariables

Save one raw scan as compact strings + aggregates; `/reload`; measure file size; parse with `slpp`/`lupa` in Python; time the parse.
- Pass: < 10 MB per raw scan, parse < 10 s.

## T5 — Commodities / AH type

Compare replicate results for a stackable (Linen Cloth 2589, Copper Ore 2770) against what the AH UI shows and AHledger's quantity.
- If stackables are missing → AH is retail-style for commodities → add per-item `SendSearchQuery` scanning for watchlist commodities (rate-limited, slower).
- Also note: listing durations (12/24/48h?), deposit formula, neutral AH cut.

## T6 — Ledger

Post 1 cheap item, buy 1 cheap item, let 1 expire, cancel 1. Check events/mail invoice data captured with correct prices and fees.

## T7 — Cross-source agreement

Same item, same hour: own scan min/median vs AHledger. Expect min within 5 %, median within 10 %. Large deviations → investigate (different houses? stale data?).

## T8 — Unattended pull

Task Scheduler hourly → `pipeline pull ahledger`; 48h; check no gaps in our L1, respect for rate limits and cache headers.
