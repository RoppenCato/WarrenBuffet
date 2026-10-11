"""Signals computed from raw scan rows (pipeline.savedvars.raw_rows) - see docs/05-market-playbook.md.

Row = (item_id, count, buyout, min_bid, bid[, time_left]); buyout is the total for the row.
Thresholds here are first guesses on beta data, to be tuned on launch data.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

AH_CUT = 0.05        # faction AH cut on a sale (playbook; not verified in Forever yet)
MIN_DEPOSIT = 100    # copper per post - beta 2026-10-11 (docs/07-test-plan.md, T5)


def unit_price(count: int, buyout: int) -> int:
    """Same rounding as Scanner.lua."""
    return max(1, math.floor(buyout / count + 0.5))


def books(rows) -> dict[int, list[tuple[int, int]]]:
    """Order book per item: [(unit_price, units), ...] cheapest first, bid-only rows left out."""
    levels: dict[int, Counter] = defaultdict(Counter)
    for row in rows:
        item_id, count, buyout = row[:3]
        if buyout > 0:
            levels[item_id][unit_price(count, buyout)] += count
    return {item_id: sorted(c.items()) for item_id, c in levels.items()}


def weighted_median(book) -> int:
    total, cum = sum(q for _, q in book), 0
    for price, qty in book:
        cum += qty
        if cum * 2 >= total:
            return price
    return 0


def depth(book, pct: float = 5) -> int:
    """Units listed within pct % of the cheapest price - what must sell before the price moves."""
    limit = book[0][0] * (1 + pct / 100)
    return sum(q for p, q in book if p <= limit)


def turnover(prev_rows, cur_rows) -> dict[int, tuple[int, int]]:
    """{item_id: (units_gone, units_new)} between two scans, matching listings on
    (item, count, buyout). Gone = sold + expired + cancelled, so it is an upper bound on sales."""
    def listings(rows):
        return Counter(row[:3] for row in rows)

    prev, cur = listings(prev_rows), listings(cur_rows)
    out: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for (item_id, count, _), n in (prev - cur).items():
        out[item_id][0] += count * n
    for (item_id, count, _), n in (cur - prev).items():
        out[item_id][1] += count * n
    return {item_id: (gone, new) for item_id, (gone, new) in out.items()}


def underpriced(book_by_item, resale, sold_per_day, discount: float = 0.30, min_sold: float = 50,
                max_share_of_day: float = 0.5) -> list[dict]:
    """Flip candidates (playbook 7): lots listed at least `discount` below a resale price, in
    items that sell.

    resale[item_id] is the price we expect to relist at - pass something conservative. A listing
    median alone overstates it: listings are asks, sales happen at the cheap end.
    Buy every unit at or below (1 - discount) x resale. Profit is after the AH cut and one
    minimum deposit. Lots above max_share_of_day of estimated daily sales are skipped - they
    would not clear in time.
    """
    out = []
    for item_id, book in book_by_item.items():
        sold, price = sold_per_day.get(item_id) or 0, resale.get(item_id)
        if sold < min_sold or not price:
            continue
        cheap = [(p, q) for p, q in book if p <= price * (1 - discount)]
        units = sum(q for _, q in cheap)
        if not units or units > sold * max_share_of_day:
            continue
        cost = sum(p * q for p, q in cheap)
        profit = units * price * (1 - AH_CUT) - cost - MIN_DEPOSIT
        if profit > 0:
            out.append({"item_id": item_id, "units": units, "cost": cost, "avg_buy": cost / units,
                        "resale": price, "sold_per_day": sold, "profit": profit})
    return sorted(out, key=lambda d: -d["profit"])


def ledger_summary(ledger) -> dict:
    """Own cash flow. `other` is what the balance lost beyond purchases and sales: deposits and
    fees. (From addon v0.3 the money rows give this directly.)"""
    bought = sum(r.get("total", 0) for r in ledger if r["event"] == "bought")
    sold = sum(r.get("total", 0) - r.get("fee", 0) for r in ledger if r["event"] == "sold")
    gold = [r["copper"] for r in ledger if r["event"] == "gold" and r.get("copper")]
    first, last = (gold[0], gold[-1]) if gold else (0, 0)
    return {"posts": sum(r["event"] == "post" for r in ledger), "bought": bought, "sold": sold,
            "first": first, "last": last, "other": first - last - bought + sold}
