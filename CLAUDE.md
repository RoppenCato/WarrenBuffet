# WarrenBuffet (forever-ah)

AH data + gold planner for WoW: Forever. EU launch 2026-11-05 00:00 CET. Beta ends 2026-10-22 — last chance for in-game tests.

The docs are the spec. Read `README.md`, `docs/` and `plan/` before changing anything. Decisions live in `docs/decisions.md`.

## Hard constraints

- **No automated AH actions.** Never post, buy, bid or cancel from code. Scanning and displaying only (`docs/03-addon.md#rules`). `hooksecurefunc` to *observe* the player's own clicks is fine; calling those functions is not.
- **`data/` is never committed.** Check `.gitignore` before adding new output paths.
- **AHledger data must be credited** with a link to ahledger.com wherever it is shown.
- **Addon is our own minimal Lua** on the Mainline 12.1.5 API, no libraries. Auctionator is reference only — check its LICENSE before copying any code (not yet verified).

## Working style

- Terse. Small incremental changes. One commit per logical step.
- When changing existing code: comment out the old lines and add a comment above each change saying what changed and why.
- Update `docs/07-test-plan.md` statuses and `docs/decisions.md` as we go.

## Layout

```
addon/ForeverAH/   Lua addon (scanner, ledger; PlanView later)
pipeline/          Python: SavedVariables -> Parquet, AHledger pull, DuckDB views
dashboard/         Static Plotly/Jinja2 site (generated output in dashboard/site/, ignored)
plan/              calendar.yaml, watchlist.yaml
docs/              Spec
tests/             Offline tests (addon runs under a stubbed WoW API)
```

## Commands

- Tests: `.venv\Scripts\python tests\test_addon.py` (venv: `python -m venv .venv`, then `pip install -r requirements.txt`)
- T4/T5 report on a real file: `.venv\Scripts\python -m pipeline.savedvars "<...>\SavedVariables\ForeverAH.lua"`
- Pipeline tests: `.venv\Scripts\python tests\test_pipeline.py`
- Dashboard: `.venv\Scripts\python -m dashboard.build --sv "<...>\ForeverAH.lua" --pull` → `dashboard/site/index.html` (ignored). Preview server: the `dashboard` entry in `.claude/launch.json`.

## Addon notes

- Beta install path: `World of Warcraft\_classic_beta_\Interface\AddOns\ForeverAH\`
- `## Interface:` in the `.toc` comes from `/dump select(4, GetBuildInfo())` in game. Beta build 1.60.1.70338 = 16001.
- Forever's AH is retail-style: quantity + unit price, stackables are commodities, durations 2/8/24 h. Beta findings are in `docs/07-test-plan.md` — read them before trusting the wiki.
- SavedVariables are written on logout or `/reload` only: `WTF\Account\<ACCOUNT>\SavedVariables\ForeverAH.lua`.
- Nothing here can be tested in game by Claude — say so, and give the user the exact in-game steps.
