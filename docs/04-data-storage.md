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
- Addon keeps: all L1 aggregates for scans not yet exported + raw rows for the **last 3 scans** only. Python dedups by `scan_id`, so the addon never needs to know what was ingested.
- Rows as compact strings (`itemID,count,buyout,minBid,bid;`), not nested Lua tables — far smaller and faster to write.
- Cap: if file > ~20 MB, drop oldest raw scans first.

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
