# Decision log

| # | Date | Decision | Why | Revisit |
|---|---|---|---|---|
| D1 | 2026-10-11 | Write own minimal addon; Auctionator as code reference only | Forever uses Mainline 12.1.5 API (Auctioneer won't load); TSM and AHledger addons are all rights reserved; we need ~3 small modules | If Auctionator license allows reuse, copy specific functions with attribution |
| D2 | 2026-10-11 | Own scans = reference; AHledger API = gap-filler + cross-check; Blizzard API replaces both if it opens | AHledger coverage irregular (T1: 37/168 h); own scans only when online | After T2 at launch |
| D3 | 2026-10-11 | Tiered storage: raw 14 d, hourly 180 d, scan aggregates + daily forever | Raw would be ~GBs/month; aggregates < 2 GB steady state | After 1 month of real data |
| D4 | 2026-10-11 | Data never committed to git | Size + AHledger terms (no redistribution as a feed) | — |
| D5 | 2026-10-11 | No automated AH actions | ToS / ban risk | Never |
| D6 | 2026-10-11 | Retail price sites (Undermine, wowpricehub, wowauction.us) out of scope | Don't cover Forever | If they add Forever → Blizzard API likely open |
| D7 | open | Hosting of dashboard: local vs private GitHub Pages | Pages is public on free plans | Before launch |
| D8 | open | Backup pull via GitHub Actions when PC is off | Fills gaps; adds complexity | After launch week |
