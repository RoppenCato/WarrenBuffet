# 02 — Data sources

## Summary

| Source | Coverage | Granularity | Gaps | Forever status | Cost / terms |
|---|---|---|---|---|---|
| **Own scans** (addon, `ReplicateItems`) | Whole AH per scan | Per auction, max 1 scan / 15 min | Only when we stand at the AH | **Works** — T3 2026-10-11: 79k rows in 14 s, stackables included | Free, ours |
| **AHledger API** | Houses where *someone* runs their addon | Per-scan latest; 7d hourly; 30/90d daily | Irregular (see test T1) | **Live**, all 12 Forever markets defined | Free; credit ahledger.com; no resale |
| **Blizzard Game Data API** | Whole AH, official | Hourly snapshot, per auction | None | **Unknown** — no Forever namespace found yet | Free; OAuth client credentials |
| Undermine Exchange | Retail only | Hourly | — | Not Forever | Patreon API key |
| wowpricehub.com, wowauction.us | Retail / Cata Classic | Hourly / "live" | — | Not Forever, no public API | — |

**Decision:** own scans = reference; AHledger = gap-filler and cross-check; Blizzard API replaces both if it opens. Retail sites are out of scope, but watch them — if they add Forever, Blizzard has opened the API.

## Own scans

- `C_AuctionHouse.ReplicateItems()` returns every auction. 15-minute **account-wide** throttle between successful calls.
- Per auction we get: count, min bid, buyout, current bid, item ID, quality, level, and a time-left band (1–4, confirmed in T3). **No auction ID, no exact time left, no owner** (owner hidden since 9.0.2 except own auctions).
  - In Forever a row is one seller's quantity at one unit price; `buyout` is the total for the row. Bids are practically unused (T5).
- Consequence: sell-through must be estimated by diffing `(item, buyout, count)` multisets between scans — approximate. Blizzard API (has auction ID + time left) would make this exact.
- Details and pitfalls: [03-addon](03-addon.md).

## AHledger API

- Base `https://api.ahledger.com`, no key needed (free key raises limits). 300 req/min; market tools 60/min. Honour `Cache-Control`.
- Market IDs: `forever.<normal|pvp|rp>.<alliance|horde>.<us|eu>`.
- Useful endpoints:
  - `/v1/pricetable/{market}` — every priced item, one line each (~3.1k rows, ~130 KB). **Our main hourly pull.**
  - `/v1/prices/{market}/{itemId}?range=7d|30d|90d` — history incl. min/p25/median/p75/qty/auctions per point, plus `sales.estimatedPerDay`.
  - `/v1/economy/{market}` — AH size per scan (auctions, units, value).
  - `/v1/deals`, `/v1/signals`, `/v1/crafting`, `/v1/structure`, `/v1/disenchant` — their analytics; use as benchmark for ours.
- Pricetable line format (header `AHL1|forever/pvp/horde/us|<unix_ts>|<rows>`):
  `itemId:median:minBuyout:quantity:median7d:median30d:low30d:high30d:soldPerDay×10` (copper). Matches their docs; verify per field once in T1b.
- Their data is crowdsourced from their addon users. Coverage of our EU house at launch is unknown.
- Terms: free personal/commercial use; credit with link wherever shown; don't present as own scans or resell as a feed. Don't scrape pages — use the API.

## Blizzard Game Data API

- Retail: `/data/wow/connected-realm/{id}/auctions` (hourly) and `/data/wow/auctions/commodities` (region-wide).
- Classic: `/data/wow/connected-realm/{id}/auctions/index` with `namespace=dynamic-classic-{region}`; AH ids 2 Alliance, 6 Horde, 7 Neutral.
- Forever: nothing published. Forever has no classic realms (one mega-server per ruleset), so whatever comes will look different. Test at launch: [T2](07-test-plan.md#t2).

## News (Wowhead)

Added 2026-10-11 (D24). Nerfs, buffs, vendor and drop changes and dates move prices before the data shows it.

- Feed: `https://www.wowhead.com/news/rss/forever` — the newest 40 stories, about four days at ~10 a day. Pulled with the hourly job and by the Refresh button.
- We keep headline, date, link and a short summary in `data/news/` (not committed). Articles stay on Wowhead; credit with a link wherever shown.
- Flagging (`pipeline/news.py`): a story is flagged when it names an item we know or an economy term (prices, supply, crafting, dates, balance), whole words only. Score 2+ waits for a review; weaker matches are only listed.
- Review is a reading job, done by Claude on request (prompt on the Today page, procedure in `CLAUDE.md`). Results go to `plan/news-log.yaml`; dated or lasting effects go to `plan/calendar.yaml` and the watchlist, which the planner reads.
- Limit: item matching only knows the watchlist and the item names cached so far. A story about an item outside those is caught only if it also uses an economy term.

## What no website gives us

- **Our own P&L** — sales, purchases, expired, cancelled, deposits lost, crafting costs. Only the addon ledger can record this. This is what tells us which strategies actually work.
