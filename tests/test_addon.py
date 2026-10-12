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
    # Changed 2026-10-11: broken_widget added, to test the chat fallback of UI.lua.
    # def __init__(self, unknown_events=()):
    # def __init__(self, unknown_events=(), broken_widget=None):   (2026-10-11: player_name added)
    # def __init__(self, unknown_events=(), broken_widget=None, player_name="Tester"):
    # (2026-10-11: no_templates and no_minimap added, for the UI's fallback looks)
    # (2026-10-11, v0.8: plan = the text of a generated ForeverAH_Plan.lua, loaded instead of the placeholder)
    def __init__(self, unknown_events=(), broken_widget=None, player_name="Tester", no_templates=False,
                 no_minimap=False, plan=None):
        self.lua = LuaRuntime(register_eval=False, register_builtins=False)
        self.lua.execute((ROOT / "tests" / "wow_stub.lua").read_text(encoding="utf-8"))
        self.g = self.lua.globals()
        self.g.BROKEN_WIDGET = broken_widget
        self.g.PLAYER_NAME = player_name
        self.g.NO_TEMPLATES = no_templates
        if no_minimap:
            self.lua.execute("Minimap = nil")
        for event in unknown_events:
            self.g.UNKNOWN_EVENTS[event] = True
        toc = (ADDON / "ForeverAH.toc").read_text(encoding="utf-8").splitlines()
        for name in (line.strip() for line in toc):
            if name and not name.startswith("#"):
                # self.g.LoadAddonFile(name, (ADDON / name).read_text(encoding="utf-8"))
                source = plan if plan and name == "ForeverAH_Plan.lua" else (ADDON / name).read_text(encoding="utf-8")
                self.g.LoadAddonFile(name, source)
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
    game.slash("debug")                                   # 2026-10-11: the T5 lines are diagnostics now
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
    # Changed 2026-10-11 (D15): the time-left band is saved as a 6th field.
    # expected = [tuple(a[:5]) for a in auctions if a[0]]
    expected = [tuple(a[:5]) + (a[6],) for a in auctions if a[0]]
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

    # Changed 2026-10-11 (beta T3): build 70338 stays silent when throttled - no event at all.
    # The empty-reply path is kept and still covered below.
    # game.slash("scan")                       # forced: server answers with an empty market
    # game.fire("REPLICATE_ITEM_LIST_UPDATE")
    # game.frames(5)
    # db = game.db()
    # assert game.g.REPLICATE_CALLS == 2
    # assert len(db["scans"]) == 1 and db["throttled"] == 1
    # assert "scan not saved: 0 rows" in game.printed()[-1]
    game.slash("scan")                       # forced inside the server's 15 min: no reply
    assert "server will probably ignore" in game.printed()[-2]
    game.g.Advance(121)
    game.frames(2)
    assert game.g.REPLICATE_CALLS == 2
    assert "no reply in 120 s - throttled" in game.printed()[-1]
    assert len(game.db()["scans"]) == 1

    game.slash("scan")                       # an empty reply is not saved either
    game.fire("REPLICATE_ITEM_LIST_UPDATE")
    game.frames(5)
    db = game.db()
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
    # assert "requesting full scan" in game.printed()[-1]   (2026-10-11: reworded)
    assert "Scanning the auction house" in game.printed()[-1]


def test_missing_events_do_not_break_the_addon():
    # Changed 2026-10-11: the ledger no longer listens to COMMODITY_PURCHASED, so use another event.
    # game = Game(unknown_events=["ITEM_PURCHASED", "COMMODITY_PURCHASED"])
    # Changed 2026-10-11 (beta run 2): AUCTION_CANCELED is gone too. Compare as a set so the test
    # stops depending on which events the ledger happens to register, and in what order.
    # game = Game(unknown_events=["ITEM_PURCHASED", "AUCTION_CANCELED"])
    game = Game(unknown_events=["ITEM_PURCHASED", "AUCTION_HOUSE_PURCHASE_COMPLETED"])
    game.slash("")
    assert any("events missing in this client: " in p and "ITEM_PURCHASED" in p for p in game.printed())
    # assert game.db()["missing"] == "COMMODITY_PURCHASED,ITEM_PURCHASED"
    # assert game.db()["missing"] == "AUCTION_CANCELED,ITEM_PURCHASED"
    assert set(game.db()["missing"].split(",")) == {"ITEM_PURCHASED", "AUCTION_HOUSE_PURCHASE_COMPLETED"}
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
    # Changed 2026-10-11 (beta T6): cancel and commodity purchase are taken from the player's click.
    # The events behave as seen in build 70338: AUCTION_CANCELED without the auction id,
    # no COMMODITY_PURCHASED, AUCTION_HOUSE_PURCHASE_COMPLETED with 0.
    # game.fire("AUCTION_CANCELED", 111)
    # ah.PlaceBid(333, 9000)
    # game.fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 333)
    # game.fire("COMMODITY_PRICE_UPDATED", 30, 600)
    # game.fire("COMMODITY_PURCHASED", 2770, 20)
    # game.fire("PLAYER_LOGOUT")
    #
    # rows = game.ledger()
    # assert [r["event"] for r in rows] == ["gold", "post", "post", "cancel", "bid", "buy_done", "buy_commodity", "gold"]
    ah.CancelAuction(111)
    game.fire("AUCTION_CANCELED", 114)
    ah.PlaceBid(333, 9000)
    game.fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 333)
    game.fire("COMMODITY_PRICE_UPDATED", 30, 600)
    ah.ConfirmCommoditiesPurchase(2770, 20)
    game.fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 0)
    game.fire("PLAYER_LOGOUT")

    rows = game.ledger()
    # Changed 2026-10-11 (beta run 2): AUCTION_CANCELED is no longer logged (cancel_evt was noise).
    # assert [r["event"] for r in rows] == ["gold", "post", "post", "cancel", "cancel_evt", "bid", "buy_done",
    #                                       "buy_commodity", "buy_done", "gold"]
    assert [r["event"] for r in rows] == ["gold", "post", "post", "cancel", "bid", "buy_done",
                                          "buy_commodity", "buy_done", "gold"]
    assert all(r["char"] == "Tester-BetaRealm" for r in rows)
    post = rows[1]
    assert (post["kind"], post["item"], post["qty"], post["bid"], post["buyout"]) == ("item", 2589, 1, 400, 500)
    assert (post["auction"], post["dur"], post["dep"], post["seq"]) == (111, 1, 100, 1)
    assert (rows[2]["kind"], rows[2]["unit"], rows[2]["dep"], rows[2]["auction"]) == ("commodity", 25, 280, 222)
    # assert rows[3]["auction"] == 111
    # assert (rows[4]["auction"], rows[4]["total"]) == (333, 9000)
    # assert (rows[6]["item"], rows[6]["qty"], rows[6]["unit"], rows[6]["total"]) == (2770, 20, 30, 600)
    assert (rows[3]["auction"], rows[3]["cost"]) == (111, 3)
    # assert rows[4]["arg"] == 114
    # assert (rows[5]["auction"], rows[5]["total"]) == (333, 9000)
    # assert (rows[7]["item"], rows[7]["qty"], rows[7]["unit"], rows[7]["total"]) == (2770, 20, 30, 600)
    assert (rows[4]["auction"], rows[4]["total"]) == (333, 9000)
    assert (rows[6]["item"], rows[6]["qty"], rows[6]["unit"], rows[6]["total"]) == (2770, 20, 30, 600)
    assert rows[0]["copper"] == 123456 and rows[0]["at"] == "login"


def test_ledger_money_rows():
    """Beta run 2: 1s was charged per post where the API estimated 0-8c; quitting logged 0 gold."""
    game = Game()
    game.fire("AUCTION_HOUSE_SHOW")
    game.g.SetMoney(123356)                  # deposit taken
    game.g.SetMoney(123356)                  # event without a change
    game.fire("AUCTION_HOUSE_CLOSED")
    game.g.SetMoney(123400)                  # looting in the world: not ours to log
    game.fire("MAIL_SHOW")
    game.g.SetMoney(124350)                  # sale collected
    game.fire("MAIL_CLOSED")
    game.g.MONEY = 0                         # the client reports 0 while quitting
    game.fire("PLAYER_LOGOUT")

    rows = game.ledger()
    assert [r["event"] for r in rows] == ["gold", "money", "money", "gold"]
    assert (rows[1]["copper"], rows[1]["delta"], rows[1]["at"]) == (123356, -100, "ah")
    assert (rows[2]["copper"], rows[2]["delta"], rows[2]["at"]) == (124350, 950, "mail")
    assert (rows[3]["copper"], rows[3]["at"]) == (124350, "logout")


def test_login_without_a_name_and_failing_handlers():
    """Beta 2026-10-11: a new character's first login left a '?' row and skipped later handlers."""
    game = Game(player_name=None)            # the name is not there yet at PLAYER_LOGIN
    assert list(game.g.ERRORS.values()) == []
    game.fire("PLAYER_LOGOUT")               # a session that ends before the name ever arrives
    assert game.ledger() == []               # no '?' row, no made-up 0 copper

    game = Game(player_name=None)
    game.g.PLAYER_NAME = "Shym"
    game.fire("PLAYER_ENTERING_WORLD")       # the name arrives with the world
    game.g.SetMoney(500)
    game.fire("PLAYER_LOGOUT")
    rows = game.ledger()
    assert [(r["char"], r["event"], r["copper"]) for r in rows] == [("Shym-BetaRealm", "gold", 500)]

    game = Game()                            # one handler raising must not stop the rest
    game.lua.execute("GetBuildInfo = function() error('boom') end")
    game.fire("PLAYER_LOGIN")
    assert [r["at"] for r in game.ledger()] == ["login", "login"]          # the ledger's handler still ran
    assert "PLAYER_LOGIN" in game.db()["errors"][0] and "boom" in game.db()["errors"][0]
    assert len(game.g.ERRORS) == 1           # and the game's error display was told


def test_item_reference_is_built_from_scans():
    game = Game()
    game.set_auctions([[2589, 20, 400, 0, 0, True, 3], [2770, 10, 1500, 0, 0, True, 3], [4306, 5, 2000, 0, 0, False, 2]])
    info = game.lua.table_from
    game.g.ITEM_INFO = info({2589: info(["Linen Cloth", 13, 200, 7, 5]), 2770: info(["Copper Ore", 5, 200, 7, 7])})
    game.open_ah()
    ref = savedvars.items(game.db())
    # Changed 2026-10-11 (v0.9): the reference also has quality and item level.
    # assert ref == {2589: {"name": "Linen Cloth", "vendor": 13, "stack": 200, "class_id": 7, "subclass_id": 5},
    #                2770: {"name": "Copper Ore", "vendor": 5, "stack": 200, "class_id": 7, "subclass_id": 7}}
    assert ref == {2589: {"name": "Linen Cloth", "vendor": 13, "stack": 200, "class_id": 7, "subclass_id": 5, "quality": 1, "level": 10},
                   2770: {"name": "Copper Ore", "vendor": 5, "stack": 200, "class_id": 7, "subclass_id": 7, "quality": 1, "level": 10}}
    assert any("item reference: 2 new items" in p for p in game.printed())

    # Changed 2026-10-11 (beta run 3): no second scan needed any more - the reference is filled
    # in again 20 s after the scan and when the AH closes, as the client finishes loading items.
    # game.g.ITEM_INFO[4306] = info(["Silk Cloth", 150, 200, 7, 5])   # the client has loaded it by now
    # game.close_ah()
    # game.g.Advance(15 * 60)
    # game.open_ah()
    # ref = savedvars.items(game.db())
    # assert sorted(ref) == [2589, 2770, 4306] and ref[4306]["vendor"] == 150
    game.g.ITEM_INFO[4306] = info(["Silk Cloth", 150, 200, 7, 5])   # the client has loaded it by now
    game.g.Advance(20)
    game.frames(3)
    ref = savedvars.items(game.db())
    assert sorted(ref) == [2589, 2770, 4306] and ref[4306]["vendor"] == 150
    game.set_auctions([[2589, 20, 400, 0, 0, True, 3], [118, 1, 10, 0, 0, False, 1]])
    game.g.Advance(15 * 60)
    game.fire("AUCTION_HOUSE_CLOSED")
    game.open_ah()                                                   # a new scan with one new item
    assert 118 not in savedvars.items(game.db())
    game.g.ITEM_INFO[118] = info(["Minor Healing Potion", 5, 5, 0, 1])
    game.close_ah()                                                  # closing the AH looks again
    game.frames(3)
    assert savedvars.items(game.db())[118]["vendor"] == 5
    assert game.db()["items"].count("Linen Cloth") == 1               # known items are not written twice
    assert "errors" not in game.db() or game.db()["errors"] == {}


def test_old_item_reference_is_rebuilt_once():
    """Lines saved before v0.9 have no quality or item level: dropped once, collected again."""
    game = Game()
    game.lua.execute('ForeverAHDB.items = "2589\\t13\\t200\\t7\\t5\\tLinen Cloth\\n"')
    info = game.lua.table_from
    game.g.ITEM_INFO = info({2589: info(["Linen Cloth", 13, 200, 7, 5, 1, 5])})
    game.set_auctions([[2589, 20, 400, 0, 0, True, 3]])
    game.open_ah()
    db = game.db()
    assert db["itemsV"] == 2 and db["items"].count("Linen Cloth") == 1
    assert savedvars.items(db)[2589] == {"name": "Linen Cloth", "vendor": 13, "stack": 200, "class_id": 7,
                                         "subclass_id": 5, "quality": 1, "level": 5}
    # the parser still reads a file that has the old lines
    assert savedvars.items({"items": "2589\t13\t200\t7\t5\tLinen Cloth\n"})[2589]["name"] == "Linen Cloth"


def test_recipes_are_read_from_the_profession_window():
    game = Game()
    rec = game.lua.table_from
    game.g.RECIPES = rec([
        rec({"id": 3915, "name": "Linen Bag", "learned": True, "output": 4238, "cooldown": 0,
             "reagents": rec([rec([2996, 3]), rec([2320, 3]), rec([9999, 1, 2])])}),      # third one is optional: left out
        rec({"id": 2385, "name": "Brown Linen Vest", "learned": False, "output": 2568, "reagents": rec([rec([2996, 1])])}),
        rec({"id": 18560, "name": "Mooncloth", "learned": True, "output": 14342, "min": 1, "max": 1, "cooldown": 7200.4,
             "reagents": rec([rec([14256, 2])])}),
        rec({"id": 7421, "name": "Runed Copper Rod", "learned": True, "reagents": rec([rec([6217, 1])])}),   # makes no item
    ])
    game.fire("TRADE_SKILL_SHOW")
    for _ in range(4):                                   # the list update comes in bursts
        game.fire("TRADE_SKILL_LIST_UPDATE")
    game.g.Advance(1)
    game.frames(1)
    recipes = savedvars.recipes(game.db())
    assert [(r["name"], r["item_id"], r["reagents"], r["cooldown"]) for r in recipes] == [
        ("Linen Bag", 4238, {2996: 3, 2320: 3}, 0), ("Mooncloth", 14342, {14256: 2}, 7200), ("Runed Copper Rod", 0, {6217: 1}, 0)]
    assert {(r["char"], r["profession"], r["skill"]) for r in recipes} == {("Tester-BetaRealm", "Tailoring", 75)}
    assert sum("Tailoring: 3 recipes saved" in p for p in game.printed()) == 1   # said once, not on every update

    game.fire("TRADE_SKILL_LIST_UPDATE")                 # nothing changed: nothing said
    game.g.Advance(1)
    game.frames(1)
    assert sum("recipes saved" in p for p in game.printed()) == 1

    game.g.TRADESKILL_LINKED = True                      # someone else's linked profession is not ours
    game.g.PROFESSION = rec({"professionName": "Alchemy", "skillLevel": 300, "maxSkillLevel": 300})
    game.fire("TRADE_SKILL_SHOW")
    game.g.Advance(1)
    game.frames(1)
    assert {r["profession"] for r in savedvars.recipes(game.db())} == {"Tailoring"}
    assert "errors" not in game.db() or game.db()["errors"] == {}


# Changed 2026-10-12 (beta run 4): a missing modern API is no longer an error - the Classic APIs
# are tried, and every attempt leaves a probe line saying what each one answered.
# def test_recipe_api_missing_is_recorded_once():
#     game = Game()
#     game.lua.execute("C_TradeSkillUI.GetRecipeSchematic = nil")
#     for _ in range(3):
#         game.fire("TRADE_SKILL_SHOW")
#         game.g.Advance(1)
#         game.frames(1)
#     errors = game.db()["errors"]
#     assert len(errors) == 1 and "recipes" in errors[0] and "missing" in errors[0]
def test_recipe_probe_says_what_each_api_answered():
    game = Game()                                        # a profession window with nothing in it yet
    game.fire("TRADE_SKILL_SHOW")
    # Changed 2026-10-12 (beta run 5): the probe is a short history, and says where the name came from.
    # probe = game.db()["probe"]["recipes"]
    # assert "TRADE_SKILL_SHOW | modern: profession=Tailoring id=nil recipes=0 learned=0 | classic: no API | craft: no API" in probe
    probe = game.db()["probe"]["recipes"][-1]
    assert "TRADE_SKILL_SHOW | modern: profession=Tailoring (from base) id=nil recipes=0 learned=0 | classic: no API | craft: no API" in probe
    assert game.db()["recipes"] == {} and game.db()["errors"] == {}
    game.slash("recipes")                                # the same line on request
    assert "/fah recipes | modern: profession=Tailoring" in game.printed()[-1]
    for _ in range(12):
        game.slash("recipes")
    assert len(game.db()["probe"]["recipes"]) == 8       # the last eight are kept


def test_profession_name_comes_from_whoever_has_one():
    """Beta run 5: 261 recipes, 5 learned, and an empty name from the child-profession call."""
    def tailor(**stub):
        game = Game()
        rec = game.lua.table_from
        game.g.RECIPES = rec([rec({"id": 3915, "name": "Linen Bag", "learned": True, "output": 4238,
                                   "reagents": rec([rec([2996, 3])])})])
        for key, value in stub.items():
            game.g[key] = rec(value) if isinstance(value, dict) else value
        game.fire("TRADE_SKILL_SHOW")
        return game, {r["profession"] for r in savedvars.recipes(game.db())}, game.db()["probe"]["recipes"][-1]

    _, professions, probe = tailor()                                   # as in Forever: child empty, base named
    assert professions == {"Tailoring"} and "(from base)" in probe
    _, professions, probe = tailor(CHILD_PROFESSION={"professionName": "Classic Tailoring", "parentProfessionName": "Tailoring",
                                                     "skillLevel": 75, "maxSkillLevel": 150})
    assert professions == {"Tailoring"} and "(from child)" in probe    # a client with child professions
    _, professions, probe = tailor(PROFESSION={"professionName": ""}, RECIPE_PROFESSION={"professionName": "Tailoring"})
    assert professions == {"Tailoring"} and "(from recipe)" in probe   # neither call has it: ask the recipe
    game, professions, probe = tailor(PROFESSION={"professionName": ""})
    assert professions == {"Profession 3915"} and "(from none)" in probe   # nobody has it: still saved
    assert game.db()["errors"] == {}


CLASSIC_API = """
local skills = {
  { name = "Bags", kind = "header" },
  { name = "Linen Bag", kind = "easy", item = "|Hitem:4238::::|h[Linen Bag]|h", spell = "|Henchant:3915|h[Linen Bag]|h",
    reagents = { { "|Hitem:2996::::|h[Bolt of Linen Cloth]|h", 3 }, { "|Hitem:2320::::|h[Coarse Thread]|h", 3 } } },
  { name = "Mooncloth", kind = "optimal", item = "|Hitem:14342::::|h[Mooncloth]|h", cooldown = 7200,
    reagents = { { "|Hitem:14256::::|h[Felcloth]|h", 2 } } },
}
function GetTradeSkillLine() return "Tailoring", 75, 150 end
function GetNumTradeSkills() return #skills end
function GetTradeSkillInfo(i) return skills[i].name, skills[i].kind end
function GetTradeSkillNumReagents(i) return #(skills[i].reagents or {}) end
function GetTradeSkillReagentInfo(i, r) return "name", 0, skills[i].reagents[r][2], 0 end
function GetTradeSkillReagentItemLink(i, r) return skills[i].reagents[r][1] end
function GetTradeSkillNumMade(i) return 1, 1 end
function GetTradeSkillItemLink(i) return skills[i].item end
function GetTradeSkillRecipeLink(i) return skills[i].spell end
function GetTradeSkillCooldown(i) return skills[i].cooldown end

local crafts = {
  { name = "Runed Copper Rod", kind = "optimal", link = "|Hitem:6218::::|h[Runed Copper Rod]|h",
    reagents = { { "|Hitem:6217::::|h[Copper Rod]|h", 1 }, { "|Hitem:10940::::|h[Strange Dust]|h", 1 } } },
  { name = "Enchant Bracer - Minor Health", kind = "optimal", link = "|Henchant:7418|h[Enchant Bracer - Minor Health]|h",
    reagents = { { "|Hitem:10940::::|h[Strange Dust]|h", 1 } } },
}
function GetCraftDisplaySkillLine() return "Enchanting", 40, 75 end
function GetNumCrafts() return #crafts end
function GetCraftInfo(i) return crafts[i].name, "", crafts[i].kind end
function GetCraftNumReagents(i) return #crafts[i].reagents end
function GetCraftReagentInfo(i, r) return "name", 0, crafts[i].reagents[r][2], 0 end
function GetCraftReagentItemLink(i, r) return crafts[i].reagents[r][1] end
function GetCraftItemLink(i) return crafts[i].link end
"""


def test_recipes_from_the_classic_profession_windows():
    """A Classic-style client: the modern API answers nothing, the old trade skill and craft APIs do."""
    game = Game()
    game.lua.execute(CLASSIC_API)
    game.fire("TRADE_SKILL_SHOW")
    game.fire("CRAFT_SHOW")
    game.g.Advance(1)
    game.frames(1)
    recipes = {r["name"]: r for r in savedvars.recipes(game.db())}
    assert sorted(recipes) == ["Enchant Bracer - Minor Health", "Linen Bag", "Mooncloth", "Runed Copper Rod"]
    bag = recipes["Linen Bag"]
    assert (bag["profession"], bag["skill"], bag["recipe_id"], bag["item_id"], bag["reagents"]) == (
        "Tailoring", 75, 3915, 4238, {2996: 3, 2320: 3})
    assert recipes["Mooncloth"]["cooldown"] == 7200
    rod, bracer = recipes["Runed Copper Rod"], recipes["Enchant Bracer - Minor Health"]
    assert (rod["profession"], rod["item_id"], rod["reagents"]) == ("Enchanting", 6218, {6217: 1, 10940: 1})
    assert (bracer["item_id"], bracer["recipe_id"]) == (0, 7418)          # an enchant makes no item
    # probe = game.db()["probe"]["recipes"]   (2026-10-12: a history now)
    probe = game.db()["probe"]["recipes"][-1]
    assert "classic: profession=Tailoring rows=3 recipes=2" in probe and "craft: profession=Enchanting rows=2 recipes=2" in probe
    assert game.db()["errors"] == {}


def test_disenchant_results_are_logged():
    game = Game()
    info = game.lua.table_from
    game.g.ITEM_INFO = info({1495: info(["Calico Shoes", 20, 1, 4, 1, 2, 12]), 10940: info(["Strange Dust", 0, 20, 7, 12])})

    def bags(items):
        game.g.SetBag(0, 16, info([info(i) for i in items]))

    bags([[1, 1495, 1, True], [2, 2589, 14, False], [3, 10940, 1, False]])
    game.fire("UNIT_SPELLCAST_START", "player", "cast-1", 13262)
    game.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "cast-1", 13262)
    bags([[2, 2589, 14, False], [3, 10940, 1, False]])     # the shoes are gone, the loot is not in yet
    game.fire("BAG_UPDATE_DELAYED")
    assert game.db()["disenchants"] == {}
    bags([[2, 2589, 14, False], [3, 10940, 3, False], [4, 10938, 1, False]])
    game.fire("BAG_UPDATE_DELAYED")
    rows = savedvars.disenchants(game.db())
    assert [(r["item_id"], r["quality"], r["level"], r["class_id"], r["gave"]) for r in rows] == [
        (1495, 2, 12, 4, {10940: 2, 10938: 1})]
    assert any("Disenchanted Calico Shoes: " in p and "Strange Dust x2" in p for p in game.printed())

    game.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "cast-2", 2575)      # some other spell: nothing
    bags([[2, 2589, 10, False], [3, 10940, 3, False]])
    game.fire("BAG_UPDATE_DELAYED")
    game.fire("UNIT_SPELLCAST_START", "player", "cast-3", 13262)         # started, then interrupted
    game.fire("UNIT_SPELLCAST_INTERRUPTED", "player", "cast-3", 13262)
    bags([[3, 10940, 3, False]])
    game.fire("BAG_UPDATE_DELAYED")
    game.fire("UNIT_SPELLCAST_START", "party1", "cast-4", 13262)         # someone else's cast
    game.fire("UNIT_SPELLCAST_SUCCEEDED", "party1", "cast-4", 13262)
    game.fire("BAG_UPDATE_DELAYED")
    assert len(savedvars.disenchants(game.db())) == 1


def test_vendor_prices_are_recorded_at_the_vendor():
    game = Game()
    row = game.lua.table_from

    def open_vendor(name, items):
        game.g.NPC_NAME = name
        game.g.MERCHANT = row([row(i) for i in items])
        game.fire("MERCHANT_SHOW")
        game.fire("MERCHANT_UPDATE")             # comes in bursts
        game.g.Advance(0.5)
        game.frames(1)

    open_vendor("Trade Goods Tom", [[2320, 10, 1, -1], [2880, 100, 1, -1], [4340, 350, 5, -1], [6217, 124, 1, 2],
                                    [30000, 0, 1, -1, True]])               # the last one costs a token, not money
    vendors = savedvars.vendors(game.db())
    assert sorted(vendors) == [2320, 2880, 4340, 6217]
    assert vendors[2320] == {"price": 10, "stack": 1, "available": -1, "vendor": "Trade Goods Tom", "zone": "Orgrimmar"}
    assert vendors[4340]["price"] == 70 and vendors[4340]["stack"] == 5       # 3s 50c for five: 70c each
    assert vendors[6217]["available"] == 2                                    # limited stock
    assert sum("Trade Goods Tom: 4 vendor prices saved" in p for p in game.printed()) == 1

    open_vendor("Trade Goods Tom", [[2320, 10, 1, -1], [6217, 124, 1, 0]])   # same vendor later: the rod sold out
    vendors = savedvars.vendors(game.db())
    assert vendors[6217]["available"] == 0 and len(vendors) == 4              # updated, nothing lost
    assert sum("vendor prices saved" in p for p in game.printed()) == 1       # nothing new, nothing said
    assert "errors" not in game.db() or game.db()["errors"] == {}


def test_ledger_mail_is_logged_once():
    game = Game()
    now = game.g.GetServerTime()
    day = 86400

    def mail(**kw):
        return game.lua.table_from(kw)

    # Changed 2026-10-11 (beta T6): opening the mailbox refreshes daysLeft; later inbox updates
    # (looting a mail) do not. The old helper refreshed on every update.
    # def open_mailbox():
    #     for _ in range(3):                   # the event comes in bursts
    #         game.fire("MAIL_INBOX_UPDATE")
    #     game.g.Advance(1)
    #     game.frames(1)
    def update():
        for _ in range(3):                   # the event comes in bursts
            game.fire("MAIL_INBOX_UPDATE")
        game.g.Advance(1)
        game.frames(1)

    def open_mailbox():
        game.g.RefreshInbox()
        update()

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
        # mail(subject="Auction cancelled: Linen Cloth", expires=now + 29 * day, name="Linen Cloth", item=2589),
        mail(subject="Auction cancelled: Linen Cloth (13)", expires=now + 29 * day, name="Linen Cloth",
             item=2589, itemCount=13),       # 2026-10-11: real subjects carry the stack size
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
    assert (rows[4]["name"], rows[4]["item"], rows[4]["qty"]) == ("Linen Cloth", 2589, 13)

    # Changed 2026-10-11 (beta T6): first the case that double-logged in the beta - a mail is
    # looted a few seconds later and the inbox updates without a refresh.
    # game.g.Advance(3600)                     # same mails an hour later: nothing new
    # open_mailbox()
    # game.g.table.remove(game.g.INBOX, 2)     # one of the twin purchases is taken
    # open_mailbox()
    # assert len(game.ledger()) == len(rows) + 1
    game.g.Advance(3)
    game.g.table.remove(game.g.INBOX, 2)     # one of the twin purchases is taken
    update()
    game.g.Advance(40)
    update()
    assert len(game.ledger()) == len(rows) + 1
    game.g.Advance(3600)                     # same mails an hour later, refreshed: nothing new
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
