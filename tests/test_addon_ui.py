"""Offline tests for UI.lua: the log window, its button, and the chat fallback.

    .venv/Scripts/python tests/test_addon_ui.py
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
    game.set_auctions(make_auctions(300, 10))
    game.open_ah()
    assert lines(game, "CHAT") == []
    assert any("scan saved: 300 rows" in line for line in lines(game, "WINDOW"))
    assert shown(game) is True                         # a scan opens it
    assert game.db()["ui"]["shown"] is True
    assert "uiErr" not in game.db()


def test_button_toggles_and_counts_unread_ledger_lines():
    game = Game()
    click(game)
    assert shown(game) is True
    click(game)
    assert shown(game) is False and label(game) == "FAH"

    for auction in (111, 112, 113):                    # ledger lines while the window is closed
        game.fire("AUCTION_HOUSE_AUCTION_CREATED", auction)
    assert shown(game) is False                        # they never open it
    assert label(game) == "FAH 3"
    assert sum("ledger: " in line for line in lines(game, "WINDOW")) == 3
    click(game)
    assert shown(game) is True and label(game) == "FAH"   # opening clears the count


def test_quiet_mode_keeps_the_window_closed():
    game = Game()
    click(game, "RightButton")                         # quiet mode on
    assert game.db()["ui"]["quiet"] is True
    game.set_auctions(make_auctions(50, 5))
    game.open_ah()
    assert shown(game) is False                        # even a scan does not open it now
    assert any("scan saved: 50 rows" in line for line in lines(game, "WINDOW"))
    assert lines(game, "CHAT") == []
    click(game, "RightButton")                         # and off again
    game.close_ah()
    game.g.Advance(15 * 60)
    game.open_ah()
    assert shown(game) is True


def test_positions_are_saved_and_restored():
    game = Game()
    game.lua.execute('ForeverAHButton:SetPoint("CENTER", UIParent, "CENTER", 120.4, -33.6)')   # as after a drag
    game.g.RunScript("ForeverAHButton", "OnDragStop")
    assert list(game.db()["ui"]["button"]) == ["CENTER", "CENTER", 120, -34]
    game.lua.execute('ForeverAHButton:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)')
    game.fire("PLAYER_LOGIN")                          # next session
    assert game.lua.eval("(select(4, ForeverAHButton:GetPoint(1)))") == 120


def test_chat_fallback_when_the_window_cannot_be_built():
    game = Game(broken_widget="ScrollingMessageFrame")
    game.set_auctions(make_auctions(100, 5))
    game.open_ah()
    assert lines(game, "WINDOW") == []
    assert any("scan saved: 100 rows" in line for line in lines(game, "CHAT"))
    assert "ScrollingMessageFrame" in game.db()["uiErr"]
    assert len(game.db()["scans"]) == 1                # the addon itself is unaffected


def test_trader_command():
    game = Game()
    game.slash("trader")
    assert game.db()["trader"] == "Tester-BetaRealm"
    game.slash("")
    assert any("trader: Tester-BetaRealm" in line for line in lines(game, "WINDOW"))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
