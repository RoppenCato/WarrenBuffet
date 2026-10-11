# 04 — Data storage

## Is the data too much?

Raw, yes, if we keep it all. Aggregated, no. Measured on the beta (AHledger economy endpoint, PvP Horde US, 2026-10-11): **88,212 auctions, 3,127 distinct items** in one house. Launch mega-servers will be bigger — plan for **150k auctions, 6k items** per house.

| Tier | What | Size estimate | Retention |
|---|---|---|---|
| L0 raw own scans | One row per auction | ~1.5–2 MB/scan (Parquet), ~4 MB/scan in SavedVariables | **14 days** |
| L1 scan aggregates | One row per item per snapshot, any source | ~50 KB/snapshot | Forever |
| L2 hourly | One row per item per hour (best source wins) | ~400 MB/year at 6k items | **180 days**, then dropped |
| L3 daily | One row per item per day | ~20 MB/year | Forever |
| Ledger | Own posts/sales/buys/expired/gold | KB/day | Forever |
| Reference | Items, vendor prices, recipes, Black Market stock | < 10 MB | Versioned in git |

Steady state < 2 GB on disk. Nothing under `data/` goes into git.

## Why keep each tier

- **L0 raw (short):** needed for sell-through estimation (which listings disappeared between scans) and order-book depth (how much is listed within 5 % of min). Not needed long-term.
- **L1:** the core history; cheap; allows recomputing everything else.
- **L2 hourly:** time-of-day and weekday patterns. After 6 months the pattern is known; daily is enough.
- **L3 daily:** long-run trends, phase/event effects, year-over-year.
- **Ledger:** real P&L per strategy — the only thing that proves what works.

## What NOT to store

- Item names/textures per auction (join from reference table instead).
- Owner names (hidden by the API anyway, privacy).
- Raw AHledger history arrays every hour — pull the `pricetable` (latest only); fetch per-item history only for backfill.
- Duplicate snapshots — dedup on `(source, house, snapshot_ts, item_id)`.

## SavedVariables budget

- Written only on logout/`/reload`. Large files slow login.
- Addon keeps: L1 aggregates for the **last 40 scans** + raw rows for the **last 3 scans** only (D9). Python dedups by `scan_id`, so the addon never needs to know what was ingested — but ingest before 40 scans roll over.
- Rows as compact strings (`itemID,count,buyout,minBid,bid,timeLeft;` — `timeLeft` band added 2026-10-11, D15), not nested Lua tables — far smaller and faster to write.
- Measured in T4: 79k auctions → 1.3 MB of raw rows, 0.1 MB of aggregates. The ~4 MB/scan estimate above is high for beta-sized houses.
- Cap: if file > ~20 MB, drop oldest raw scans first.
- Inventory (`inv`, added 2026-10-11): latest bags, bank and own auctions per character as short strings — a few KB, overwritten in place.
- Item reference (`items`, added 2026-10-11): one line per item with vendor price, stack size, class and name — about 40 bytes an item, written once. This is the "Reference" tier for items; it lives in the SavedVariables file rather than in git because the game is its source.
- Two accounts means two SavedVariables files. `data/local.json` holds the game folder (`"wow"`); every `WTF/Account/*/SavedVariables/ForeverAH.lua` under it is loaded and merged (D32).

## Schema (L1, Parquet, partitioned by `date`)

| Column | Type | Note |
|---|---|---|
| `source` | str | `own`, `ahledger`, `blizzard` |
| `house` | str | `forever.normal.horde.eu` style (AHledger market id) |
| `snapshot_ts` | timestamp UTC | scan/observation time |
| `item_id` | int | |
| `variant` | str/null | suffix/bonus key for gear, null for stackables |
| `min_buyout` | int | copper, per unit |
| `p10`, `p25`, `median`, `p75` | int | per unit, quantity-weighted |
| `quantity` | int | units listed |
| `auctions` | int | listings |
| `depth_5pct` | int | units within 5 % of min (own scans only) |
| `sold_est_per_day` | float/null | AHledger estimate, or ours from L0 diffs |

Ledger table: `ts, character, event (post|sold|bought|expired|cancelled|deposit|craft), item_id, qty, unit_price, total, fee, house`.

Engine: Parquet files + DuckDB for queries/views. SQLite only for the ledger if convenient.

## As built (2026-10-11, `pipeline/storage.py`)

```
data/l0/date=YYYY-MM-DD/<house>-<ts>.parquet            raw own scans, one row per auction, pruned after 14 days
data/l1/date=YYYY-MM-DD/<source>-<house>-<ts>.parquet   one row per item per snapshot, kept forever
data/ledger.parquet                                     own transactions, kept forever
data/ahledger/<house>/<ts>.txt                          landing zone for pulled pricetables; only the newest is kept
```

- One file per snapshot. A snapshot whose file exists is skipped, which is the dedup on `(source, house, snapshot_ts)`.
- L1 columns are the schema above. Own scans fill everything except `sold_est_per_day`; `p75` and `depth_5pct` need the raw rows, so they are empty for a scan ingested after the addon dropped its raw. AHledger rows have `median`, `min_buyout`, `quantity` and `sold_est_per_day` only. `variant` is always empty until gear variants are handled.
- L0 columns: `house, snapshot_ts, item_id, count, buyout, min_bid, bid, time_left`.
- Ledger columns: `ts, character, event, item_id, qty, unit_price, total, fee, deposit, copper, delta, auction, name, row` — `row` is the addon's original line and the dedup key.
- DuckDB views from `storage.connect()`: `l0`, `l1`, `ledger`, `latest` (newest snapshot per source and house), `hourly` (L2: one row per house, item and hour; Blizzard beats own beats AHledger), `daily` (L3). L2 and L3 are views over L1 until L1 is too big to scan each time; the 180-day L2 retention starts mattering only then.
- Measured on beta data: two scans (163,507 auction rows) are 0.6 MB in L0; three L1 snapshots are 0.14 MB; a full ingest takes under a second. The size table above is generous.
- `python -m pipeline.storage ingest` reads the SavedVariables file and the landing zone; `python -m pipeline.pull` stores what it pulls; the dashboard's Refresh does both.
