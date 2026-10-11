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
        else:
            rec.update(action="sell", why="Price is near its 7-day level. Sell when convenient.")
        out.append(rec)
    order = {"sell": 0, "hold": 1, "keep": 2, "price": 3}
    return sorted(out, key=lambda r: (order[r["action"]], -r["value"]))


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
    active = None
    for phase in plan.get("phases", []):
        start = _date(phase.get("from_date")) or _date(events.get(phase.get("from"), {}).get("start"))
        if not start or start > today:
            continue
        end = _date(phase.get("to_date")) or (start + dt.timedelta(days=phase["days"]) if phase.get("days") else None)
        if end is None or today <= end:
            active = phase
    return {"phase": active,
            "upcoming": [{"days": days, "id": e["id"], "date": _date(e["start"]), "note": e.get("note", ""),
                          "status": e.get("status", "")} for days, e in upcoming[:4]]}
