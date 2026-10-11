"""Offline tests for UI.lua: the window, the minimap button, the fallbacks, readable lines.

    .venv/Scripts/python tests/test_addon_ui.py

Rewritten 2026-10-11 with UI v0.7 (minimap button, bordered window above the AH, sentences
instead of raw ledger rows). The stub's widgets reject method names it does not list, so a
call that does not exist in the game fails here.
"""
from __future__ import annotations

from test_addon import Game, make_auctions


def lines(game, name):
    return list(game.g[name].values())


def shown(game):
    return game.lua.eval("ForeverAHWindow:IsShown()")


def click(game, mouse="LeftButton"):
    game.g.RunScript("ForeverAHButton", "OnClick", mouse)


def label(game):
    return game.lua.eval("ForeverAHButton.fontStrings[1].text")


def test_messages_go_to_the_window_not_to_chat():
    game = Game()
    assert shown(game) is False                        # hidden until there is something to say
    game.set_auctions(make_auctions(12_300, 10))
    game.open_ah()
    assert lines(game, "CHAT") == []
    assert any("Scan saved" in line and "12,300 auctions, 10 items" in line for line in lines(game, "WINDOW"))
    assert not any("hasAllInfo" in line for line in lines(game, "WINDOW"))   # diagnostics are off by default
    assert shown(game) is True                         # a scan opens it
    assert game.lua.eval("ForeverAHWindow.raised") >= 1   # and brings it to the front
    db = game.db()
    assert db["ui"]["shown"] is True and "uiErr" not in db and "uiNote" not in db


def test_window_opens_beside_the_auction_house_until_moved():
    game = Game()
    game.set_auctions(make_auctions(50, 5))
    game.open_ah()
    assert game.lua.eval("select(2, ForeverAHWindow:GetPoint(1)) == AuctionHouseFrame") is True
    game.lua.execute('ForeverAHWindow:SetPoint("CENTER", UIParent, "CENTER", -300.2, 80)')   # the player drags it
    game.g.RunScript("ForeverAHWindow", "OnDragStop")
    assert list(game.db()["ui"]["window"]) == ["CENTER", "CENTER", -300, 80]
    game.close_ah()
    game.g.Advance(15 * 60)
    game.open_ah()
    assert game.lua.eval("select(2, ForeverAHWindow:GetPoint(1)) == UIParent") is True   # left where it was put

    game = Game()                                      # the game's AH window does not exist yet on the event
    game.lua.execute("AH, AuctionHouseFrame = AuctionHouseFrame, nil")
    game.fire("AUCTION_HOUSE_SHOW")
    assert game.lua.eval("select(2, ForeverAHWindow:GetPoint(1)) == UIParent") is True
    game.lua.execute("AuctionHouseFrame = AH")
    game.g.Advance(0.2)
    game.frames(1)
    assert game.lua.eval("select(2, ForeverAHWindow:GetPoint(1)) == AuctionHouseFrame") is True


def test_minimap_button_toggles_and_counts_unread_lines():
    game = Game()
    assert game.lua.eval("ForeverAHButton.parent == Minimap") is True
    assert game.lua.eval("select(2, ForeverAHButton:GetPoint(1)) == Minimap") is True
    click(game)
    assert shown(game) is True
    click(game)
    assert shown(game) is False and label(game) == ""

    for auction in (111, 112, 113):                    # ledger lines while the window is closed
        game.fire("AUCTION_HOUSE_AUCTION_CREATED", auction)
    assert shown(game) is False and label(game) == "3"
    click(game)
    assert shown(game) is True and label(game) == ""   # opening clears the count


def test_minimap_button_is_dragged_around_the_rim():
    game = Game()
    game.g.CURSOR = game.lua.table_from([500, 640])    # straight above the minimap centre (500, 500)
    game.g.RunScript("ForeverAHButton", "OnDragStart")
    game.g.RunScript("ForeverAHButton", "OnUpdate")
    game.g.RunScript("ForeverAHButton", "OnDragStop")
    assert game.db()["ui"]["minimap"] == 90
    x, y = game.lua.eval("select(4, ForeverAHButton:GetPoint(1))")
    assert abs(x) < 0.001 and abs(y - 75) < 0.001      # radius = half the minimap + 5
    game.lua.execute('ForeverAHButton:SetPoint("CENTER", Minimap, "CENTER", 1, 1)')
    game.fire("PLAYER_LOGIN")                          # next session: back where it was dragged
    assert abs(game.lua.eval("(select(5, ForeverAHButton:GetPoint(1)))") - 75) < 0.001


def test_quiet_mode_keeps_the_window_closed():
    game = Game()
    click(game, "RightButton")
    assert game.db()["ui"]["quiet"] is True
    game.set_auctions(make_auctions(50, 5))
    game.open_ah()
    assert shown(game) is False                        # even a scan does not open it now
    assert any("Scan saved" in line for line in lines(game, "WINDOW")) and lines(game, "CHAT") == []
    click(game, "RightButton")
    game.close_ah()
    game.g.Advance(15 * 60)
    game.open_ah()
    assert shown(game) is True


def test_ledger_lines_are_sentences():
    game = Game()
    ah = game.g.C_AuctionHouse
    ah.PostCommodity(game.lua.table_from({"id": 2770}), 2, 40, 25)
    game.fire("AUCTION_HOUSE_AUCTION_CREATED", 222)
    game.fire("AUCTION_HOUSE_SHOW")
    game.g.SetMoney(123356)
    now = game.g.GetServerTime()
    game.g.INBOX = game.lua.table_from([game.lua.table_from(dict(
        subject="Auction successful: Linen Bag", money=950, invoice="seller", name="Linen Bag", bid=1000, buyout=1000,
        deposit=20, fee=50, count=1, expires=now + 30 * 86400))])
    game.g.RefreshInbox()
    game.fire("MAIL_INBOX_UPDATE")
    game.g.Advance(1)
    game.frames(1)
    text = "\n".join(lines(game, "WINDOW"))
    assert "Posted Copper Ore x40 at 25c each for 8 h" in text
    assert "-1s 0c at the auction house, balance 12g 33s 56c" in text
    assert "Sold Linen Bag x1 for 10s 0c (AH cut 50c)" in text
    assert "auction=222" not in text                   # the raw row stays in the file, not on screen
    assert any("auction=222" in row for row in game.db()["ledger"])


def test_fallback_looks():
    game = Game(no_templates=True)                     # no Blizzard templates: the plain window
    game.set_auctions(make_auctions(100, 5))
    game.open_ah()
    assert any("Scan saved" in line for line in lines(game, "WINDOW")) and lines(game, "CHAT") == []
    assert "plain window" in game.db()["uiNote"] and "uiErr" not in game.db()

    game = Game(no_minimap=True)                       # no minimap: the floating button
    assert game.lua.eval("ForeverAHButton.parent == UIParent") is True and label(game) == "FAH"
    game.fire("AUCTION_HOUSE_AUCTION_CREATED", 1)
    assert label(game) == "FAH 1"
    assert "floating button" in game.db()["uiNote"]
    click(game)
    assert shown(game) is True


def test_chat_fallback_when_the_window_cannot_be_built():
    game = Game(broken_widget="ScrollingMessageFrame")
    game.set_auctions(make_auctions(100, 5))
    game.open_ah()
    assert lines(game, "WINDOW") == []
    assert any("Scan saved" in line for line in lines(game, "CHAT"))
    assert "ScrollingMessageFrame" in game.db()["uiErr"]
    assert len(game.db()["scans"]) == 1                # the addon itself is unaffected


def test_trader_and_debug_commands():
    game = Game()
    game.slash("trader")
    assert game.db()["trader"] == "Tester-BetaRealm"
    game.slash("")
    assert any("trader: Tester-BetaRealm" in line for line in lines(game, "WINDOW"))
    game.slash("debug")
    game.set_auctions(make_auctions(100, 5))
    game.open_ah()
    assert any("hasAllInfo misses" in line for line in lines(game, "WINDOW"))


def make_plan(scan_ts):
    import tempfile
    from pathlib import Path
    from pipeline import planfile
    labels = {"sell": "Sell", "keep": "Keep collecting", "repost": "Repost", "buy": "Buy", "short": "Over budget"}
    names = {2770: "Copper Ore", 2589: "Linen Cloth", 4235: "Heavy Hide"}
    plan = planfile.make(
        scan_ts=scan_ts, labels=labels, name=names.get, headline="Launch week, day 2 of 7", mode="launch",
        sells=[{"action": "sell", "item_id": 2770, "units": 120, "price": 141, "net": 15900, "why": "Supply is tight."},
               {"action": "keep", "item_id": 2589, "units": 14, "price": 17, "net": 0, "why": "A post costs more than it is worth."}],
        reposts=[{"action": "repost", "item_id": 2770, "units": 40, "price": 190, "cheapest": 141, "why": "Undercut by 35%."}],
        buys=[{"item_id": 4235, "units": 30, "max_price": 3154, "cost": 76600, "profit": 51600, "affordable": False,
               "why": "Listed well under its usual price."}],
        books={2770: [(141, 10)], 2589: [(17, 5)]})
    with tempfile.TemporaryDirectory() as tmp:
        return planfile.write(plan, Path(tmp) / planfile.NAME).read_text(encoding="utf-8")


def plan_lines(game):
    return list(game.g.PlanLines().values())


def test_plan_view_shows_the_pipeline_plan():
    game = Game(plan=make_plan(scan_ts=1760180000 - 600))
    text = "\n".join(plan_lines(game))
    assert "Launch week, day 2 of 7" in text and "A newer scan exists" not in text
    assert "Sell|r  Copper Ore x120  at 1s 41c  ->  1g 59s 0c" in text and "Supply is tight." in text
    assert "Keep collecting|r  Linen Cloth x14  at 17c" in text
    assert "Repost|r  Copper Ore x40  yours 1s 90c, cheapest 1s 41c" in text
    assert "Over budget|r  Heavy Hide x30  at 31s 54c or less  (7g 66s 0c for +5g 16s 0c)" in text
    assert lines(game, "WINDOW") == []                   # the plan is not log output

    click(game)                                          # opens on the plan when there is one
    assert game.lua.eval("ForeverAHWindow.planLines:IsShown()") is True and game.db()["ui"]["tab"] == "plan"
    game.fire("AUCTION_HOUSE_AUCTION_CREATED", 7)        # a ledger line while looking at the plan
    assert label(game) == "1"
    game.lua.execute('NS.SetTab("log")')
    assert label(game) == "" and game.lua.eval("ForeverAHWindow.planLines:IsShown()") is False

    click(game)                                          # close; a scan then opens the window on the log
    game.lua.execute('NS.SetTab("plan")')
    game.set_auctions(make_auctions(50, 5))
    game.open_ah()
    assert shown(game) is True and game.db()["ui"]["tab"] == "log"
    game.fire("PLAYER_LOGIN")                            # after a /reload the plan is older than the scan
    assert any("A newer scan exists" in line for line in plan_lines(game))


def test_tooltip_lines_come_from_the_plan():
    game = Game(plan=make_plan(scan_ts=1760180000 - 600))
    info = game.lua.table_from
    game.g.ITEM_INFO = info({2770: info(["Copper Ore", 5, 20, 7, 7])})
    assert list(game.g.ShowItemTooltip(2770).values()) == ["AH cheapest: 1s 41c", "Vendor pays: 5c", "ForeverAH plan: Sell"]
    assert list(game.g.ShowItemTooltip(2589).values()) == ["AH cheapest: 17c", "ForeverAH plan: Keep collecting"]   # vendor price not loaded
    assert list(game.g.ShowItemTooltip(4235).values()) == []           # not in the scan, not held
    assert "errors" not in game.db() or game.db()["errors"] == {}


def test_no_plan_yet():
    game = Game()
    assert plan_lines(game)[0] == "No plan yet."
    assert game.db()["ui"]["tab"] == "log"
    assert list(game.g.ShowItemTooltip(2770).values()) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
