# forever-ah

Auction house data, statistics and a gold-making planner for **World of Warcraft: Forever** (EU launch 2026-11-05 00:00 CET).

> Status: **pre-launch**. Test addon v0.1 (scanner + ledger) and a SavedVariables parser exist; neither has run in game yet — beta tests T3–T6 are pending ([07](docs/07-test-plan.md)).

## What it does

1. **Collects** AH prices from several sources (own in-game scans, AHledger API, Blizzard API if it opens for Forever).
2. **Stores** them compactly in tiers (raw → per-scan aggregates → hourly → daily).
3. **Analyses** price level, liquidity, time-to-sell, weekday/hour patterns and event effects.
4. **Plans**: a daily buy/sell/craft list and a weekly/phase calendar, built from the playbook in this repo.
5. **Shows** it all in a static HTML dashboard, and pushes today's plan back into the game.

No automated buying, posting or bidding — ever. Scanning and planning only. See [docs/03-addon.md](docs/03-addon.md#rules).

## Repo layout (target)

```
addon/ForeverAH/        Lua addon: scanner, own-transaction ledger, in-game plan view
pipeline/               Python: ingest (SavedVariables, AHledger, Blizzard), storage, analytics
dashboard/              HTML templates → generated static site
plan/                   Built-in plan: calendar.yaml, watchlist.yaml, rules (machine-readable)
docs/                   Design docs (this folder)
tests/                  Offline tests: addon Lua under a stubbed WoW API
data/                   Local data — gitignored, never committed
```

## Dev setup

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python tests\test_addon.py
.venv\Scripts\python -m pipeline.savedvars "<...>\SavedVariables\ForeverAH.lua"
```

## Docs

| Doc | Contents |
|---|---|
| [01-architecture](docs/01-architecture.md) | Components, data flow, tech choices |
| [02-data-sources](docs/02-data-sources.md) | Source comparison, what each can and can't do |
| [03-addon](docs/03-addon.md) | Addon base decision, scan API, ledger, rules |
| [04-data-storage](docs/04-data-storage.md) | What to store, volumes, retention, schema |
| [05-market-playbook](docs/05-market-playbook.md) | Lessons from past Classic launches → signals |
| [06-milestone-calendar](docs/06-milestone-calendar.md) | Forever dates and what to do when |
| [07-test-plan](docs/07-test-plan.md) | Can we pull data automatically? Tests + results |
| [decisions](docs/decisions.md) | Decision log |
| [sources](docs/sources.md) | References |

## Attribution

Prices from the AHledger API must be credited with a link to [ahledger.com](https://ahledger.com) wherever shown (their terms). The dashboard footer does this.
