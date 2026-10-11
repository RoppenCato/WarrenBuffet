"""Tests for pipeline/storage.py: Parquet layout, dedup, views, retention (no network, temp folder).

    .venv/Scripts/python tests/test_storage.py
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import storage  # noqa: E402

HOUSE = "forever.normal.horde.us"     # "Classic Beta PvE" + Horde in plan/houses.yaml
T0 = 1791711400                        # 2026-10-11 09:36:40 UTC
PRICETABLE = "AHL1|forever/normal/horde/us|{ts}|2\n1:{median}:90:500:150:150:80:300:1234\n9:5000:4000:3::::7000:0\n"


def scan(ts, rows, raw=True):
    chunk = ";".join(",".join(map(str, r)) for r in rows) + ";"
    return {"id": f"{ts}:Classic Beta PvE:Horde", "ts": ts, "realm": "Classic Beta PvE", "faction": "Horde",
            "raw": [chunk] if raw else None,
            # item 1: 10 @ 100, 10 @ 200, 20 @ 300, plus a bid-only stack of 5; item 2: one stack
            "agg": ["1,100,100,100,200,45,4;2,50,50,50,50,10,1;"]}


ROWS = [(1, 10, 1000, 0, 0, 3), (1, 10, 2000, 0, 0, 3), (1, 20, 6000, 0, 0, 4), (1, 5, 0, 50, 0, 1), (2, 10, 500, 0, 0, 2)]


def test_ingest_layout_dedup_and_views():
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        db = {"scans": [scan(T0, ROWS), scan(T0 + 900, ROWS, raw=False), dict(scan(T0, ROWS), realm="Unknown Realm")],
              "ledger": [f"{T0},Gorlac-R,post,auction=7,seq=1,kind=commodity,item=2589,qty=13,unit=18,dur=1,dep=8",
                         f"{T0 + 5},Gorlac-R,bought,item=5997,qty=2,total=10,fee=0,name=Elixir, of \"Minor\" Defense",
                         f"{T0 + 9},?,gold,copper=0,at=logout"]}
        for ts, median in ((T0 + 60, 210), (T0 + 7200, 190)):
            path = data / "ahledger" / HOUSE / f"{ts}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(PRICETABLE.format(ts=ts, median=median), encoding="utf-8")

        done = storage.ingest_scans(db, data)
        assert (done["l1"], done["l0"], done["unknown_realm"]) == (2, 1, {"Unknown Realm"})
        assert storage.ingest_ahledger(data) == 2
        assert storage.ingest_ledger(db, data) == 2                       # the "?" row is dropped
        assert sorted(p.name for p in (data / "l1" / "date=2026-10-11").iterdir()) == [
            f"ahledger-{HOUSE}-{T0 + 60}.parquet", f"ahledger-{HOUSE}-{T0 + 7200}.parquet",
            f"own-{HOUSE}-{T0}.parquet", f"own-{HOUSE}-{T0 + 900}.parquet"]

        again = storage.ingest_scans(db, data)                             # same input again: nothing new
        assert (again["l1"], again["l0"]) == (0, 0) and storage.ingest_ahledger(data) == 0
        assert storage.ingest_ledger(db, data) == 2

        con = storage.connect(data)
        own = con.execute("SELECT min_buyout, p10, p25, median, p75, quantity, auctions, depth_5pct, sold_est_per_day, "
                          "snapshot_ts FROM l1 WHERE source = 'own' AND item_id = 1 ORDER BY snapshot_ts").fetchall()
        assert own[0][:9] == (100, 100, 100, 200, 300, 45, 4, 10, None)    # p75 and depth come from the raw rows
        assert own[0][9] == dt.datetime(2026, 10, 11, 9, 36, 40)
        assert own[1][:9] == (100, 100, 100, 200, None, 45, 4, None, None)  # raw already dropped by the addon
        ahl = con.execute("SELECT median, min_buyout, quantity, sold_est_per_day, p25, auctions FROM l1 "
                          "WHERE source = 'ahledger' AND item_id = 1 ORDER BY snapshot_ts").fetchall()
        assert ahl == [(210, 90, 500, 123.4, None, None), (190, 90, 500, 123.4, None, None)]
        assert con.execute("SELECT count(*), sum(count), max(time_left) FROM l0").fetchone() == (5, 55, 4)

        # latest: newest snapshot per source; hourly: own scan wins over AHledger inside the same hour
        assert con.execute("SELECT source, median FROM latest WHERE item_id = 1 ORDER BY source").fetchall() == [
            ("ahledger", 190), ("own", 200)]
        hourly = con.execute("SELECT hour, source, median FROM hourly WHERE item_id = 1 ORDER BY hour").fetchall()
        assert [(h.hour, s, m) for h, s, m in hourly] == [(9, "own", 200), (11, "ahledger", 190)]
        assert con.execute("SELECT median, min_buyout, hours FROM daily WHERE item_id = 1").fetchall() == [(195, 90, 2)]

        ledger = con.execute("SELECT character, event, item_id, qty, unit_price, total, deposit, name FROM ledger ORDER BY ts").fetchall()
        assert ledger == [("Gorlac-R", "post", 2589, 13, 18, None, 8, None),
                          ("Gorlac-R", "bought", 5997, 2, 5, 10, None, 'Elixir, of "Minor" Defense')]
        assert "L0  1 raw scans, 5 auction rows" in storage.status(data)


def test_l0_is_pruned_after_14_days_and_l1_is_kept():
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        storage.ingest_scans({"scans": [scan(T0, ROWS)]}, data)
        assert storage.prune(data, today=dt.date(2026, 10, 25)) == 0       # day 14: still there
        assert storage.prune(data, today=dt.date(2026, 10, 26)) == 1
        assert not list((data / "l0").glob("*/*.parquet"))
        assert len(list((data / "l1").glob("*/*.parquet"))) == 1
        con = storage.connect(data)                                        # views still work with L0 gone
        assert con.execute("SELECT count(*) FROM l0").fetchone() == (0,)
        assert con.execute("SELECT count(*) FROM l1").fetchone() == (2,)


def test_views_exist_on_an_empty_store():
    with tempfile.TemporaryDirectory() as tmp:
        con = storage.connect(Path(tmp))
        for name in ("l0", "l1", "ledger", "latest", "hourly", "daily"):
            assert con.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
