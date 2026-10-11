"""Planner v0: turn the latest scan, the holdings and the calendar into suggestions.

Every suggestion says what to do and why. Nothing here acts - the player does the clicks.
v0 has no history of its own: "normal price" is AHledger's 7-day median and "how fast it
sells" is their sold-per-day estimate. Thresholds are first guesses from the playbook
(docs/05-market-playbook.md), to be tuned against the ledger.
"""
from __future__ import annotations

import datetime as dt

from pipeline import analytics

MIN_LOT_VALUE = 20 * analytics.MIN_DEPOSIT   # 20s: below this the 1s deposit is over 5 % of the lot
SELL_PREMIUM = 1.3      # playbook 1: sell when the price is 1.3x its 7-day median or more
HOLD_DISCOUNT = 0.8     # price at or under 0.8x its 7-day median: wait
TIGHT_DAYS = 0.5        # under half a day of stock listed: supply is tight
MIN_SOLD = 50           # sold per day for "sells fast"
UNDERCUT = 0.05         # own auction more than 5 % above the cheapest: it will not sell first
NO_HOLD_PHASES = {"sell_to_levelers"}   # launch week: gold now beats gold later
# Launch week mode (added 2026-10-11, D30)
MOUNT_FUND = 120 * 10000                # level 40: 100g riding + 20g mount (reported, docs/05)
KEEP_CATEGORIES = {"stock_while_leveling", "endgame_mats"}   # watchlist categories wanted at 60
TREND = 0.10                            # a 10 % move between two scans counts as rising or falling
MIN_VENDOR_PROFIT = 50                  # copper; smaller below-vendor lots are not worth the walk


def sell(holdings: dict[int, int], books, ahl, phase: str | None = None) -> list[dict]:
    """One suggestion per item held: sell, hold, keep (lot too small) or price (no listings)."""
    out = []
    for item_id, units in holdings.items():
        book, ref = books.get(item_id), ahl.get(item_id)
        if not book:
            out.append({"action": "price", "item_id": item_id, "units": units, "value": 0,
                        "why": "Nobody is selling this right now, so there is no price to follow. Check it by hand."})
            continue
        price = book[0][0]
        value = units * price
        listed = sum(q for _, q in book)
        sold = ref.sold_per_day if ref and ref.sold_per_day else 0
        normal = ref.median_7d if ref else None
        rec = {"item_id": item_id, "units": units, "price": price, "value": value,
               "net": value * (1 - analytics.AH_CUT) - analytics.MIN_DEPOSIT}
        if value < MIN_LOT_VALUE:
            rec.update(action="keep", why=f"The lot is worth {analytics.money(value)} and a post costs "
                                          f"{analytics.money(analytics.MIN_DEPOSIT)}. Collect more first, or vendor it.")
        elif normal and price >= normal * SELL_PREMIUM:
            rec.update(action="sell", why=f"Cheapest listing is {price / normal - 1:.0%} above its 7-day median.")
        elif sold >= MIN_SOLD and listed / sold < TIGHT_DAYS:
            rec.update(action="sell", why=f"Supply is tight: {listed / sold:.1f} days of stock listed, "
                                          f"about {sold:,.0f} sell a day.")
        elif normal and price <= normal * HOLD_DISCOUNT and phase not in NO_HOLD_PHASES:
            rec.update(action="hold", why=f"Cheapest listing is {1 - price / normal:.0%} under its 7-day median. "
                                          "Wait unless you need the gold.")
        elif normal and price <= normal * HOLD_DISCOUNT:
            rec.update(action="sell", why="Price is under its 7-day median, but in launch week gold now beats gold later.")
        # Changed 2026-10-11: at launch there is no 7-day history at all. The old text claimed the
        # price was "near its 7-day level" even when there was no such level to compare with.
        # else:
        #     rec.update(action="sell", why="Price is near its 7-day level. Sell when convenient.")
        elif normal:
            rec.update(action="sell", why="Price is near its 7-day level. Sell when convenient.")
        elif phase in NO_HOLD_PHASES:
            rec.update(action="sell", why="No price history yet. Launch week: sell raw materials now, prices fall as supply catches up.")
        else:
            rec.update(action="sell", why="No price history for this item yet, so nothing to compare with. Sell when convenient.")
        out.append(rec)
    order = {"sell": 0, "hold": 1, "keep": 2, "price": 3}
    return sorted(out, key=lambda r: (order[r["action"]], -r["value"]))


def launch_mode(phase: str | None, books, ahl) -> bool:
    """Week one of a market: the calendar says so, or hardly anything has a 7-day price yet.
    The second test makes it work for any fresh market (the Hardcore launch) without a date."""
    if phase in NO_HOLD_PHASES:
        return True
    with_history = sum(1 for i in books if i in ahl and ahl[i].median_7d)
    return bool(books) and with_history < 0.2 * len(books)


def sell_launch(holdings: dict[int, int], books, prev_books=None, vendor=None, category=None) -> list[dict]:
    """Launch week version of sell(). There is no "normal" price yet, so nothing is compared with
    one. What is left: the vendor price as a floor, the deposit, how the price moved since the
    previous scan, and the playbook - raw materials peak in the first days, so sell, don't hold.
    vendor: {item_id: copper a vendor pays per unit}; category: {item_id: watchlist category}."""
    prev_books, vendor, category = prev_books or {}, vendor or {}, category or {}
    money = analytics.money
    out = []
    for item_id, units in holdings.items():
        book, pays = books.get(item_id), vendor.get(item_id) or 0
        if not book:
            out.append({"action": "price", "item_id": item_id, "units": units, "value": 0,
                        "why": "Nobody is selling this right now, so you set the price."
                               + (f" A vendor pays {money(pays)} each: anything above that is a gain." if pays else "")})
            continue
        price = book[0][0]
        value = units * price
        net = value * (1 - analytics.AH_CUT) - analytics.MIN_DEPOSIT
        rec = {"item_id": item_id, "units": units, "price": price, "value": value, "net": net}
        if pays and net <= units * pays:
            rec.update(action="vendor", net=units * pays,
                       why=f"A vendor pays {money(pays)} each. The AH would leave {money(max(net, 0) / units)} each "
                           "after the 5 % cut and the deposit.")
        elif value < MIN_LOT_VALUE:
            rec.update(action="keep", why=f"The lot is worth {money(value)} and a post costs {money(analytics.MIN_DEPOSIT)}. "
                                          "Collect more first" + (f", or vendor it for {money(units * pays)}." if pays else "."))
        elif category.get(item_id) in KEEP_CATEGORIES:
            rec.update(action="choice", why="Wanted at level 60. Keep it if you can spare the gold and bag space; "
                                            "sell it if the mount fund needs it.")
        else:
            prev = prev_books.get(item_id)
            if not prev:
                why = "No earlier scan to compare with. Raw materials peak in the first days of a launch and fall " \
                      "as gathering catches up: sell now, don't hold."
            else:
                change = price / prev[0][0] - 1
                supply = sum(q for _, q in book) / sum(q for _, q in prev) - 1
                if change <= -TREND:
                    why = f"Cheapest price fell {-change:.0%} since the last scan" \
                          + (f" while supply grew {supply:.0%}" if supply >= TREND else "") \
                          + ". It keeps falling as gathering catches up: sell now."
                elif change >= TREND:
                    why = f"Cheapest price rose {change:.0%} since the last scan. Raw materials peak in the first " \
                          "days of a launch: sell into it."
                else:
                    why = "Price is steady since the last scan. Raw materials peak in the first days of a launch " \
                          "and fall as gathering catches up: sell now, don't hold."
            rec.update(action="sell", why=why)
        out.append(rec)
    order = {"sell": 0, "choice": 1, "vendor": 2, "keep": 3, "price": 4}
    return sorted(out, key=lambda r: (order[r["action"]], -r["value"]))


def below_vendor(books, vendor, balance: int = 0, limit: int = 8) -> list[dict]:
    """Listings priced under what a vendor pays: buy, walk to a vendor, sell. No deposit, no cut,
    no waiting - the one purchase that is not a bet, so the only one suggested in launch week."""
    out = []
    for item_id, book in books.items():
        pays = vendor.get(item_id) or 0
        cheap = [(p, q) for p, q in book if p < pays]
        if not cheap:
            continue
        units, cost = sum(q for _, q in cheap), sum(p * q for p, q in cheap)
        profit = units * pays - cost
        if profit >= MIN_VENDOR_PROFIT:
            out.append({"item_id": item_id, "units": units, "cost": cost, "max_price": max(p for p, _ in cheap),
                        "vendor": pays, "profit": profit, "affordable": cost <= balance,
                        "why": f"Listed under the {analytics.money(pays)} a vendor pays for each."})
    out.sort(key=lambda d: (not d["affordable"], -d["profit"]))
    return out[:limit]


def repost(auctions: list[dict], books) -> list[dict]:
    """Own active auctions against the cheapest listing now. `buyout` is taken as the unit price
    (unverified for stacks - see docs/07-test-plan.md, T9)."""
    out = []
    for a in auctions:
        if a["status"] != 0:
            continue
        book = books.get(a["item"])
        cheapest = book[0][0] if book else None
        rec = {"item_id": a["item"], "units": a["qty"], "price": a["buyout"], "cheapest": cheapest,
               "hours": a["seconds"] / 3600, "char": a.get("char", "")}   # char added 2026-10-11
        if not cheapest or a["buyout"] <= cheapest * (1 + UNDERCUT):
            rec.update(action="leave", why="Yours is the cheapest, or within 5 % of it.")
        elif a["qty"] * cheapest < MIN_LOT_VALUE:
            rec.update(action="leave", why="Undercut, but the lot is too small to be worth another "
                                           f"{analytics.money(analytics.MIN_DEPOSIT)} deposit.")
        else:
            rec.update(action="repost", why=f"Undercut by {a['buyout'] / cheapest - 1:.0%}. Cancelling loses the deposit, "
                                            "so repost only if it will not sell otherwise.")
        out.append(rec)
    return sorted(out, key=lambda r: r["action"] != "repost")


def buy(books, ahl, balance: int, limit: int = 5) -> list[dict]:
    """Flip candidates (D20), cheapest lots first where the balance covers them."""
    median = {i: analytics.weighted_median(b) for i, b in books.items()}
    resale = {i: min(median[i], ahl[i].median_7d or median[i]) for i in books if i in ahl}
    sold = {i: p.sold_per_day or 0 for i, p in ahl.items()}
    out = []
    for d in analytics.underpriced(books, resale, sold, min_sold=MIN_SOLD):
        d = dict(d, max_price=int(d["resale"] * 0.7), affordable=d["cost"] <= balance,
                 why=f"{d['units']:,} units listed 30 % or more under both today's median and the 7-day median; "
                     f"about {d['sold_per_day']:,.0f} sell a day.")
        out.append(d)
    out.sort(key=lambda d: (not d["affordable"], -d["profit"]))
    return out[:limit]


def _date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else None


def calendar(plan: dict, today: dt.date) -> dict:
    """Active phase (what the playbook says to do now) and the next dated events."""
    events = {e["id"]: e for e in plan.get("events", [])}
    upcoming = sorted((((_date(e.get("start")) - today).days, e) for e in events.values()
                       if _date(e.get("start")) and _date(e.get("start")) >= today), key=lambda pair: pair[0])
    active, day = None, None
    for phase in plan.get("phases", []):
        start = _date(phase.get("from_date")) or _date(events.get(phase.get("from"), {}).get("start"))
        if not start or start > today:
            continue
        end = _date(phase.get("to_date")) or (start + dt.timedelta(days=phase["days"]) if phase.get("days") else None)
        if end is None or today <= end:
            active, day = phase, (today - start).days + 1   # day added 2026-10-11: "day 3 of 7"
    return {"phase": active, "phase_day": day,
            "upcoming": [{"days": days, "id": e["id"], "date": _date(e["start"]), "note": e.get("note", ""),
                          "status": e.get("status", "")} for days, e in upcoming[:4]]}
