"""Offline tests: run the addon's Lua under a fake WoW API (tests/wow_stub.lua).

    .venv\\Scripts\\python tests\\test_addon.py

Proves the addon's own logic (chunking, aggregates, retention, dedup). It cannot prove that
the Forever client behaves like the stub - that is what T3-T6 in docs/07-test-plan.md are for.
"""
from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import savedvars  # noqa: E402

ADDON = ROOT / "addon" / "ForeverAH"


class Game:
    def __init__(self, unknown_events=()):
        self.lua = LuaRuntime(register_eval=False, register_builtins=False)
        self.lua.execute((ROOT / "tests" / "wow_stub.lua").read_text(encoding="utf-8"))
        self.g = self.lua.globals()
        for event in unknown_events:
            self.g.UNKNOWN_EVENTS[event] = True
        toc = (ADDON / "ForeverAH.toc").read_text(encoding="utf-8").splitlines()
        for name in (line.strip() for line in toc):
            if name and not name.startswith("#"):
                self.g.LoadAddonFile(name, (ADDON / name).read_text(encoding="utf-8"))
        self.fire("ADDON_LOADED", "ForeverAH")
        self.fire("PLAYER_LOGIN")

    def fire(self, event, *args):
        self.g.Fire(event, *args)

    def frames(self, n=1):
        for _ in range(n):
            self.g.Frame()

    def set_auctions(self, rows):
        self.g.AUCTIONS = self.lua.table_from([self.lua.table_from(r) for r in rows])

    def open_ah(self, reply=True):
        self.fire("AUCTION_HOUSE_SHOW")
        if reply:
            self.fire("REPLICATE_ITEM_LIST_UPDATE")
            self.frames(200)

    def close_ah(self):
        self.fire("AUCTION_HOUSE_CLOSED")

    def slash(self, msg):
        self.g.SlashCmdList.FOREVERAH(msg)

    def printed(self):
        return list(self.g.PRINTED.values())

    def db(self):
        """Round trip through a SavedVariables file and the pipeline parser."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ForeverAH.lua"
            path.write_text(self.g.Dump(), encoding="utf-8")
            return savedvars.load(path)

    def ledger(self):
        return savedvars.ledger_rows(self.db())


def make_auctions(n, n_items, seed=1):
    """[itemID, count, buyout, minBid, bid, hasAllInfo, timeLeft] - Linen 2589 in, Copper Ore 2770 out."""
    rng = random.Random(seed)
    ids = [2589] + [i for i in range(3000, 3000 + n_items) if i != 2770][: n_items - 1]
    base = {i: rng.randint(5, 2_000_000) for i in ids}
    rows = []
    for _ in range(n):
        item = rng.choice(ids)
        count = rng.choice([1, 1, 1, 5, 10, 20])
        unit = max(1, int(base[item] * rng.uniform(0.8, 1.6)))
        buyout = 0 if rng.random() < 0.05 else unit * count   # 5 % bid-only
        bid = unit * count // 2 if rng.random() < 0.1 else 0
        rows.append([item, count, buyout, max(1, unit * count // 2), bid, rng.random() > 0.02, rng.randint(1, 4)])
    return rows


def test_scan_saves_rows_and_aggregates():
    game = Game()
    auctions = make_auctions(12_345, 300)
    auctions.insert(100, [0, 1, 500, 100, 0, False, 1])   # no item id -> skipped
    game.set_auctions(auctions)
    game.open_ah()
    for _ in range(50):                                   # late item-cache events are ignored
        game.fire("REPLICATE_ITEM_LIST_UPDATE")
    game.frames(5)

    db = game.db()
    assert len(db["scans"]) == 1, game.printed()
    scan = db["scans"][0]
    expected = [tuple(a[:5]) for a in auctions if a[0]]
    assert savedvars.raw_rows(scan) == expected
    assert savedvars.agg_rows(scan) == savedvars.aggregate(expected)
    assert (scan["n"], scan["rows"], scan["skip"]) == (12_346, 12_345, 1)
    assert scan["miss"] == sum(1 for a in auctions if a[0] and not a[5])
    assert scan["items"] == len({a[0] for a in auctions if a[0]})
    assert scan["units"] == sum(a[1] for a in auctions if a[0])
    assert scan["frames"] >= 3                            # 12k rows / 5000 per frame
    assert sum(int(p.split(":")[1]) for p in scan["tl"].split(",")) == 12_345
    assert (scan["realm"], scan["faction"], scan["zone"]) == ("Beta Realm", "Horde", "Orgrimmar")
    assert db["lastScan"] == scan["ts"]
    out = "\n".join(game.printed())
    assert "Linen Cloth 2589:" in out and "Copper Ore 2770: NOT in scan" in out   # T5 answer is printed


def test_aggregate_definition():
    # 10 units @ 100, 10 @ 200, 20 @ 300, one bid-only stack of 5. Unit price = buyout / count.
    game = Game()
    game.set_auctions([
        [1, 10, 1000, 1, 0, True, 1],
        [1, 10, 2000, 1, 0, True, 1],
        [1, 20, 6000, 1, 0, True, 1],
        [1, 5, 0, 50, 0, True, 1],
        [2, 3, 0, 50, 0, True, 1],      # bid-only item
        [3, 200, 100, 1, 0, True, 1],   # 0.5 copper per unit -> 1
    ])
    game.open_ah()
    agg = savedvars.agg_rows(game.db()["scans"][0])
    assert agg[1] == (100, 100, 100, 200, 45, 4)   # min, p10, p25, median, qty, auctions
    assert agg[2] == (0, 0, 0, 0, 3, 1)
    assert agg[3] == (1, 1, 1, 1, 200, 1)
    game.slash("item 1")
    assert "min 100, p10 100, p25 100, median 200" in game.printed()[-1]


def test_throttle_and_retention():
    game = Game()
    game.set_auctions(make_auctions(500, 20))
    game.open_ah()
    assert game.g.REPLICATE_CALLS == 1

    game.close_ah()
    game.g.Advance(5 * 60)
    game.open_ah(reply=False)                # inside our own 15 min: no request at all
    assert game.g.REPLICATE_CALLS == 1
    assert "next scan in 10 min" in game.printed()[-1]

    game.slash("scan")                       # forced: server answers with an empty market
    game.fire("REPLICATE_ITEM_LIST_UPDATE")
    game.frames(5)
    db = game.db()
    assert game.g.REPLICATE_CALLS == 2
    assert len(db["scans"]) == 1 and db["throttled"] == 1
    assert "scan not saved: 0 rows" in game.printed()[-1]

    for _ in range(4):                       # four more real scans
        game.close_ah()
        game.g.Advance(15 * 60)
        game.open_ah()
    scans = game.db()["scans"]
    assert len(scans) == 5
    assert [bool(s.get("raw")) for s in scans] == [False, False, True, True, True]
    assert all(s["agg"] for s in scans)
    assert len({s["id"] for s in scans}) == 5


def test_abort_on_close_and_timeout():
    game = Game()
    game.set_auctions(make_auctions(20_000, 50))
    game.open_ah(reply=False)
    game.close_ah()                          # closed while waiting
    assert "AH closed during scan" in game.printed()[-1]

    game.g.Advance(15 * 60)                  # the aborted request still used up the server throttle
    game.open_ah(reply=False)
    game.fire("REPLICATE_ITEM_LIST_UPDATE")
    game.frames(1)
    game.close_ah()                          # closed while processing
    game.frames(200)
    assert "AH closed during scan" in game.printed()[-1]
    assert game.db()["scans"] == {}

    game.g.Advance(15 * 60)
    game.open_ah(reply=False)                # no reply ever
    game.g.Advance(121)
    game.frames(2)
    assert "no reply in 120 s" in game.printed()[-1]
    game.slash("scan")                       # state is clean again
    assert "requesting full scan" in game.printed()[-1]


def test_missing_events_do_not_break_the_addon():
    game = Game(unknown_events=["ITEM_PURCHASED", "COMMODITY_PURCHASED"])
    game.slash("")
    assert any("events missing in this client: " in p and "ITEM_PURCHASED" in p for p in game.printed())
    game.set_auctions(make_auctions(100, 5))
    game.open_ah()
    assert len(game.db()["scans"]) == 1


def test_ledger_posts_and_purchases():
    game = Game()
    ah = game.g.C_AuctionHouse
    ah.PostItem(game.lua.table_from({"id": 2589}), 1, 1, 400, 500)
    game.fire("AUCTION_HOUSE_AUCTION_CREATED", 111)
    ah.PostCommodity(game.lua.table_from({"id": 2770}), 2, 40, 25)
    game.fire("AUCTION_HOUSE_AUCTION_CREATED", 222)
    game.fire("AUCTION_CANCELED", 111)
    ah.PlaceBid(333, 9000)
    game.fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 333)
    game.fire("COMMODITY_PRICE_UPDATED", 30, 600)
    game.fire("COMMODITY_PURCHASED", 2770, 20)
    game.fire("PLAYER_LOGOUT")

    rows = game.ledger()
    assert [r["event"] for r in rows] == ["gold", "post", "post", "cancel", "bid", "buy_done", "buy_commodity", "gold"]
    assert all(r["char"] == "Tester-BetaRealm" for r in rows)
    post = rows[1]
    assert (post["kind"], post["item"], post["qty"], post["bid"], post["buyout"]) == ("item", 2589, 1, 400, 500)
    assert (post["auction"], post["dur"], post["dep"], post["seq"]) == (111, 1, 100, 1)
    assert (rows[2]["kind"], rows[2]["unit"], rows[2]["dep"], rows[2]["auction"]) == ("commodity", 25, 280, 222)
    assert rows[3]["auction"] == 111
    assert (rows[4]["auction"], rows[4]["total"]) == (333, 9000)
    assert (rows[6]["item"], rows[6]["qty"], rows[6]["unit"], rows[6]["total"]) == (2770, 20, 30, 600)
    assert rows[0]["copper"] == 123456 and rows[0]["at"] == "login"


def test_ledger_mail_is_logged_once():
    game = Game()
    now = game.g.GetServerTime()
    day = 86400

    def mail(**kw):
        return game.lua.table_from(kw)

    def open_mailbox():
        for _ in range(3):                   # the event comes in bursts
            game.fire("MAIL_INBOX_UPDATE")
        game.g.Advance(1)
        game.frames(1)

    sold = dict(subject="Auction successful: Linen Bag", money=950, invoice="seller", name="Linen Bag",
                bid=1000, buyout=1000, deposit=20, fee=50, count=1)
    bought = dict(subject="Auction won: Copper Ore", invoice="buyer", name="Copper Ore", item=2770,
                  bid=300, buyout=300, deposit=0, fee=0, count=20)
    game.g.INBOX = game.lua.table_from([
        mail(expires=now + 30 * day, **sold),
        mail(expires=now + 30 * day, **bought),
        mail(expires=now + 30 * day + 1, **bought),      # identical purchase one second later
        mail(subject="Auction expired: Rough Stone, Polished", expires=now + 29 * day,
             name="Rough Stone, Polished", item=2835, itemCount=7),
        mail(subject="Auction cancelled: Linen Cloth", expires=now + 29 * day, name="Linen Cloth", item=2589),
        mail(subject="Outbid on Wool Cloth", money=500, expires=now + 3 * day),
        mail(subject="Hello from a friend", expires=now + 3 * day),
    ])
    open_mailbox()
    rows = [r for r in game.ledger() if r["event"] != "gold"]
    assert [r["event"] for r in rows] == ["sold", "bought", "bought", "expired", "cancelled", "outbid"]
    assert (rows[0]["total"], rows[0]["fee"], rows[0]["dep"], rows[0]["money"], rows[0]["qty"]) == (1000, 50, 20, 950, 1)
    assert rows[0]["name"] == "Linen Bag" and "item" not in rows[0]
    assert (rows[1]["item"], rows[1]["qty"], rows[1]["total"]) == (2770, 20, 300)
    assert (rows[3]["item"], rows[3]["qty"], rows[3]["name"]) == (2835, 7, "Rough Stone, Polished")
    assert rows[5]["name"] == "Wool Cloth" and rows[5]["money"] == 500

    game.g.Advance(3600)                     # same mails an hour later: nothing new
    open_mailbox()
    game.g.table.remove(game.g.INBOX, 2)     # one of the twin purchases is taken
    open_mailbox()
    assert len(game.ledger()) == len(rows) + 1

    later = game.g.GetServerTime()
    game.g.table.insert(game.g.INBOX, mail(expires=later + 30 * day, **bought))   # a third, later purchase
    open_mailbox()
    assert [r["event"] for r in game.ledger()][-1] == "bought"
    assert len(game.ledger()) == len(rows) + 2

    game.g.Advance(31 * day)                 # expired mails are forgotten at next login
    game.fire("PLAYER_LOGIN")
    assert game.db()["mailSeen"] == {}


def test_launch_size_budget():
    """docs/04 plans for 150k auctions / 6k items per house. T4 limits: < 10 MB raw, parse < 10 s."""
    game = Game()
    auctions = make_auctions(150_000, 6_000)
    game.set_auctions(auctions)
    game.open_ah()
    text = game.g.Dump()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ForeverAH.lua"
        path.write_text(text, encoding="utf-8")
        t = time.perf_counter()
        db = savedvars.load(path)
        parse_s = time.perf_counter() - t
    scan = db["scans"][0]
    raw_mb = sum(len(c) for c in scan["raw"]) / 1e6
    agg_mb = sum(len(c) for c in scan["agg"]) / 1e6
    print(f"  150k auctions / 6k items: file {len(text) / 1e6:.1f} MB (raw {raw_mb:.1f}, agg {agg_mb:.2f}), "
          f"{scan['frames']} frames, python parse {parse_s:.2f} s")
    assert scan["rows"] == 150_000 and scan["items"] == len({a[0] for a in auctions})
    assert savedvars.agg_rows(scan) == savedvars.aggregate(savedvars.raw_rows(scan))
    assert raw_mb < savedvars.MAX_RAW_MB and parse_s < savedvars.MAX_PARSE_S


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
