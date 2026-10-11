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
- Returned values (in order): name, texture, count, qualityID, usable, level, levelType, minBid, minIncrement, buyoutPrice, bidAmount, highBidder, bidderFullName, owner, ownerFullName, saleStatus, itemID, hasAllInfo.
  - Store only: `itemID, count, buyoutPrice, minBid, bidAmount` (+ link/variant key for gear with random suffixes — see below).
  - `hasAllInfo == false` → item not cached; use `Item:CreateFromItemID(id):ContinueOnItemLoad(...)`, or just skip name/link (we only need itemID).
- Pitfalls:
  - **Throttled call returns an empty market, not an error** (reported in beta). Treat `n == 0` on a populated house as "throttled", don't save.
  - Very large replicates have caused disconnects historically; process in chunks across frames (`C_Timer.After(0, ...)`), e.g. 5–10k rows per frame.
  - Throttle is account-wide — alts share it.
- Output per scan (SavedVariables): header (scan_id, house, unix time, n) + compact string rows `itemID,count,buyout,minBid,bid;...`, plus a per-item aggregate block computed in Lua (min, p10, p25, median, qty, auctions). See [04](04-data-storage.md).
- **Open question [T5]:** does `ReplicateItems` include stackable commodities in Forever? If the AH is retail-style (commodities by quantity), they may need `C_AuctionHouse.SendSearchQuery` per item — slow, watchlist-only.

### Ledger (own transactions)

- Posting: hook `AUCTION_HOUSE_AUCTION_CREATED` / owned-auction updates → item, qty, price, duration, deposit.
- Outcomes from mail: sold (invoice: `GetInboxInvoiceInfo`), won/bought, expired, cancelled, outbid.
- Gold snapshot per character on login/logout (`GetMoney()`).
- Crafting: `TRADE_SKILL` events → reagents consumed vs output (for real crafting margins). v2.
- This is the only source of real P&L. Small data, keep forever.

### PlanView

- Python writes `addon/ForeverAH/ForeverAH_Plan.lua` (listed in the `.toc`) with today's buy/sell/craft list and price targets.
- `/fah` opens a simple frame; tooltip line "target buy ≤ X / sell ≥ Y" for watchlist items.
- Refreshes on `/reload` after the pipeline runs.

## Rules

- Never call protected functions in code paths without a player click: posting, buying, bidding, cancelling. No queues that auto-confirm. Automation of AH actions breaks Blizzard's ToS and risks a ban (Blizzard has said it will act harder on gold buying/abuse in Forever).
- Scanning, reading mail info, and displaying data are fine.
- No network access from the addon (not possible anyway); data leaves the game only via SavedVariables on logout/reload.

## Install paths

- Beta: `World of Warcraft\_classic_beta_\Interface\AddOns\ForeverAH\`
- Launch folder name: unknown — check after the launch client ships.
- `.toc` `## Interface:` number: read in game with `/dump select(4, GetBuildInfo())`.
- SavedVariables: `WTF\Account\<ACCOUNT>\SavedVariables\ForeverAH.lua` (written on logout/reload only).
