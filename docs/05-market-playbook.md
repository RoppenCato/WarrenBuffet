# 05 — Market playbook

Lessons from Classic 2019, Season of Mastery, Season of Discovery, Hardcore and Anniversary realms, adjusted for Forever. Each pattern ends with the **signal** the project computes for it. `[U]` = pattern without hard price data. Sources in [sources.md](sources.md).

## Forever is not 2019 Classic — what changes

| Difference | Effect on the playbook |
|---|---|
| **Mega-server**: one AH per ruleset × faction × region | Far more liquidity and competition. Fewer "only seller" niches; undercut wars faster. Volume strategies > margin strategies |
| **Neutral AH 15 % cut vs 5 % at faction AH** | Lasting faction price gaps. Arbitrage only if gap > ~15 % + deposits |
| **Black Market vendor** (beta): Black Lotus 50g, Arcane Crystal 50g, Pristine Scale 50g, Pristine Hide 20g, Fel Crystal / Stranglevine 20g+ | **Price ceiling** on those mats while the vendor stocks them. Don't speculate above it. Buy below it |
| **Black Market AH** (bidding, Deathcharger's Reins from 3,000g) | Gold sink; rich players' gold leaves the economy |
| **Scarce materials** (Pyrite, Frilled Lichen, Pristine Leather; more in files) | New, supply-limited mats used across crafts — likely premium early. Track from day 1 |
| **600+ new recipes**, rare BS/LW recipes drop in dungeons | Old "known" margins don't apply. Crafting margins must be measured, not assumed |
| **Riding**: 40 = 100g + 20g mount; 60 = 1,000g + 200g [R] | Mount at 40 is the first big gold demand from levelers |
| **No WoW Token, no boosts, harder line on gold buyers** | Less legal gold inflow; RMT still happens (bots seen in beta) |
| **Level cap fixed at 60**; new content as raids/zones at 60 | No expansion wipe of item value; phase speculation still matters |
| **Gear stat changes** (hit+crit merged, healing → also spell damage) | Old BoE value rankings wrong; let data decide |

## 1. Launch week (days 0–7)

- Gold is scarce; every leveler is buying. Sell raw low-tier cloth/ore/herbs, bags, bandage cloth, potions, stat food, leveling greens (Str/Agi). [Wowhead AH guide]
- Low-tier mats (Peacebloom, Copper, Linen) start high and deflate fast as gathering catches up. [U] Typical: peak days 1–5, steep fall over 2–4 weeks.
- Forever twist: starter-zone nodes deplete after 1–2 taps and mobs skin once → early mat scarcity may last longer than in 2019.
- Deposits are a big share of value early — prefer short durations (2 h / 8 h / 24 h in Forever, seen in beta 2026-10-11) to limit losses on expiry.
- Beta 2026-10-11: every post cost at least **1s**, even 1 Linen at 17c, and cancelling did not return it. Never post single cheap items — batch until the lot is worth far more than the deposit.
- Don't buy anything speculative. Gold now is worth more than gold later.
- **Signals:** `deflation_rate` per item (log-price slope over 48h); `sell_now` = deflation_rate < 0 and price ≥ 1.3× 7-day median → sell stock now rather than hold [thresholds tuned on data].

## 2. Month 1–2: levelers → endgame

- Levelers dump endgame-useful mats cheaply: Swiftthistle (Thistle Tea), Small Flame Sac (fire resistance), Golden Pearl, Fused Wiring — buy and hold for level 60 demand.
- Level 40 mount demand (≈120g) keeps leveling-zone prices supported.
- Arcane Crystal / Black Lotus: buy only below the Black Market vendor price (50g).
- **Signals:** `stock_up` = item in endgame-demand list and price < 30-day p25; `vendor_cap` flag.

## 3. Level 60 economy

- Main money items historically: flasks (Titans, Supreme Power, Distilled Wisdom), Elixir of the Mongoose, Greater Arcane Elixir, Greater Fire Protection, Major Mana, Devilsaur Leather/sets, Arcanite Bar, enchanting mats (Large Brilliant Shard), Thorium, Runecloth. [Icy Veins goldmaking]
- Cooldown crafts: Arcanite transmute (2-day), Mooncloth (4-day). Buy reagents → craft → sell bars beats selling a service. [Bitt's guides]
- 2019 reference: flasks 60–80g (Feb 2020) → 90–240g (Mar 2020) as BWL raiding grew.
- Forever: recipes/cooldowns may differ — verify each in game.
- **Signals:** `craft_margin` = product median × (1 − AH cut) − Σ reagent min price; `cooldown_ready` from ledger.

## 4. Weekly cycle (once raids exist)

- Raid consumables peak just before/at raid nights; buy Thu–Mon, sell Tue–Wed (EU reset is Wednesday). Major Mana spikes on raid nights. [Icy Veins; Blizzard forums]
- Post short listings (2 h or 8 h — Forever offers 2/8/24 h, beta 2026-10-11) on raid-day afternoons.
- [U] Leveling mats: weekend and evening demand peaks.
- **Signals:** `weekday_index` and `hour_index` per item (ratio to weekly mean, from L2); buy when index < 0.9, sell when > 1.1.

## 5. Phase transitions and speculation

- **Sell into the announcement, not the launch.** Prices rise when content is announced/datamined; the launch day often floods with hoarders' stock. Naxx-era Arcane Crystal advice: sell when the phase is announced. [Bitt's guides]
- Demand from a new raid is partly **one-time** (attunements, resistance sets, tier crafting) → spike then fade.
- **Developer supply changes kill hoards:** Black Lotus ~300g → ~40g (−87 %) after the May 2020 spawn buff; buffed again Feb 2025. Don't hold big stockpiles of anything Blizzard can tune (herbs, nodes, vendor stock).
- AQ War Effort (2020): huge one-off demand for low mats (90k Copper Bars, 400k Runecloth Bandages per faction…) — watch for any Forever "war effort" style event.
- Items made obsolete by new content fall "suddenly and dramatically" (TBC Classic) — sell old-tier crafts before new tier drops.
- **Signals:** `event_window` from `plan/calendar.yaml`; for each tagged item, pre-event price drift vs baseline; exit rule = sell 50 % at announcement, rest before launch.

## 6. Risks / what crashes

- **Bots** push down what they farm (herbs, ore, crystals, potions) and push up everything else via gold inflow. Anniversary: Black Lotus ~50g → 12g in one night (Dec 2024).
- **Inflation** over months: hold value in hard-to-bot goods (crafted BoEs, rare recipes), not bot-farmed mats.
- **Hoard dumps** at phase launch.
- **Deposit losses** from posting too long/too high — ledger tracks this.
- **Signals:** `supply_shock` = quantity listed > 3× 7-day median with price drop > 30 %; `bot_suspect` category flag [U].

## 7. Repeatable easy money

- Vendor items with limited stock / single source (e.g. Recipe: Frost Oil, limited alchemy recipes like Free Action/Shadow Protection, Deneb Walker's First Aid manuals) → resell. [Warcraft Tavern hidden vendors]
- AH listings below vendor sell price → buy and vendor (needs vendor price table).
- Disenchant arbitrage: green BoEs below expected shard/dust value.
- Undervalued listings: buy below 30-day p25 *only if* liquidity is high (sold/day ≥ threshold) — flipping is a volume game.
- Always set a buyout; post multiple stack sizes.
- **Signals:** `below_vendor`, `de_arbitrage`, `flip_candidate` (discount ≥ 25 % vs 30d median AND est. sell-through ≥ X/day AND expected time-to-sell < 48h).

## 8. Hardcore launch = second fresh market

Hardcore gets its own ruleset AH (winter 2026/27). It will replay the launch-week pattern from scratch — and by then we have our own launch price curves from Normal/PvP to predict it. Best opportunity of the season.

## Numbers to remember

| Item | Early | Later |
|---|---|---|
| Classic gold (RMT) | ~$1.1/g (Sep 2019) | ~$20–30 per 1,200g (Anniversary) |
| Flask (2019) | 60–80g (Feb 2020) | 90–240g (Mar 2020) |
| Black Lotus (2019) | ~300g pre-buff (May 2020) | ~40g after → 60–140g (Jul 2020) |
| Arcane Crystal | ~80g pre-P5 | ~35–42g mid-P5 |
| Blue Sapphire | < 15g (2019 P5/P6) | 46–108g (Era 2025) |
