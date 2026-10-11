"""Tests for pipeline/analytics.py and pipeline/ahledger.py (no network).

    .venv/Scripts/python tests/test_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import ahledger, analytics, houses, news, planfile, planner, savedvars  # noqa: E402

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

    # Added 2026-10-11: two characters in one ledger. The gatherer mails 50c to the trader.
    ledger = [{"char": "Bank", "event": "gold", "copper": 1000}, {"char": "Main", "event": "gold", "copper": 300},
              {"char": "Main", "event": "gold", "copper": 250},
              {"char": "Bank", "event": "post"}, {"char": "Bank", "event": "money", "copper": 950, "delta": -100},
              {"char": "Bank", "event": "sold", "total": 400, "fee": 20}, {"char": "Bank", "event": "gold", "copper": 1330}]
    s = analytics.ledger_summary(ledger)
    assert s["chars"]["Bank"] == {"posts": 1, "bought": 0, "sold": 380, "first": 1000, "last": 1330, "other": 50}
    assert s["chars"]["Main"]["last"] == 250 and s["chars"]["Main"]["other"] == 50
    assert (s["first"], s["last"], s["sold"], s["other"]) == (1300, 1580, 380, 100)


def test_parse_pricetable():
    text = "AHL1|forever/normal/horde/us|1791729297|3\n2589:25:18:12812:32:59:3:104:150794\n720:32000:31000:10:67756:78722:17900\n55:200:200:1::::1300:0\n"
    head, prices = ahledger.parse_pricetable(text)
    assert head == {"market": "forever.normal.horde.us", "ts": 1791729297, "rows": 3}
    linen = prices[2589]
    assert (linen.median, linen.min_buyout, linen.quantity, linen.median_7d, linen.median_30d) == (25, 18, 12812, 32, 59)
    assert (linen.low_30d, linen.high_30d, linen.sold_per_day) == (3, 104, 15079.4)
    assert prices[720].high_30d is None and prices[720].sold_per_day is None   # short line
    assert prices[55].median_7d is None and prices[55].sold_per_day == 0       # empty fields
    # A house nobody has scanned yet (EU before launch): valid header, no rows.
    assert ahledger.parse_pricetable("AHL1|forever/normal/horde/eu|1791734573|0\n") == (
        {"market": "forever.normal.horde.eu", "ts": 1791734573, "rows": 0}, {})


def test_two_accounts_merge_into_one_table():
    main = {"scans": [{"id": "100:R:Horde", "ts": 100}, {"id": "300:R:Horde", "ts": 300}], "trader": "Bank-R",
            "ledger": ["100,Bank-R,gold,copper=5,at=login", "300,Bank-R,post,auction=1"],
            "inv": {"Bank-R": {"bags": "1:2"}}, "items": "1\t5\t20\t7\t5\tLinen Cloth\n", "errors": {}, "build": "1.60.1"}
    mage = {"scans": [{"id": "200:R:Horde", "ts": 200}, {"id": "300:R:Horde", "ts": 300}],
            "ledger": ["200,Mage-R,gold,copper=9,at=login"], "inv": {"Mage-R": {"bags": "2:1"}},
            "items": "1\t5\t20\t7\t5\tLinen Cloth\n2\t0\t1\t0\t0\tConjured Water\n", "errors": ["x"], "throttled": 2}
    db = savedvars.merge([main, mage])
    assert [s["ts"] for s in db["scans"]] == [100, 200, 300]          # by time, the shared scan once
    assert [row.split(",")[1] for row in db["ledger"]] == ["Bank-R", "Mage-R", "Bank-R"]
    assert sorted(db["inv"]) == ["Bank-R", "Mage-R"] and db["trader"] == "Bank-R"
    assert sorted(savedvars.items(db)) == [1, 2] and db["errors"] == ["x"] and db["throttled"] == 2
    assert savedvars.merge([main]) is main


def test_plan_file_is_valid_lua():
    import tempfile
    from lupa.lua51 import LuaRuntime
    labels = {"sell": "Sell", "keep": "Keep collecting", "repost": "Repost", "buy": "Buy", "short": "Over budget"}
    names = {2770: "Copper Ore", 9: 'Odd "name" with \\ and\nnewline'}
    plan = planfile.make(
        scan_ts=1791750584, labels=labels, name=names.get,
        sells=[{"action": "sell", "item_id": 2770, "units": 120, "price": 141, "net": 15974.0, "why": "Supply is tight."},
               {"action": "keep", "item_id": 9, "units": 3, "price": 8, "net": -77.2, "why": "Too small."}],
        reposts=[{"action": "repost", "item_id": 2770, "units": 40, "price": 190, "cheapest": None, "why": "Undercut."}],
        buys=[{"item_id": 2770, "units": 30, "max_price": 98, "cost": 2400.0, "profit": 600.5, "affordable": False, "why": "Cheap."}],
        books={2770: [(141, 10), (150, 5)], 9: [(8, 1)]}, headline="Launch week, day 2 of 7", mode="launch")
    with tempfile.TemporaryDirectory() as tmp:
        text = planfile.write(plan, Path(tmp) / planfile.NAME).read_text(encoding="utf-8")
    lua = LuaRuntime(register_eval=False, register_builtins=False)
    lua.execute(text)
    got = lua.globals().ForeverAH_Plan
    assert (got.mode, got.headline, got.scan) == ("launch", "Launch week, day 2 of 7", 1791750584)
    assert (got.sell[1].act, got.sell[1].item, got.sell[1].units, got.sell[1].price, got.sell[1].get) == ("Sell", "Copper Ore", 120, 141, 15974)
    assert got.sell[2].item == names[9] and got.sell[2].get == 0          # quotes, backslash and newline survive
    assert (got.auctions[1].act, got.auctions[1].cheapest) == ("Repost", 0)
    assert (got.buy[1].act, got.buy[1].max, got.buy[1].profit) == ("Over budget", 98, 600)
    assert got.min[2770] == 141 and got.min[9] == 8 and got.act[2770] == "Sell" and got.act[9] == "Keep collecting"
    assert planfile.lua({"a b": [1, 2.5, True, None], 3: {}}) == '{\n  ["a b"] = {\n    1,\n    2.5,\n    true,\n    nil,\n  },\n  [3] = {},\n}'


def test_houses():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "houses.yaml"
        cfg.write_text('tracked: [forever.normal.horde.eu, forever.normal.alliance.eu]\n'
                       'realms:\n  "Classic Beta PvE": {ruleset: normal, region: us}\n', encoding="utf-8")
        assert houses.tracked(cfg) == ["forever.normal.horde.eu", "forever.normal.alliance.eu"]
        assert houses.house_id("Classic Beta PvE", "Horde", cfg) == "forever.normal.horde.us"
        assert houses.house_id("Classic Beta PvE", "Alliance", cfg) == "forever.normal.alliance.us"
        assert houses.house_id("Some EU Realm", "Horde", cfg) is None      # not known until launch
        assert houses.house_id("Classic Beta PvE", "?", cfg) is None
    assert "forever.normal.horde.eu" in houses.tracked() and "forever.normal.alliance.eu" in houses.tracked()


def price(median_7d, sold):
    return ahledger.Price(median_7d, median_7d, 0, median_7d, None, None, None, sold)


def test_planner_sell_rules():
    books = {
        1: [(130, 500), (140, 500)],     # 30 % above its 7-day median
        2: [(100, 40)],                  # 40 listed, 1,000 sold a day: tight
        3: [(70, 5000)],                 # 30 % under its 7-day median
        4: [(100, 5000)],                # at its normal price
        5: [(17, 9000)],                 # held lot too small to post
    }
    ahl = {1: price(100, 10), 2: price(100, 1000), 3: price(100, 10), 4: price(100, 10), 5: price(17, 5000)}
    held = {1: 100, 2: 100, 3: 100, 4: 100, 5: 13, 6: 50}
    recs = {r["item_id"]: r for r in planner.sell(held, books, ahl)}
    assert [recs[i]["action"] for i in (1, 2, 3, 4, 5, 6)] == ["sell", "sell", "hold", "sell", "keep", "price"]
    assert "30% above" in recs[1]["why"] and "Supply is tight" in recs[2]["why"] and "30% under" in recs[3]["why"]
    assert "worth 2s 21c" in recs[5]["why"] and "post costs 1s 00c" in recs[5]["why"]
    assert recs[1]["net"] == 100 * 130 * 0.95 - 100
    assert [r["action"] for r in planner.sell(held, books, ahl)] == ["sell", "sell", "sell", "hold", "keep", "price"]
    launch = {r["item_id"]: r for r in planner.sell(held, books, ahl, phase="sell_to_levelers")}
    assert launch[3]["action"] == "sell" and "launch week" in launch[3]["why"]

    # Added 2026-10-11: a fresh market has no history. The reason must say so, not invent a level.
    fresh = {r["item_id"]: r for r in planner.sell({4: 100}, books, {})}
    assert fresh[4]["action"] == "sell" and "No price history" in fresh[4]["why"] and "7-day" not in fresh[4]["why"]
    fresh = {r["item_id"]: r for r in planner.sell({4: 100}, books, {}, phase="sell_to_levelers")}
    assert "Launch week" in fresh[4]["why"]


def test_planner_repost_and_buy():
    books = {1: [(100, 500)], 2: [(100, 500)], 3: [(10, 50)]}
    mine = [{"item": 1, "qty": 50, "buyout": 104, "status": 0, "seconds": 3600},    # within 5 %
            {"item": 2, "qty": 50, "buyout": 150, "status": 0, "seconds": 7200},    # undercut
            {"item": 3, "qty": 5, "buyout": 30, "status": 0, "seconds": 7200},      # undercut, tiny lot
            {"item": 2, "qty": 50, "buyout": 150, "status": 1, "seconds": 0}]       # already sold
    recs = planner.repost(mine, books)
    assert [(r["item_id"], r["action"]) for r in recs] == [(2, "repost"), (1, "leave"), (3, "leave")]
    assert "Undercut by 50%" in recs[0]["why"] and recs[0]["hours"] == 2

    # Changed 2026-10-11: flips under 10s are dropped, so item 1's lot grew and item 3 was added.
    # books = {1: [(100, 10), (200, 10), (300, 20)], 2: [(10, 40), (200, 100), (210, 100)]}
    # ahl = {1: price(200, 100), 2: price(200, 1000)}
    books = {1: [(100, 20), (200, 10), (300, 20)], 2: [(10, 40), (200, 100), (210, 100)], 3: [(15, 1), (140, 9), (150, 9)]}
    ahl = {1: price(200, 100), 2: price(200, 1000), 3: price(140, 8000)}
    deals = planner.buy(books, ahl, balance=500)
    assert [(d["item_id"], d["affordable"]) for d in deals] == [(2, True), (1, False)]   # affordable first; item 3 earns 18c
    assert deals[0]["max_price"] == 140 and "40 units" in deals[0]["why"]


def test_launch_mode_rules():
    """Week one: no 7-day prices. Vendor floor, deposit, trend since the last scan, and the playbook."""
    books = {
        1: [(90, 500)],        # was 120: falling, and supply has grown
        2: [(150, 500)],       # was 100: rising
        3: [(100, 500)],       # steady
        4: [(100, 500)],       # no earlier scan
        5: [(20, 500)],        # a vendor pays 19: the AH would leave less
        6: [(17, 9000)],       # lot too small to post
        7: [(300, 500)],       # watchlist says it is wanted at 60
    }
    prev = {1: [(120, 200)], 2: [(100, 500)], 3: [(101, 480)], 5: [(20, 500)], 6: [(17, 9000)], 7: [(300, 500)]}
    held = {1: 100, 2: 100, 3: 100, 4: 100, 5: 100, 6: 13, 7: 100, 8: 5}
    recs = {r["item_id"]: r for r in planner.sell_launch(held, books, prev, {5: 19, 6: 2, 8: 40}, {7: "stock_while_leveling"})}
    assert [recs[i]["action"] for i in range(1, 9)] == ["sell", "sell", "sell", "sell", "vendor", "keep", "choice", "price"]
    assert "fell 25%" in recs[1]["why"] and "supply grew 150%" in recs[1]["why"]
    assert "rose 50%" in recs[2]["why"] and "steady" in recs[3]["why"] and "No earlier scan" in recs[4]["why"]
    assert "vendor pays 19c each" in recs[5]["why"] and "leave 18c each" in recs[5]["why"] and recs[5]["net"] == 1900
    assert "vendor it for 26c" in recs[6]["why"] and "level 60" in recs[7]["why"]
    assert "vendor pays 40c" in recs[8]["why"]                      # no listings, but a floor is known
    assert not any("7-day" in r["why"] for r in recs.values())      # nothing claims a history

    assert planner.launch_mode("sell_to_levelers", books, {}) is True
    assert planner.launch_mode(None, books, {}) is True             # a fresh market without a date
    history = {i: price(100, 10) for i in books}
    assert planner.launch_mode(None, books, history) is False and planner.launch_mode("levelers_to_60", books, history) is False


def test_below_vendor_lots():
    books = {1: [(10, 40), (30, 10), (60, 100)], 2: [(48, 3)], 3: [(5, 10)]}
    lots = planner.below_vendor(books, {1: 50, 2: 50}, balance=500)
    assert [(d["item_id"], d["units"], d["cost"], d["max_price"], d["profit"], d["affordable"]) for d in lots] == [
        (1, 50, 700, 30, 1800, False)]                              # item 2 would earn 6c: not worth the walk
    assert planner.below_vendor(books, {}) == []                    # no vendor prices, no suggestions


def test_planner_calendar():
    import datetime as dt
    plan = {"events": [{"id": "beta_end", "start": dt.datetime(2026, 10, 22, 6), "note": "Beta ends."},
                       {"id": "launch", "start": dt.datetime(2026, 11, 5)},
                       {"id": "name_reservation", "start": dt.date(2026, 10, 27)},
                       {"id": "hardcore", "start": None}],
            "phases": [{"id": "sell_to_levelers", "from": "launch", "days": 7, "focus": "Sell raw mats."},
                       {"id": "levelers_to_60", "from_date": dt.date(2026, 11, 12), "to_date": dt.date(2026, 12, 1)}]}
    before = planner.calendar(plan, dt.date(2026, 10, 11))
    assert before["phase"] is None
    assert [(e["id"], e["days"]) for e in before["upcoming"]] == [("beta_end", 11), ("name_reservation", 16), ("launch", 25)]
    assert planner.calendar(plan, dt.date(2026, 11, 6))["phase"]["id"] == "sell_to_levelers"
    assert planner.calendar(plan, dt.date(2026, 11, 6))["phase_day"] == 2 and before["phase_day"] is None
    assert planner.calendar(plan, dt.date(2026, 11, 20))["phase"]["id"] == "levelers_to_60"
    assert planner.calendar(plan, dt.date(2026, 12, 5))["phase"] is None


FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Wowhead News</title>
<item><title>Crafted Wand Sell Prices Partially Un-Nerfed in Latest Forever Build</title>
<link>https://example.test/news=1/wands</link><pubDate>Thu, 08 Oct 2026 17:13:00 -0500</pubDate>
<description><![CDATA[<p>After nerfing all crafted <b>Enchanting</b> wands, Blizzard un-nerfed them. Continue reading \u00bb</p>]]></description></item>
<item><title>Linen Cloth Drop Rates Doubled</title><link>https://example.test/news=2/linen</link>
<pubDate>Fri, 09 Oct 2026 10:00:00 -0500</pubDate><description>More cloth for everyone.</description></item>
<item><title>How Does Elemental Shaman Look in WoW: Forever?</title><link>https://example.test/news=3/shaman</link>
<pubDate>Fri, 09 Oct 2026 15:03:00 -0500</pubDate><description>A look at the class before launch.</description></item>
<item><title>Wolfshead Helm Nerfed</title><link>https://example.test/news=4/helm</link>
<pubDate>Fri, 09 Oct 2026 19:58:00 -0500</pubDate><description>Now weaker.</description></item>
</channel></rss>"""


def test_news_parse_flag_pending():
    import datetime as dt
    import tempfile
    stories = news.parse_feed(FEED)
    assert [s["link"][-5:] for s in stories] == ["wands", "linen", "haman", "/helm"]
    assert stories[0]["published"] == "2026-10-08T22:13:00+00:00"
    assert stories[0]["summary"] == "After nerfing all crafted Enchanting wands, Blizzard un-nerfed them."   # tags and the tail gone

    names = ["Linen Cloth", "Copper Ore"]
    assert news.flag(stories[0], names) == ["prices: sell prices", "crafting: crafted, enchanting", "balance: nerfing, un-nerfed"]
    assert news.flag(stories[1], names) == ["item: Linen Cloth", "supply: drop rates"]
    assert news.flag(stories[2], names) == []        # "ore" inside "Forever" and "before" is not a match
    assert news.flag(stories[3], names) == ["balance: nerfed"]

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "news-log.yaml"
        day = dt.date(2026, 10, 11)
        assert [s["link"][-5:] for s in news.flagged(stories, names, log=log, today=day)] == ["linen", "wands", "/helm"]
        assert [s["link"][-5:] for s in news.pending(stories, names, log=log, today=day)] == ["linen", "wands"]   # helm is weak
        log.write_text("reviewed:\n  - {link: 'https://example.test/news=2/linen', verdict: relevant}\n", encoding="utf-8")
        assert [s["link"][-5:] for s in news.pending(stories, names, log=log, today=day)] == ["wands"]
        assert news.pending(stories, names, log=log, today=dt.date(2026, 11, 30)) == []   # older than 14 days


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
