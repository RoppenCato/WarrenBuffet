# 07 — Test plan: can we pull data automatically?

Status legend: ✅ pass · ❌ fail · ⏳ todo · ⚠️ partial

| # | Test | Where | Status |
|---|---|---|---|
| T1 | AHledger API reachable, schema as documented | Web | ✅ 2026-10-11 |
| T1b | Pricetable fields match docs | Python | ⏳ |
| T2 | Blizzard Game Data API has Forever auctions | Web | ⏳ (at launch) |
| T3 | `ReplicateItems` full scan works in Forever client | Beta | ✅ 2026-10-11 |
| T4 | SavedVariables size, write on logout, Python parse | Beta | ✅ 2026-10-11 |
| T5 | Commodities included in replicate? AH type? | Beta | ✅ 2026-10-11 — included; neutral cut and deposit formula still open |
| T6 | Ledger captures post/sold/bought/expired | Beta | ⚠️ 2026-10-11 — post, bought, cancelled seen; two bugs fixed, re-run needed; sold/expired not seen yet |
| T7 | Own scan vs AHledger agree on same hour | Beta/launch | ⚠️ 2026-10-11 — close, but scans were 4 h apart |
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

## Beta run sheet (T3–T6)

First beta run: 2026-10-11, build 1.60.1.70338 (Interface 16001), realm "Classic Beta PvE", Horde, Undercity. Results are under each test. The fixes made after that run (addon v0.2) have only run offline.

Setup, once:
1. Copy `addon\ForeverAH` to `World of Warcraft\_classic_beta_\Interface\AddOns\ForeverAH\`.
2. At character select, AddOns: ForeverAH must be listed and enabled. If it says out of date, tick "Load out of date AddOns" and send the number from `/dump select(4, GetBuildInfo())`.
3. In game: `/console scriptErrors 1` (show Lua errors), then `/fah` — prints client build and any events this client doesn't have.

Send back: the `ForeverAH` chat lines (or screenshots), any Lua error text, and the output of
`python -m pipeline.savedvars "<WoW>\_classic_beta_\WTF\Account\<ACCOUNT>\SavedVariables\ForeverAH.lua"` after a `/reload`.

## T3 — In-game scan (beta)

Minimal test addon: on `AUCTION_HOUSE_SHOW`, call `ReplicateItems`, count rows, print timing.
Measure: rows vs AHledger auction count for the same house; seconds to process; frame drops; `hasAllInfo=false` share; behaviour when throttled (expect `n == 0`).
- Pass: ≥ 95 % of AHledger's auction count, no disconnect, < 30 s processing.

Run:
1. Open the AH and keep it open. Expect `requesting full scan`, then `scan saved: N rows …` with wait/process seconds, slowest frame, `hasAllInfo` misses and time-left bands.
2. Same minute: note `auctions` from `https://api.ahledger.com/v1/economy/<market>` for the same house (beta realm "Classic Beta PvE" → `forever.normal.<faction>.us`).
3. Within 15 min, type `/fah scan`. Expected `scan not saved: 0 rows - throttled`. If it says `scan saved` with the same row count instead, the client replays the old list — tell me, the scanner needs a guard.
4. After 15 min, close and reopen the AH: a second scan should run on its own.

Result 2026-10-11 — **pass**:
- 79,437 rows saved of 79,437 reported, 3,061 items, 550,299 units. AHledger's newest scan of the same house (`forever.normal.horde.us`, 4 h earlier): 79,452 auctions, 3,011 items, 496,036 units → 99.98 % of their auction count. Source: [AHledger](https://ahledger.com).
- Wait for the reply 13.0 s, processing 1.1 s over 23 frames, slowest frame 50 ms. No disconnect.
- `hasAllInfo` false on 7,696 rows (9.7 %); itemID, count and buyout were present on all of them, 0 rows skipped.
- Throttled request (`/fah scan` a few minutes later): **no reply at all** — no event, not an empty list. The 120 s timeout reported it. Docs/03 expected `n == 0`.
- `GetReplicateItemTimeLeft` works: bands 1–4 on every row (1: 3,534 · 2: 10,592 · 3: 47,457 · 4: 17,854).
- A Lua error followed every scan (`GetItemCommodityStatus` takes an ItemLocation, not an item id). The scan was already saved; fixed in v0.2.
- Open: step 4 (does the next automatic scan run 15 min after a successful one, and does a throttled attempt restart the server's timer?).

## T4 — SavedVariables

Save one raw scan as compact strings + aggregates; `/reload`; measure file size; parse with `slpp`/`lupa` in Python; time the parse.
- Pass: < 10 MB per raw scan, parse < 10 s.

Simulated 2026-10-11 (stub, random data, not the real client): 150k auctions / 6k items → 3.8 MB raw + 0.25 MB aggregates per scan, parse 0.02 s; 88k auctions → 2.2 MB raw. Aggregates recomputed in Python from the raw rows match the addon's.

Run: after T3 step 1, `/reload`, then run `pipeline.savedvars` (command above). It prints file size, parse time, per-scan stats and whether the aggregates match the raw rows.

Result 2026-10-11 — **pass**: file written on `/reload`, 1.4 MB for one scan (1.3 MB raw for 79k rows — a third of the estimate in docs/04), parsed in 0.01 s, aggregates recomputed in Python match the addon's. The 6th raw field added in v0.2 adds about 0.2 MB per scan.

## T5 — Commodities / AH type

Compare replicate results for a stackable (Linen Cloth 2589, Copper Ore 2770) against what the AH UI shows and AHledger's quantity.
- If stackables are missing → AH is retail-style for commodities → add per-item `SendSearchQuery` scanning for watchlist commodities (rate-limited, slower).
- Also note: listing durations (12/24/48h?), deposit formula, neutral AH cut.

Run:
1. After each scan the addon prints one line each for 2589 and 2770: auctions, units, min, median — or `NOT in scan`. `commodity status` is `C_AuctionHouse.GetItemCommodityStatus`: 1 = item, 2 = commodity.
2. Search the same two items in the AH UI and compare cheapest price and rough quantity. Compare with AHledger `/v1/prices/<market>/2589`.
3. `/fah item <id>` for anything else. Note whether the sell tab asks for a stack size (classic style) or a quantity + unit price (retail style), and which durations it offers.

Result 2026-10-11 — **stackables are in the replicate results**; no per-item `SendSearchQuery` scanning needed:
- Linen Cloth 2589: 597 rows, 14,159 units, min 19, median 27. Copper Ore 2770: 141 rows, 7,849 units, min 100, median 150.
- AHledger, same house 4 h earlier: Linen 491 auctions, 12,749 units, min 20, median 30; Copper Ore 148 auctions, 7,885 units, min 135, median 150. Source: [AHledger](https://ahledger.com).
- AH type: **retail-style**. The sell tab takes a quantity and a buyout price per item; our Linen and potion posts went through `PostCommodity`. Rows are one seller's quantity at one unit price (up to 10,000 units in a row); `buyout` in the replicate row is unit price × count on all 79k rows.
- Bids barely exist: 1 row of 79,437 had a bid, 1 had no buyout, `minBid` was 0 on every row.
- Durations: **2 h / 8 h / 24 h** (codes 1 / 2 / 3), not 12/24/48.
- Deposit, two data points: 1 potion at 10c for 8 h → 0c; 13 Linen at 18c for 2 h → 8c. Formula still open.
- Not tested: neutral AH cut.

## T6 — Ledger

Post 1 cheap item, buy 1 cheap item, let 1 expire, cancel 1. Check events/mail invoice data captured with correct prices and fees.

Run:
1. Post one item at 12 h, post and cancel another, buy one cheap item. Each should print a `ledger: …` line (`post` with item, qty, price, duration, deposit; `cancel`; `bid`/`buy_*`).
2. Open the mailbox: expect `bought` and `cancelled` rows. Open it again — no duplicate rows.
3. Next day: `expired` for the unsold item, `sold` (and earlier `sold_pending`) if one sold. Check `total`, `fee`, `dep` against the mail.
4. `/fah` lists events that failed to register — those names are wrong for this client.

Result 2026-10-11 — **partial**:
- All events registered (none missing in this client).
- `post`: correct for both posts — auction id, item, quantity, unit price, duration code, deposit.
- `bought` mail: Elixir of Minor Defense, qty 1, total 5c, with itemID. `cancelled` mail: Linen Cloth, itemID 2589, qty 13.
- Bug: the `cancelled` mail was logged twice, 3 s apart. `daysLeft` from the inbox is a snapshot from the last refresh, not a countdown, so the computed expiry drifted. Fixed in v0.2 (D17); the beta sequence is now an offline test.
- `AUCTION_CANCELED` does not carry the auction id: it gave 114 for the Linen cancel, 0 at the purchase, and fired once 13 s after the AH opened. v0.2 takes the cancel from the `CancelAuction` click instead.
- The purchase produced `AUCTION_HOUSE_PURCHASE_COMPLETED` with 0 only — no `COMMODITY_PURCHASED`, no `PlaceBid`. v0.2 logs the `ConfirmCommoditiesPurchase` click.
- Not seen yet: `sold`, `sold_pending`, `expired`, `outbid`. The potion posted for 8 h will give `sold` or `expired`.
- Re-run needed for the v0.2 changes (cancel row, commodity buy row, no duplicate mail).

## T7 — Cross-source agreement

Same item, same hour: own scan min/median vs AHledger. Expect min within 5 %, median within 10 %. Large deviations → investigate (different houses? stale data?).

Result 2026-10-11 — **partial** (own scan 09:36 UTC, AHledger's newest 05:26 UTC, so not the same hour): Linen min 19 vs 20, median 27 vs 30; Copper Ore min 100 vs 135, median 150 vs 150. Auction counts within 0.02 %. Repeat when the two scans fall in the same hour. Source: [AHledger](https://ahledger.com).

## T8 — Unattended pull

Task Scheduler hourly → `pipeline pull ahledger`; 48h; check no gaps in our L1, respect for rate limits and cache headers.
