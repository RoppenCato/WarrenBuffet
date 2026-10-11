# 01 — Architecture

## Data flow

```
 ┌────────────── in game ──────────────┐        ┌──────────── on PC (Python) ────────────┐
 │ ForeverAH addon                     │        │                                        │
 │  Scanner  ── ReplicateItems ──┐     │ logout │  ingest_savedvars ─┐                   │
 │  Ledger   ── mail/AH events ──┼─► SavedVariables ───────────────►│                   │
 │  PlanView ◄── ForeverAH_Plan.lua ◄──┼────────┼── planner ◄─┐      ▼                   │
 └─────────────────────────────────────┘ /reload│             │   storage (Parquet +     │
                                                │ ingest_ahledger ─► DuckDB views)       │
 AHledger API (hourly, crowdsourced) ──────────►│ ingest_blizzard ─►    │                 │
 Blizzard Game Data API (if Forever opens) ────►│                       ▼                 │
                                                │              analytics → signals        │
                                                │                       │                 │
                                                │              dashboard (static HTML)    │
                                                └─────────────────────────────────────────┘
```

## Components

| Component | Language | Job |
|---|---|---|
| `addon/ForeverAH` | Lua (Mainline API) | Full AH scan, own-transaction ledger, inventory and own-auctions snapshot, show today's plan in game |
| `pipeline/ingest_*` | Python | Parse SavedVariables; pull AHledger hourly; pull Blizzard API if available |
| `pipeline/news` | Python | Pull Wowhead's Forever news feed, flag headlines that may move prices, list those waiting for a review |
| `pipeline/storage` | Python + Parquet/DuckDB | Tiered storage, dedup by `(source, house, snapshot_ts, item_id)`. Built 2026-10-11: L0, L1, ledger as Parquet; L2/L3 as views |
| `pipeline/pull` | Python | The hourly job: pricetable of every tracked house (`plan/houses.yaml`) and the news, straight into the store |
| `pipeline/analytics` | Python (polars/pandas) | Price stats, liquidity, time-to-sell, seasonality, event effects |
| `pipeline/planner` | Python | Combine signals + `plan/calendar.yaml` + rules → daily/weekly plan. v0 (2026-10-11): sell / hold / repost / buy suggestions, each with its reason |
| `dashboard/` | Jinja2 + Plotly → static HTML | Two pages (D22): **Today** — the planner's suggestions and why; **Market** — all tables and charts. Open locally or host privately. `dashboard/serve.py` serves them on localhost and gives the pages a Refresh button (D25) |
| `plan/` | YAML | Built-in plan: milestones, watchlist, rule thresholds |

## Key design choices

- **Own scans are the reference.** External feeds fill gaps and act as cross-check. Every row carries `source`.
- **One house first.** Forever has one AH per ruleset × faction × region (mega-server). Start with *our* house (e.g. `forever.normal.horde.eu`), add the opposite faction for neutral-AH arbitrage later.
- **Aggregate early.** Raw auction rows are kept short-term only; long-term history is per-item aggregates. See [04](04-data-storage.md).
- **Plan back into the game.** Addons can't read files at runtime, but a Lua data file listed in the `.toc` is loaded at login/`/reload`. Python writes `ForeverAH_Plan.lua`; the addon displays it. (Same trick TSM's desktop app uses.)
- **Data stays out of git.** `data/` is gitignored. Repo holds code, docs, plan and small reference tables.

## Scheduling

- **Local (default):** Windows Task Scheduler runs `pipeline pull` hourly (AHledger) and `pipeline ingest` on file change in `WTF/.../SavedVariables/`.
- **Optional backup:** GitHub Actions cron pulls AHledger hourly to a release asset / data branch when the PC is off. Decide after launch — see [decisions](decisions.md).

## Tech stack

Python 3.11+, `duckdb`, `polars`, `pyarrow`, `plotly`, `jinja2`, `requests`, `slpp` or `lupa` (Lua table parsing), `pyyaml`. Addon: plain Lua, no libraries at first.
