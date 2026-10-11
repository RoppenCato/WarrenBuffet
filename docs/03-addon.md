# 03 — Addon (`addon/ForeverAH`)

## Base decision

| Candidate | Forever? | License | Verdict |
|---|---|---|---|
| Auctioneer | No — built on the legacy Classic AH API | — | **No.** Forever uses Mainline (12.1.5) APIs; Classic addons don't load |
| TradeSkillMaster | Not confirmed for Forever | All rights reserved | **No fork.** Can still be used alongside as a player |
| AHledger addon | Yes | All rights reserved (personal use) | **No fork.** Use their API instead |
| **Auctionator** | Yes (Forever build reported) | Open source on GitHub (TheMouseNest/Auctionator) — **license not yet verified** | **Reference only**: read its full-scan loop and item-load handling |
| **Own minimal addon** | — | Ours | **Chosen.** We need ~3 small modules, not a full AH UI |

Why not fork Auctionator: we don't need its posting/shopping UI, and a small addon is easier to keep working through beta/patch API changes. If Auctionator's license allows (check `LICENSE` in the repo), copy specific functions with attribution.

Optional: if Auctionator is installed, read its prices through its public API for tooltips. Not needed for v1.

## Modules

### Scanner

- Trigger: `AUCTION_HOUSE_SHOW` → if ≥15 min since last successful scan → `C_AuctionHouse.ReplicateItems()`.
- On `REPLICATE_ITEM_LIST_UPDATE`: `n = C_AuctionHouse.GetNumReplicateItems()`, loop `0..n-1` over `GetReplicateItemInfo(i)`.
  - The event fires again for every item the client caches afterwards (~2000/frame per the wiki). Only the first one after our request is handled.
- Returned values (in order): name, texture, count, qualityID, usable, level, levelType, minBid, minIncrement, buyoutPrice, bidAmount, highBidder, bidderFullName, owner, ownerFullName, saleStatus, itemID, hasAllInfo.
  - Store only: `itemID, count, buyoutPrice, minBid, bidAmount` (+ link/variant key for gear with random suffixes — see below).
  - `hasAllInfo == false` → item not cached; use `Item:CreateFromItemID(id):ContinueOnItemLoad(...)`, or just skip name/link (we only need itemID).
  - v0.1: misses are counted and the row is saved as is — the wiki says count, minBid, buyoutPrice and itemID are available immediately. `bidAmount` on a miss is unverified.
  - `C_AuctionHouse.GetReplicateItemTimeLeft(i)` is listed on the wiki. v0.1 only counts rows per band (`tl` in the scan header) to see if it works in Forever; if it does, add it to the raw row.
- Pitfalls:
  - **Throttled call returns an empty market, not an error** (reported in beta). Treat `n == 0` on a populated house as "throttled", don't save.
  - Very large replicates have caused disconnects historically; process in chunks across frames (`C_Timer.After(0, ...)`), e.g. 5–10k rows per frame.
  - Throttle is account-wide — alts share it.
  - Closing the AH before the scan finishes drops it (and still uses up the throttle). No reply in 120 s → dropped.
- Output per scan (SavedVariables): header (scan_id, house, unix time, n) + compact string rows `itemID,count,buyout,minBid,bid;...`, plus a per-item aggregate block computed in Lua (min, p10, p25, median, qty, auctions). See [04](04-data-storage.md).
  - v0.1 header: `id` (`ts:realm:faction`), `ts` (server time), `realm`, `faction`, `region`, `zone`, `n` (reported), `rows` (saved), `items`, `units`, `miss`, `skip`, `waitSec`, `procSec`, `frames`, `maxMs`, `tl`. House id is derived in the pipeline (D12).
  - Aggregates are strings too: `itemID,min,p10,p25,median,qty,auctions;`. Definition in D10 and the `Scanner.lua` header.
  - No variant key for random-suffix gear yet — rows are per itemID only.
- **Open question [T5]:** does `ReplicateItems` include stackable commodities in Forever? If the AH is retail-style (commodities by quantity), they may need `C_AuctionHouse.SendSearchQuery` per item — slow, watchlist-only.

### Ledger (own transactions)

- Posting: hook `AUCTION_HOUSE_AUCTION_CREATED` / owned-auction updates → item, qty, price, duration, deposit.
  - v0.1: `hooksecurefunc` on `PostItem` / `PostCommodity` remembers what the player posted (deposit from `CalculateItemDeposit` / `CalculateCommodityDeposit`); the row is written when `AUCTION_HOUSE_AUCTION_CREATED` gives the auction id. `AUCTION_CANCELED` → `cancel` row with that id.
  - Buying, real time: `PlaceBid` hook → `bid`; `AUCTION_HOUSE_PURCHASE_COMPLETED`, `ITEM_PURCHASED`, `COMMODITY_PURCHASED` → `buy_*`. The `bought` mail row is the record to trust.
- Outcomes from mail: sold (invoice: `GetInboxInvoiceInfo`), won/bought, expired, cancelled, outbid.
  - v0.1: invoice type gives `sold` / `bought` / `sold_pending`; subject (matched against the client's own `AUCTION_*_MAIL_SUBJECT` strings) gives `expired` / `cancelled` / `outbid`. Each mail is logged once (D11). Sold mails carry the item name only, no itemID.
  - Row format: `ts,char,event,key=value,…,name=…` — see the `Ledger.lua` header.
- Gold snapshot per character on login/logout (`GetMoney()`).
- Crafting: `TRADE_SKILL` events → reagents consumed vs output (for real crafting margins). v2.
- This is the only source of real P&L. Small data, keep forever.

### PlanView

- Python writes `addon/ForeverAH/ForeverAH_Plan.lua` (listed in the `.toc`) with today's buy/sell/craft list and price targets.
- `/fah` opens a simple frame; tooltip line "target buy ≤ X / sell ≥ Y" for watchlist items.
- Not built yet. In v0.1 `/fah` prints status, `/fah scan` scans now, `/fah item <id>` prints an item from the latest scan.
- Refreshes on `/reload` after the pipeline runs.

## Rules

- Never call protected functions in code paths without a player click: posting, buying, bidding, cancelling. No queues that auto-confirm. Automation of AH actions breaks Blizzard's ToS and risks a ban (Blizzard has said it will act harder on gold buying/abuse in Forever).
- Scanning, reading mail info, and displaying data are fine.
- No network access from the addon (not possible anyway); data leaves the game only via SavedVariables on logout/reload.

## Install paths

- Beta: `World of Warcraft\_classic_beta_\Interface\AddOns\ForeverAH\`
- Launch folder name: unknown — check after the launch client ships.
- `.toc` `## Interface:` number: read in game with `/dump select(4, GetBuildInfo())`.
  - Set to 16001, derived from the installed beta build 1.60.1.70338. Not confirmed in game.
- SavedVariables: `WTF\Account\<ACCOUNT>\SavedVariables\ForeverAH.lua` (written on logout/reload only).

## Offline tests

`.venv\Scripts\python tests\test_addon.py` runs the Lua files under a stubbed WoW API (`tests/wow_stub.lua`, Lua 5.1 via `lupa`) and round-trips the result through `pipeline/savedvars.py`. It checks our logic, not the client's behaviour — that is T3–T6.
