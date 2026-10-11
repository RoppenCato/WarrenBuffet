# Decision log

| # | Date | Decision | Why | Revisit |
|---|---|---|---|---|
| D1 | 2026-10-11 | Write own minimal addon; Auctionator as code reference only | Forever uses Mainline 12.1.5 API (Auctioneer won't load); TSM and AHledger addons are all rights reserved; we need ~3 small modules | If Auctionator license allows reuse, copy specific functions with attribution. 2026-10-11: license still unverified (repo link in sources.md gave 404); addon v0.1 written from the API docs, no code copied |
| D2 | 2026-10-11 | Own scans = reference; AHledger API = gap-filler + cross-check; Blizzard API replaces both if it opens | AHledger coverage irregular (T1: 37/168 h); own scans only when online | After T2 at launch |
| D3 | 2026-10-11 | Tiered storage: raw 14 d, hourly 180 d, scan aggregates + daily forever | Raw would be ~GBs/month; aggregates < 2 GB steady state | After 1 month of real data |
| D4 | 2026-10-11 | Data never committed to git | Size + AHledger terms (no redistribution as a feed) | — |
| D5 | 2026-10-11 | No automated AH actions | ToS / ban risk | Never |
| D6 | 2026-10-11 | Retail price sites (Undermine, wowpricehub, wowauction.us) out of scope | Don't cover Forever | If they add Forever → Blizzard API likely open |
| D7 | open | Hosting of dashboard: local vs private GitHub Pages | Pages is public on free plans | Before launch |
| D8 | open | Backup pull via GitHub Actions when PC is off | Fills gaps; adds complexity | After launch week |
| D9 | 2026-10-11 | Addon keeps raw rows for the last 3 scans and aggregates for the last 40 scans | The addon can't know what Python has ingested, so "all not yet exported" isn't implementable. Simulated launch size: 0.25 MB aggregates + 3.8 MB raw per scan → ~21 MB worst case | After T4 with a real file |
| D10 | 2026-10-11 | Aggregate definition: unit price = buyout ÷ count (rounded, min 1 copper); percentiles quantity-weighted with integer comparisons; bid-only rows count in qty/auctions but not in prices | Python must reproduce the addon's numbers exactly (`pipeline.savedvars.aggregate`) | T7, if AHledger's median is defined differently |
| D11 | 2026-10-11 | Ledger rows are strings `ts,char,event,key=value,…,name=…`; mail is deduplicated on event + item name + count + bid + expiry time | Fields differ per event and may change during beta; the inbox has no mail id | After T6 |
| D12 | 2026-10-11 | Addon stores realm, faction, region and zone per scan; the pipeline maps them to a house id | No API for the ruleset confirmed in Forever | After T3 |
| D13 | 2026-10-11 | `hasAllInfo` misses are counted, not waited for. A scan is dropped if the AH closes before it finishes | itemID, count, minBid and buyout are valid immediately (wiki); a partial scan would look like mass sell-through | After T3 |
| D14 | 2026-10-11 | Repo root is `C:\dev\WarrenBuffet` (moved up from `forever-ah/`), remote `RoppenCato/WarrenBuffet` | Paths in the brief are root-relative; CLAUDE.md must sit in the session folder | — |
