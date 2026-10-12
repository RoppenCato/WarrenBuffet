"""Offline tests for Inventory.lua (same stub and helpers as test_addon.py).

    .venv/Scripts/python tests/test_addon_inventory.py
"""
from __future__ import annotations

from test_addon import Game, savedvars

LINEN, ORE, POTION = 2589, 2770, 118


def bag(game, index, slots, items):
    game.g.SetBag(index, slots, game.lua.table_from([game.lua.table_from(i) for i in items]))


def settle(game):
    game.g.Advance(1)
    game.frames(1)


def inv(game):
    return savedvars.inventory(game.db())["Tester-BetaRealm"]


def test_bags_and_bank_snapshot():
    game = Game()
    bag(game, 0, 16, [[1, LINEN, 13, False], [3, 6948, 1, True], [9, POTION, 2, False]])   # 6948: soulbound
    bag(game, 1, 8, [[2, LINEN, 7, False]])
    bag(game, 6, 98, [[5, ORE, 40, False]])        # character bank tab
    bag(game, 12, 98, [[1, ORE, 200, False]])      # account bank tab
    bag(game, -2, 6, [[1, 4500, 1, False]])        # the container that holds bank bags: not items
    game.fire("PLAYER_ENTERING_WORLD")
    for _ in range(5):                             # bag events come in bursts
        game.fire("BAG_UPDATE_DELAYED")
    settle(game)
    now = inv(game)
    assert now["bags"] == {LINEN: 20, POTION: 2}
    assert now["bank"] == {} and "bankTs" not in now          # bank never opened

    game.g.BANK_OPEN = True
    game.fire("BANKFRAME_OPENED")
    settle(game)
    now = inv(game)
    assert now["bank"] == {ORE: 40} and now["abank"] == {ORE: 200}

    game.g.BANK_OPEN = False                       # closed: bank bags read as empty
    game.fire("BANKFRAME_CLOSED")
    bag(game, 0, 16, [[1, LINEN, 13, False]])      # potions used
    game.fire("BAG_UPDATE_DELAYED")
    settle(game)
    now = inv(game)
    assert now["bags"] == {LINEN: 20}
    assert now["bank"] == {ORE: 40}                # not wiped by the closed bank

    game.g.BAGS_READABLE = False                   # logging out: nothing readable
    game.fire("BAG_UPDATE_DELAYED")
    settle(game)
    assert inv(game)["bags"] == {LINEN: 20}        # last good snapshot kept
    assert "err" not in inv(game)


def test_own_auctions_snapshot():
    game = Game()
    game.fire("AUCTION_HOUSE_SHOW")
    game.g.Advance(2)
    game.frames(1)
    assert game.g.QUERY_OWNED == 1                 # one read-only query, 2 s after opening
    game.g.OWNED = game.lua.table_from([
        game.lua.table_from({"auctionID": 54136807, "itemKey": game.lua.table_from({"itemID": POTION}),
                             "quantity": 1, "buyoutAmount": 10, "status": 0, "timeLeftSeconds": 28000.7}),
        game.lua.table_from({"auctionID": 54138630, "itemKey": game.lua.table_from({"itemID": LINEN}),
                             "quantity": 13, "buyoutAmount": 18, "bidAmount": 5, "status": 1}),
    ])
    game.fire("OWNED_AUCTIONS_UPDATED")
    auctions = inv(game)["auctions"]
    assert auctions[0] == {"auction": 54136807, "item": POTION, "qty": 1, "buyout": 10, "bid": 0, "status": 0, "seconds": 28000}
    assert auctions[1] == {"auction": 54138630, "item": LINEN, "qty": 13, "buyout": 18, "bid": 5, "status": 1, "seconds": 0}
    game.slash("")
    assert any("inventory: 0 items in bags, 0 in bank (open the bank once), 2 own auctions" in p for p in game.printed())

    # Added 2026-10-12 (beta run 4): a new auction makes the addon ask for the list again.
    game.fire("AUCTION_HOUSE_AUCTION_CREATED", 54999999)
    game.g.Advance(1)
    game.frames(1)
    assert game.g.QUERY_OWNED == 2


def test_api_failure_is_recorded_not_raised():
    game = Game()
    bag(game, 0, 16, [[1, LINEN, 13, False]])
    game.fire("PLAYER_ENTERING_WORLD")
    settle(game)
    game.lua.execute("C_AuctionHouse.GetNumOwnedAuctions = function() error('no such thing') end")
    game.fire("OWNED_AUCTIONS_UPDATED")            # must not raise
    now = inv(game)
    assert now["bags"] == {LINEN: 13} and now["auctions"] == []
    assert now["err"].startswith("auctions: ") and "no such thing" in now["err"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
