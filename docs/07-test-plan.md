# 07 — Test plan: can we pull data automatically?

Status legend: ✅ pass · ❌ fail · ⏳ todo · ⚠️ partial

| # | Test | Where | Status |
|---|---|---|---|
| T1 | AHledger API reachable, schema as documented | Web | ✅ 2026-10-11 |
| T1b | Pricetable fields match docs | Python | ✅ 2026-10-11 |
| T2 | Blizzard Game Data API has Forever auctions | Web | ⏳ (at launch) |
| T3 | `ReplicateItems` full scan works in Forever client | Beta | ✅ 2026-10-11 |
| T4 | SavedVariables size, write on logout, Python parse | Beta | ✅ 2026-10-11 |
| T5 | Commodities included in replicate? AH type? | Beta | ✅ 2026-10-11 — included; deposit is at least 1s per post; neutral cut still open |
| T6 | Ledger captures post/sold/bought/expired | Beta | ⚠️ 2026-10-12 — post, cancel, bought, cancelled, expired and the money rows correct; only `sold` not seen yet |
| T7 | Own scan vs AHledger agree on same hour | Beta/launch | ✅ 2026-10-11 — medians within 2 %, mins within 1 copper, 6 min apart |
| T8 | Scheduled hourly pull runs unattended for 48h | PC | ⏳ — scheduled 2026-10-11 18:21, first run ok; check the log on 2026-10-13 evening |
| T9 | Inventory and own-auctions snapshot | Beta | ⚠️ 2026-10-12 — bags correct, bank read (it was empty), query does not disturb the scan; a live auction still not captured (fixed in v0.10.1, untested) |
| T10 | Log window, button, several characters | Beta | ✅ 2026-10-12 for the window and minimap button (user: "window works nice"); second character not tested |
| T15 | Vendor prices recorded at the vendor | Beta | ✅ 2026-10-12 — 131 items from six vendors, Coarse Thread 10c |
| T13 | Recipes read from the profession window | Beta | ✅ 2026-10-12 — Tailoring and Enchanting saved, 5 recipes each, materials and outputs right |
| T14 | Disenchant results logged | Beta | ✅ 2026-10-12 — Copper Chain Belt → 1 Strange Dust, with quality and level |
| T12 | In-game plan and tooltip lines | Beta | ✅ 2026-10-12 — the user sees the Plan tab and the three tooltip lines |
| T11 | Item reference: names and vendor prices | Beta | ✅ 2026-10-12 — 3,167 items after two scans with the repeat pass (the last scan had 3,102) |
| T16 | Another addon's full scan is saved too | Beta | ⏳ — optional, needs a second scanning addon installed |
| T17 | Recipe colour saved; cheapest skill points | Beta | ⏳ — open both profession windows once with v0.11 |

## T1 — AHledger API ✅

Run 2026-10-11 (beta data).

- `GET /v1/markets` → 14 markets: 12 Forever (`forever.{normal,pvp,rp}.{alliance,horde}.{us,eu}`) + 2 retail. Fields: `id, game, ruleset, faction, region, label`. No open/last-scan flag.
- `GET /v1/prices/forever.pvp.horde.us/2589?range=7d` (Linen Cloth) → `latest {observedAt, source:"Addon scan", minBuyout:15, median:18, quantity:9372, auctions:404, median7d, median30d, median90d}`; `series` of 100 points `{t, min, median, p25, p75, quantity, auctions}`; `sales {estimatedPerDay, windowDays:7, coveredHours:37}`; `attribution {text, url, html}`.
- `GET /v1/economy/forever.pvp.horde.us` → latest 88,212 auctions, 533,590 units, 3,127 distinct items; daily array with `{day, value, auctions, units, scans}` (7 scans that day).
- `GET /v1/pricetable/forever.pvp.horde.us` → header `AHL1|forever/pvp/horde/us|<unix>|3097`, ~3.1k rows, ~130 KB.
- From the cloud workspace, `curl` to the API was blocked by the sandbox proxy — irrelevant for the home PC, but re-test there (T8).

**Finding:** coverage is irregular — 37 covered hours of 168 in the 7-day window, gaps up to ~9h. Confirms: AHledger fills gaps, can't be the only source.

## T1b — Pricetable fields ✅

Run 2026-10-11 on `forever.normal.horde.us`, Linen Cloth 2589 and Copper Ore 2770, pricetable against `/v1/prices/…?range=30d` fetched in the same minute. Source: [AHledger](https://ahledger.com).

- `median`, `minBuyout`, `quantity`, `median7d`, `median30d` equal `latest` in the price endpoint.
- `soldPerDay×10` equals `sales.estimatedPerDay` × 10 (150794 ↔ 15,079.4; 88349 ↔ 8,834.9).
- `low30d` is the lowest daily `min` in the 30-day series, `high30d` the highest daily `median`.
- Lines can be short (trailing fields missing) or have empty fields; the parser returns `None` for those.
- `Cache-Control: max-age=60`; rate limit header says 300 per minute.

## T2 — Blizzard API (at launch)

1. Create client at develop.battle.net → client credentials token (`POST https://oauth.battle.net/token`).
2. Try `GET https://eu.api.blizzard.com/data/wow/connected-realm/index` with namespaces `dynamic-eu`, `dynamic-classic-eu`, `dynamic-classic1x-eu`, and anything new (search the API forum / changelog for "Forever").
3. Look for Forever realms; if found, `.../connected-realm/{id}/auctions/index` and `.../auctions/{ahId}`.
- Pass: hourly snapshot with item, quantity, buyout/unit_price, time_left for our house.
- Fail: rely on own scans + AHledger. Re-check monthly.

## Beta run sheet (T3–T6)

First beta run: 2026-10-11, build 1.60.1.70338 (Interface 16001), realm "Classic Beta PvE", Horde, Undercity. Results are under each test. The fixes made after that run (addon v0.2) have only run offline.

Combined run for the open items (2026-10-11, v0.6): `/reload` → `/fah` → open the bank → open the mailbox and take everything → open the AH, wait for the scan, post one stack of two or more units → `/reload`. That covers T6 (sold/expired mail, money rows), T9, the first half of T10, and T11.

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
- Run 2 (16:41, v0.2): the scan started by itself on opening the AH and finished with no error — 84,070 rows of 84,070, wait 21.3 s, processing 1.2 s, slowest frame 50 ms, rows saved with the 6th field. `AUCTION_CANCELED` fired 28 times in the second the reply arrived, with auction ids that are not ours.
- Open: does a throttled attempt restart the server's 15 min? (Run 2 was 5 h later, so it doesn't say.)

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
- Deposit: **1s was charged for each of three posts**, shown by the gold balance (339c → 134c = two posts + a 5c purchase; 134c → 19c = one post + a 15c purchase). `CalculateCommodityDeposit` had said 0c, 8c and 0c, so the API estimate is not what is charged — a 1s minimum fits all three. Cancelling did not give it back. Whether a sale refunds it is still open.
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

Run 2, 2026-10-11 16:41 (v0.2) — the fixes hold:
- `post` Linen ×1 at 17c → `cancel` with the same auction id (54678655) and cost 0. The join works.
- `buy_commodity` Linen ×1, unit 15, total 15 → `buy_done` one second later → `bought` mail with total 15. All three agree.
- One `bought` and one `cancelled` mail row, no duplicates.
- `gold` at logout was 0 when the game was quit (correct on `/reload`). Fixed in v0.3: the last balance seen is logged.
- v0.3 adds `money` rows (every balance change while the AH or mailbox is open) because the deposit estimate was wrong, and stops logging `AUCTION_CANCELED`. Untested in game.
- Still not seen: `sold`, `sold_pending`, `expired`, `outbid`. The potion posted at 11:40 for 8 h ends at 19:40.

## T7 — Cross-source agreement

Same item, same hour: own scan min/median vs AHledger. Expect min within 5 %, median within 10 %. Large deviations → investigate (different houses? stale data?).

Result 2026-10-11, run 1 — partial (own scan 09:36 UTC, AHledger's newest 05:26 UTC, so not the same hour): Linen min 19 vs 20, median 27 vs 30; Copper Ore min 100 vs 135, median 150 vs 150. Auction counts within 0.02 %. Source: [AHledger](https://ahledger.com).

Result 2026-10-11, run 2 — **pass** (own scan 14:41 UTC, AHledger 14:35 UTC). Source: [AHledger](https://ahledger.com).

| | Own scan | AHledger |
|---|---|---|
| Auctions in house | 84,070 | 83,139 |
| Linen Cloth min / median | 17 / 25 | 18 / 25 |
| Linen Cloth units / auctions | 15,138 / 587 | 12,812 / 489 |
| Copper Ore min / median | 141 / 148 | 141 / 145 |
| Copper Ore units / auctions | 2,202 / 119 | 2,035 / 116 |

Across the whole house: 2,983 items appear in both scans, and 98 % of them have medians within 10 % of each other (97 % among the 473 items selling 50+ a day).

Medians are within 2 %. Linen's min differs by 1 copper, which is 5.6 % at this price — the 5 % rule needs an absolute floor for cheap items. Linen quantity differs by 18 %; AHledger's hourly point an hour earlier (15,140 units) matches ours, so this looks like timing or their filtering, not a scan gap.

## Run 3 — 2026-10-11 22:29, addon v0.6

The user opened the AH (scan) and emptied the mailbox, then reloaded. Read from the SavedVariables file:

- **No errors:** `errors` empty, no `uiErr`, no inventory `err`, no events missing, no `?` rows.
- **T3:** third scan, 96,635 rows of 96,635, wait 28.5 s, processing 1.4 s, slowest frame 58 ms. The wait grows with the house (13 s at 79k, 21 s at 84k, 28.5 s at 97k) — the 30 s line in T3 will be crossed at launch size; the addon waits up to 120 s.
- **T6:** first `expired` row — Minor Healing Potion ×1, itemID from the attachment. The balance stayed at 19c, so the 1s deposit is not returned on expiry. `gold` rows at login and logout are right (19c, no zero).
- **T9:** bags saved as Linen Cloth 14, Refreshing Spring Water 19, Minor Healing Potion 1, Elixir of Minor Defense 1 — which matches the ledger (13 Linen cancelled back + 1 bought, the expired potion, the bought elixir). The own-auctions query ran two seconds after the AH opened, returned an empty list, and the scan still completed. Not tested: the bank (never opened) and a live auction, so whether the saved price is per unit or per stack is still open.
- **T10:** the window was built from plain frames without error; the button was dragged and its position saved (`TOP 691, -141`); the window state was saved. Whether chat stayed clean has to come from the user.
- **T11:** 937 of 3,128 scanned items got a reference line (30 %): the pass ran right after the scan, while the client was still loading item data. Values look right — Linen Cloth 13c, Copper Ore 5c, Minor Healing Potion 5c, stack sizes 20/20/5 — but none was checked at an in-game vendor. v0.6.1 repeats the pass 20 s later and when the AH closes.
- With real vendor prices the launch-week preview finds listings under vendor price: crafted leather gear a few copper below (Dark Leather Cloak, 242 units at 4s 00c against 4s 08c). Real, but small — 19s on 9g 68s.

Still open before Oct 22: one more scan with v0.6.1 (item coverage), one post of a stack of two or more (money rows, own-auction price), the bank opened once.

User feedback on run 3: it worked, but the window was behind the auction house window; a minimap button and a nicer look were asked for. That is UI v0.7 (D35), offline-tested only. To check in game: the coin button sits on the minimap and can be dragged around it; the window opens beside the AH, in front of it, with a border and a status line; ledger lines read as sentences; `uiNote` and `uiErr` are absent from the file.

## Run 4 — 2026-10-12 19:09–19:15, addon v0.10

The user, now with Tailoring and Enchanting, ran the list: Plan tab and tooltips, both profession windows, one disenchant, the bank, a scan and a post. Read from the file, plus what the user reported:

- **No errors:** `errors` empty, no `uiErr`, no `uiNote` (the bordered window and the minimap button were built with their templates), no events missing.
- **T12:** the user sees the Plan tab and the tooltip lines.
- **T10:** "Window works nice." It had been dragged; position and tab were saved.
- **T14:** one disenchant logged — Copper Chain Belt (quality 2, item level 11, armour) gave 1 Strange Dust. The Classic spell id is right.
- **T15:** 131 vendor items, e.g. Coarse Thread 10c from Millie Gregorian in Undercity. No limited-stock item seen yet.
- **T11:** 3,167 items in the reference, all with quality and level.
- **T6:** the money rows work: −1s for the belt bought at the AH, −1s for a post of 2 Linen at 18c for 2 h. The addon's deposit estimate for that post was 1c — a fourth post that cost exactly 1s. The bought mail and the bid row agree at 1s.
- **T9:** the bank was read (`bankTs` set) and held nothing sellable. The stack posted 13 s before `/reload` was **not** in the auctions snapshot. First read as a stale list (v0.10.1 asks again after each new auction, which is still right to do), but the user later said the Linen sold the moment it was posted — so there was most likely nothing left to list. Unit-or-stack price still open; it needs an auction that stays up.
- **T3:** 75,834 rows, 19.3 s wait.
- **T13 failed quietly:** nothing under `recipes`, no error. The modern reader returns without a word when the profession has no name, the recipe list is empty, or nothing is marked learned — so the cause is unknown. v0.10.1 writes what each API answered to `probe.recipes`, tries the Classic trade skill and craft APIs too, reads at once as well as a second later, and has `/fah recipes` to read on demand.

Next: `/reload`, open the Tailoring window, type `/fah recipes` while it is open, then the same for Enchanting, `/reload`.

## Run 5 — 2026-10-12 19:22, addon v0.10.1

The probe answered the recipe question: `modern: profession= id=0 recipes=261 learned=5 | classic: no API | craft: no API`, and the events `TRADE_SKILL_UPDATE`, `CRAFT_SHOW`, `CRAFT_UPDATE` do not exist in this client.

- Forever uses the **Mainline profession API**; the Classic trade skill and craft APIs are not there.
- The recipes were being read all along (261 in the list, 5 learned). They were thrown away because the profession had no name: the child-profession call answers with an empty record in Forever, and since that record is not nil the base profession was never asked.
- v0.10.2: child if it has a name, else base, else the profession of a learned recipe, else a placeholder key — recipes are saved either way. The probe keeps its last eight lines.
- Only one probe line survived (written by a timer a second before `/reload`), so whether the base call has the name is still to be seen.

## Run 6 — 2026-10-12 19:25, addon v0.10.2

- **T13 passes.** Both professions saved: Tailoring (skill 1/75) with Bolt of Linen Cloth, Linen Bag, Linen Cloak, Simple Linen Pants, Brown Linen Shirt; Enchanting (2/75) with Dust to Motes, Runed Copper Rod, two bracer enchants and Novice's Practice Wand. Materials match what Classic players know (a Linen Bag is 3 bolts and 3 Coarse Thread). Two are new in Forever: Dust to Motes (1 Strange Dust → 3 Mote of Magic) and Novice's Practice Wand.
- The probe shows the name comes from the base profession call (`Tailoring (from base) id=197`, `Enchanting … id=333`), and from a learned recipe once the window is closing.
- When the second window opened, the first event still carried the previous profession's list (471 recipes under Enchanting for a moment). The final state was right; v0.10.3 skips an attempt whose recipes belong to another profession than the window.
- With the real recipes the Craft section works end to end: Bolt of Linen Cloth from the 20 Linen held (4s 75c as bolts against 3s 23c raw), Brown Linen Shirt +1s 30c, Linen Bag +1s 05c. Coarse Thread is priced at the vendor's 10c from the vendor log, not the 15c someone lists it for.
- Finding: a vendor pays 2s for a Linen Bag that costs 1s 80c to make. The planner now treats what a vendor pays as an outlet and says so.

## T9 — Inventory and own auctions

Added 2026-10-11 with `Inventory.lua` (addon v0.4). Only run offline so far.

Run:
1. `/reload`, then `/fah` — the last lines say how many items are saved for bags, bank and own auctions.
2. Open the bank once and close it.
3. Open the AH and let the scan finish. Post one stack of **two or more** units and leave it up (this shows whether the saved price is per unit or for the stack).
4. `/reload`.

Check in the file: bags and bank counts match what is in game; soulbound items are absent; the posted stack is in `auctions` with the right quantity; no `err`; the scan still saved its rows (the own-auctions query must not disturb it).
- Pass: all of the above. Then build the dashboard — the Today page lists what is held and what is listed.

## T10 — Window and several characters

Added 2026-10-11 with `UI.lua` (addon v0.5). Only run offline so far.

Run:
1. After `/reload`: a small "FAH" button is on screen and nothing from ForeverAH appears in chat. Drag it somewhere.
2. Left-click it: the window opens and closes. `/fah` opens it with the status lines.
3. Open the AH: the window opens by itself for the scan. Close it, post something: it stays closed and the button shows a count.
4. Right-click the button (quiet mode), `/reload`: button and window are where they were left.
5. On the trading character type `/fah trader`. Log in on another character, open the AH there, `/reload`.

Check in the file: `ui` has the positions, `uiErr` and `errors` are absent or empty, `trader` is set, the ledger has rows for both characters and none for `?`, `inv` has an entry per character.

Found before the run, 2026-10-11: a new character's first session (16:57) wrote a `gold` row with character `?` and 0 copper, and its login row is missing — Core's login handler failed or never ran, which then skipped the ledger's. v0.5 resolves the name later, isolates handlers and saves errors to the file.

## T15 — Vendor log

Added 2026-10-11 with `Vendors.lua` (addon v0.10). Only run offline so far.

Run: open a trade goods vendor (one that sells thread or vials) and close it. The Log tab should say "<vendor>: N vendor prices saved". `/reload`.
- Check in the file: `vendors` has a line per item with the price shown in game, the vendor's name and the zone; a limited-stock item has its count instead of -1.
- Pass: prices match the vendor window. Then the Craft section prices thread at the vendor's price.

## T13 — Recipes

Added 2026-10-11 with `Recipes.lua` (addon v0.9). Only run offline so far.

Run, on a character with a crafting profession and a few recipes: `/reload`, open the profession window, wait two seconds, close it. The Log tab should say "<Profession>: N recipes saved for the planner". `/reload`.
- Check in the file: `recipes[char][profession]` lists the learned recipes with the right output item and materials (compare two with the game); `errors` has no `recipes` line.
- Pass: the recipes are there and right. Then Refresh the dashboard: the Craft section lists what clears its materials cost.
- If `errors` says the recipe functions are missing, this client uses another profession API and the module needs rewriting — send the line.

## T17 — Recipe colour and skill points

Added 2026-10-12 with addon v0.11 (D42). Only run offline so far.

Run: `/reload`, open each profession window for two seconds, `/reload`. Then Refresh the dashboard.
- Check in the file: each recipe line has a number before the name — 0 orange, 1 yellow, 2 green, 3 grey. Compare two with the colours in the profession window.
- Pass: the colours match, and the Today page shows "Cheapest skill points" under Craft.
- If every recipe says -1, Forever does not fill `relativeDifficulty`; the list stays hidden and the colour has to come from somewhere else.

## T16 — Shared scan

Added 2026-10-12 with addon v0.11 (D41). Only run offline so far. Optional: it needs Auctionator or CraftProfit installed next to ours.

Run: open the AH and let our scan finish. Keep the AH open for 16 minutes, then press the other addon's full-scan button.
- Pass: the Log tab says "Another addon scanned the auction house - saving its result too", then "Scan saved"; the file has a second scan with `via = "other"`, and no third one however long the AH stays open.
- Also worth one look: with both addons installed, opening the AH still gives each of them its data.

## T14 — Disenchant log

Added 2026-10-11 with `Disenchant.lua` (addon v0.9). Only run offline so far.

Run, on an enchanter: disenchant one green item and loot the result. The Log tab should say "Disenchanted <item>: <materials>". `/reload`.
- Check in the file: one `disenchants` line with the item, its quality and level, and the materials received.
- If nothing is logged: the Disenchant spell has another id in Forever. `/dump C_Spell.GetSpellInfo("Disenchant")` shows it.

## T12 — In-game plan and tooltips

Added 2026-10-11 with `Plan.lua` (addon v0.8). Only run offline so far. The plan file for the current scan is already in the installed addon.

Run: `/reload`, click the minimap button. Expect the Plan tab with a "Plan from HH:MM" line and a Sell section listing what is in the bags. Hover Linen Cloth in a bag: the tooltip should end with "AH cheapest", "Vendor pays" and "ForeverAH plan" lines. Click the Log tab and back.
- Pass: the plan shows, the tooltip lines appear, no error in `errors`, and the game loads the addon without complaining about the plan file.
- Watch for: tooltip lines missing (the hook differs in this client), or an error on login naming `ForeverAH_Plan.lua`.

## T11 — Item reference

Added 2026-10-11 with `Items.lua` (addon v0.6). Only run offline so far. Needs nothing beyond the scan in the combined run.

Check in the file after a scan and `/reload`: `items` has a line for most of the ~3,000 scanned items (the rest follow after the next scan); names are right; vendor prices match the game (hover an item at a vendor: Linen Cloth, Copper Ore); `errors` is empty.
- Pass: at least 80 % of scanned items present after two scans, spot-checked prices correct.
- Then: `python -m dashboard.build --date 2026-11-06` shows launch week mode with a real "Buy to vendor" list.

## T8 — Unattended pull

Task Scheduler hourly → `pipeline pull ahledger`; 48h; check no gaps in our L1, respect for rate limits and cache headers.

As built 2026-10-11: `python -m pipeline.pull` fetches the pricetable of every house in `plan/houses.yaml` plus the news, stores them in L1, writes one line per run to `data/pull.log`, and exits with 1 if a source failed. `tools\pull.cmd` runs it by hand.

Scheduled 2026-10-11 as the Windows task **"ForeverAH pull"** (`tools\register-pull.ps1`): 7 minutes past every hour while the user is logged on, a missed run happens on wake, 10-minute limit. It runs `pythonw -m pipeline.pull` so no console window appears. Remove with `Unregister-ScheduledTask -TaskName "ForeverAH pull" -Confirm:$false`.
- The very first scheduled run sat for over a minute with no progress and was stopped. Run by hand the same command took 3 s, and a second scheduled run took 7 s. The task now uses priority 6 (normal disk priority instead of the default low one); a run after that took 3 s. The cause of the first stall is not proven — a cold start under low disk priority is the guess.
First manual run: both EU houses answer with an empty table (nobody can scan them before launch) and are skipped; the beta house was unchanged.
After 48 h check: `data/pull.log` has a line per hour, none with FAILED, and `python -m pipeline.storage status` shows the snapshots.
