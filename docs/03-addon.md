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
  - `C_AuctionHouse.GetReplicateItemTimeLeft(i)` works in Forever (T3). From v0.2 the band is the 6th raw field: `itemID,count,buyout,minBid,bid,timeLeft;` (D15). The per-band counts stay in the header as `tl`.
  - `C_AuctionHouse.GetItemCommodityStatus` takes an ItemLocation, not an item id — it can't be asked about an arbitrary item.
- Pitfalls:
  - **Throttled call returns an empty market, not an error** (reported in beta). Treat `n == 0` on a populated house as "throttled", don't save.
    - T3 on build 70338: a throttled call got **no reply at all** — no event. The addon gives up after 120 s and reports it as throttled; the `n == 0` path is kept.
  - Very large replicates have caused disconnects historically; process in chunks across frames (`C_Timer.After(0, ...)`), e.g. 5–10k rows per frame.
  - Throttle is account-wide — alts share it.
  - Closing the AH before the scan finishes drops it (and still uses up the throttle). No reply in 120 s → dropped.
- Output per scan (SavedVariables): header (scan_id, house, unix time, n) + compact string rows `itemID,count,buyout,minBid,bid;...`, plus a per-item aggregate block computed in Lua (min, p10, p25, median, qty, auctions). See [04](04-data-storage.md).
  - v0.1 header: `id` (`ts:realm:faction`), `ts` (server time), `realm`, `faction`, `region`, `zone`, `n` (reported), `rows` (saved), `items`, `units`, `miss`, `skip`, `waitSec`, `procSec`, `frames`, `maxMs`, `tl`. House id is derived in the pipeline (D12).
  - Aggregates are strings too: `itemID,min,p10,p25,median,qty,auctions;`. Definition in D10 and the `Scanner.lua` header.
  - No variant key for random-suffix gear yet — rows are per itemID only.
- **Answered [T5], 2026-10-11:** yes — the AH is retail-style (quantity + unit price, posts go through `PostCommodity`) and stackables are in the replicate results. No `SendSearchQuery` scanning (D16).

### Ledger (own transactions)

- Posting: hook `AUCTION_HOUSE_AUCTION_CREATED` / owned-auction updates → item, qty, price, duration, deposit.
  - v0.1: `hooksecurefunc` on `PostItem` / `PostCommodity` remembers what the player posted (deposit from `CalculateItemDeposit` / `CalculateCommodityDeposit`); the row is written when `AUCTION_HOUSE_AUCTION_CREATED` gives the auction id.
  - v0.2 (T6): `cancel` comes from the player's `CancelAuction` click (auction id + cancel cost). `AUCTION_CANCELED` is not usable: no auction id on our own cancels, and it fires in bursts with other auctions' ids when a scan reply arrives. Not logged since v0.3.
  - v0.3: `dep` on the post row is `Calculate*Deposit`, which under-reports (0–8c where 1s was charged). The `money` row after a post is the real cost (D18).
  - Buying, real time: `PlaceBid` hook → `bid`; `ConfirmCommoditiesPurchase` hook → `buy_commodity`; `AUCTION_HOUSE_PURCHASE_COMPLETED`, `ITEM_PURCHASED` → `buy_done`, `buy_item`. `COMMODITY_PURCHASED` did not fire in T6. The `bought` mail row is the record to trust.
  - Durations in Forever: code 1 = 2 h, 2 = 8 h, 3 = 24 h.
- Outcomes from mail: sold (invoice: `GetInboxInvoiceInfo`), won/bought, expired, cancelled, outbid.
  - v0.1: invoice type gives `sold` / `bought` / `sold_pending`; subject (matched against the client's own `AUCTION_*_MAIL_SUBJECT` strings) gives `expired` / `cancelled` / `outbid`. Each mail is logged once (D11). Sold mails carry the item name only, no itemID.
  - The inbox's `daysLeft` is a snapshot from the last refresh, not a countdown; the expiry used for dedup is anchored to when each value was first seen (D17). Known limit: identical mails beyond the 50 visible inbox slots can be missed.
  - Row format: `ts,char,event,key=value,…,name=…` — see the `Ledger.lua` header.
- Gold snapshot per character on login/logout (`GetMoney()`).
  - `GetMoney()` is 0 while the game is quitting; v0.3 logs the last balance seen. `money` rows record every balance change while the AH or mailbox is open.
- Crafting: `TRADE_SKILL` events → reagents consumed vs output (for real crafting margins). v2.
- This is the only source of real P&L. Small data, keep forever.

### Inventory

Added 2026-10-11 (D21). The planner can't say what to sell or repost without knowing what the character holds and has listed.

- Read-only snapshots, **latest state only** (the ledger has the history), per character in `ForeverAHDB.inv[char]`:
  - `bags` — carried bags, `itemID:count,…`. Soulbound items are left out.
  - `bank` — character bank, saved while the bank is open. `abank` — account bank, if the client has one.
  - `auctions` — own auctions, `auctionID:itemID:qty:buyout:bid:status:secondsLeft;…` (status 0 active, 1 sold).
  - `<key>Ts` — server time of each snapshot. `err` — first snapshot error of the session.
- Bags: `C_Container.GetContainerNumSlots` / `GetContainerItemInfo` (`itemID`, `stackCount`, `isBound`), one second after `BAG_UPDATE_DELAYED`.
- Bag indexes are chosen by `Enum.BagIndex` **name** (`Backpack`, `Bag_n`, `ReagentBag`; bank: `Bank`, `BankBag_n`, `CharacterBankTab_n`; account: `AccountBankTab_n`), because the numbers differ between clients — 5 is a reagent bag in Mainline and a bank bag in Classic.
- A snapshot that reads zero slots (bank closed, logging out) is skipped, so a good one is never replaced by an empty one.
- Own auctions: two seconds after the AH opens the addon sends `C_AuctionHouse.QueryOwnedAuctions({})` — the same read-only query the Auctions tab sends — and saves the list on `OWNED_AUCTIONS_UPDATED`.
- Unverified in Forever until T9 runs: which bank layout the client has, whether `buyoutAmount` is a unit price or a total for stacks, and whether the query disturbs the full scan.

### Window (UI)

Added 2026-10-11 (D26). Messages in the chat frame got in the way.

- A small button ("FAH") and a log window, both draggable; positions and state are saved in `ForeverAHDB.ui`.
- Left-click the button: open or close the window. Right-click: quiet mode, in which the window never opens by itself.
- Scan messages and `/fah` open the window. Ledger lines and "next scan in N min" never do; while it is closed the button counts them ("FAH 3").
- Built from plain frames and textures, no Blizzard templates. If building it fails, messages fall back to chat and the reason is saved in `ForeverAHDB.uiErr`.
- Handler errors are saved in `ForeverAHDB.errors` (last 20) as well as shown by the game, and one failing handler no longer stops the others.

### Several characters

Added 2026-10-11 (D27). One character trades (a bank alt); others also open the AH.

- SavedVariables are per account, so every character writes to the same scans, ledger and inventory. Ledger rows and inventory snapshots carry the character.
- Any character scans. Same faction means the same house, so it is the same data; the 15-minute throttle and our timer are account-wide. A character on the other faction scans a different house — scans carry realm and faction.
- `/fah trader` on the trading character stores it in `ForeverAHDB.trader`. The dashboard plans purchases with that character's gold and adds up holdings across all characters.
- The character name is resolved at login and again when the world loads; balance rows wait until it is known.

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
  - 16001 for beta build 1.60.1.70338 — confirmed in game 2026-10-11.
- SavedVariables: `WTF\Account\<ACCOUNT>\SavedVariables\ForeverAH.lua` (written on logout/reload only).

## Offline tests

`.venv\Scripts\python tests\test_addon.py` runs the Lua files under a stubbed WoW API (`tests/wow_stub.lua`, Lua 5.1 via `lupa`) and round-trips the result through `pipeline/savedvars.py`. It checks our logic, not the client's behaviour — that is T3–T6.
