"""Tests for pipeline/analytics.py and pipeline/ahledger.py (no network).

    .venv/Scripts/python tests/test_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import ahledger, analytics  # noqa: E402

# (item, count, buyout total, minBid, bid, timeLeft): 10 @ 100, 10 @ 200, 20 @ 300, one bid-only row
ROWS = [(1, 10, 1000, 0, 0, 3), (1, 10, 2000, 0, 0, 3), (1, 20, 6000, 0, 0, 4), (1, 5, 0, 50, 0, 1)]


def test_books_median_depth():
    book = analytics.books(ROWS)[1]
    assert book == [(100, 10), (200, 10), (300, 20)]
    assert analytics.weighted_median(book) == 200
    assert analytics.depth(book, 5) == 10 and analytics.depth(book, 100) == 20


def test_turnover_counts_units_gone_and_new():
    later = [(1, 10, 2000, 0, 0, 2), (1, 20, 6000, 0, 0, 3), (1, 7, 700, 0, 0, 4), (2, 3, 30, 0, 0, 4)]
    assert analytics.turnover(ROWS, later) == {1: (15, 7), 2: (0, 3)}   # the bid-only row left too
    assert analytics.turnover(ROWS[:3], [r[:5] for r in ROWS[:3]]) == {}   # 5- and 6-field rows match


def test_underpriced_needs_discount_liquidity_and_profit():
    book = {1: [(100, 10), (200, 10), (300, 20)], 2: [(100, 10), (300, 20)], 3: [(1, 5), (10, 50)]}
    resale, sold = {1: 200, 2: 200, 3: 10}, {1: 100, 2: 5, 3: 1000}
    deals = analytics.underpriced(book, resale, sold)
    assert [d["item_id"] for d in deals] == [1]          # 2 sells too slowly, 3 loses to the deposit
    d = deals[0]
    assert (d["units"], d["cost"], d["resale"]) == (10, 1000, 200)
    assert d["profit"] == 10 * 200 * 0.95 - 1000 - analytics.MIN_DEPOSIT
    assert analytics.underpriced(book, resale, {1: 15, 2: 5, 3: 1000}, min_sold=10) == []   # lot > half a day of sales


def test_ledger_summary_infers_deposits_from_the_balance():
    ledger = [{"event": "gold", "copper": 339}, {"event": "post"}, {"event": "post"},
              {"event": "bought", "total": 5}, {"event": "gold", "copper": 0}, {"event": "gold", "copper": 134}]
    s = analytics.ledger_summary(ledger)
    assert (s["first"], s["last"], s["bought"], s["sold"], s["other"], s["posts"]) == (339, 134, 5, 0, 200, 2)


def test_parse_pricetable():
    text = "AHL1|forever/normal/horde/us|1791729297|3\n2589:25:18:12812:32:59:3:104:150794\n720:32000:31000:10:67756:78722:17900\n55:200:200:1::::1300:0\n"
    head, prices = ahledger.parse_pricetable(text)
    assert head == {"market": "forever.normal.horde.us", "ts": 1791729297, "rows": 3}
    linen = prices[2589]
    assert (linen.median, linen.min_buyout, linen.quantity, linen.median_7d, linen.median_30d) == (25, 18, 12812, 32, 59)
    assert (linen.low_30d, linen.high_30d, linen.sold_per_day) == (3, 104, 15079.4)
    assert prices[720].high_30d is None and prices[720].sold_per_day is None   # short line
    assert prices[55].median_7d is None and prices[55].sold_per_day == 0       # empty fields


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
