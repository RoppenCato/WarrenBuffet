"""Storage (docs/04-data-storage.md): Parquet files under data/, queried through DuckDB views.

    python -m pipeline.storage ingest [--sv <path>]   SavedVariables + pulled pricetables -> Parquet
    python -m pipeline.storage status                 what is stored

  L0      data/l0/date=YYYY-MM-DD/<house>-<ts>.parquet            raw own scans, one row per auction, 14 days
  L1      data/l1/date=YYYY-MM-DD/<source>-<house>-<ts>.parquet   one row per item per snapshot, kept forever
  ledger  data/ledger.parquet                                     own transactions, kept forever

One file per snapshot, so ingesting twice changes nothing: that is the dedup on
(source, house, snapshot_ts). L2 (hourly) and L3 (daily) are views over L1 for now and get
materialised when L1 is too big to scan each time (D3).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import tempfile
from pathlib import Path

import duckdb

from pipeline import ahledger, analytics, houses, savedvars

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
L0_DAYS = 14

L1_COLUMNS = {"source": "VARCHAR", "house": "VARCHAR", "ts": "BIGINT", "item_id": "INTEGER", "variant": "VARCHAR",
              "min_buyout": "BIGINT", "p10": "BIGINT", "p25": "BIGINT", "median": "BIGINT", "p75": "BIGINT",
              "quantity": "BIGINT", "auctions": "INTEGER", "depth_5pct": "BIGINT", "sold_est_per_day": "DOUBLE"}
L0_COLUMNS = {"house": "VARCHAR", "ts": "BIGINT", "item_id": "INTEGER", "count": "INTEGER", "buyout": "BIGINT",
              "min_bid": "BIGINT", "bid": "BIGINT", "time_left": "TINYINT"}
LEDGER_COLUMNS = {"ts": "BIGINT", "character": "VARCHAR", "event": "VARCHAR", "item_id": "INTEGER", "qty": "INTEGER",
                  "unit_price": "BIGINT", "total": "BIGINT", "fee": "BIGINT", "deposit": "BIGINT", "copper": "BIGINT",
                  "delta": "BIGINT", "auction": "BIGINT", "name": "VARCHAR", "row": "VARCHAR"}
# Best source first when two sources cover the same hour (D2).
SOURCE_RANK = "CASE source WHEN 'blizzard' THEN 0 WHEN 'own' THEN 1 ELSE 2 END"


def _write(path: Path, columns: dict[str, str], rows, ts_name: str = "snapshot_ts") -> None:
    """Rows -> one Parquet file. The `ts` column (unix seconds) is stored as a UTC TIMESTAMP named ts_name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "rows.csv"
        with raw.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(["" if v is None else v for v in row] for row in rows)
        spec = ", ".join(f"'{name}': '{kind}'" for name, kind in columns.items())
        select = (f"SELECT * REPLACE (make_timestamp(ts * 1000000) AS ts) FROM read_csv('{raw.as_posix()}', "
                  f"header = false, delim = ',', quote = '\"', escape = '\"', nullstr = '', columns = {{{spec}}})")
        if ts_name != "ts":
            select = f"SELECT * RENAME (ts AS {ts_name}) FROM ({select})"
        duckdb.connect().execute(f"COPY ({select}) TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")


def _day(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def _p75(book) -> int:
    total, cum = sum(q for _, q in book), 0
    for price, qty in book:
        cum += qty
        if cum * 4 >= total * 3:
            return price
    return 0


def ingest_scans(db: dict, data: Path = DATA) -> dict:
    """Own scans from the SavedVariables table -> L1 (always) and L0 (while the addon still has the raw rows)."""
    done = {"l1": 0, "l0": 0, "unknown_realm": set()}
    for scan in db.get("scans") or []:
        house = houses.house_id(scan["realm"], scan["faction"])
        if not house:
            done["unknown_realm"].add(scan["realm"])
            continue
        ts, day = scan["ts"], _day(scan["ts"])
        raw = savedvars.raw_rows(scan)
        l1 = data / "l1" / f"date={day}" / f"own-{house}-{ts}.parquet"
        if not l1.exists():
            books = analytics.books(raw)
            rows = []
            for item_id, (low, p10, p25, median, qty, auctions) in sorted(savedvars.agg_rows(scan).items()):
                book = books.get(item_id)
                rows.append(("own", house, ts, item_id, None, low, p10, p25, median, _p75(book) if book else None,
                             qty, auctions, analytics.depth(book) if book else None, None))
            _write(l1, L1_COLUMNS, rows)
            done["l1"] += 1
        l0 = data / "l0" / f"date={day}" / f"{house}-{ts}.parquet"
        if raw and not l0.exists():
            _write(l0, L0_COLUMNS, ((house, ts, *row[:5], row[5] if len(row) > 5 else None) for row in raw))
            done["l0"] += 1
    return done


def ingest_ahledger(data: Path = DATA) -> int:
    """Pulled pricetables (data/ahledger/<market>/<ts>.txt) -> L1. Returns the number of new snapshots."""
    new = 0
    for path in sorted((data / "ahledger").glob("*/*.txt")):
        head, prices = ahledger.parse_pricetable(path.read_text(encoding="utf-8"))
        out = data / "l1" / f"date={_day(head['ts'])}" / f"ahledger-{head['market']}-{head['ts']}.parquet"
        if out.exists() or not prices:
            continue
        _write(out, L1_COLUMNS, (("ahledger", head["market"], head["ts"], item_id, None, p.min_buyout, None, None,
                                  p.median, None, p.quantity, None, None, p.sold_per_day)
                                 for item_id, p in sorted(prices.items())))
        new += 1
    # The text files are only a landing zone. Keep the newest per house (the dashboard reads it)
    # and drop the rest once they are in L1.
    for folder in (data / "ahledger").glob("*"):
        for old in sorted(folder.glob("*.txt"), key=lambda p: int(p.stem))[:-1]:
            old.unlink()
    return new


def ingest_ledger(db: dict, data: Path = DATA) -> int:
    """Ledger rows -> data/ledger.parquet, merged with what is already there. Returns the row count."""
    path = data / "ledger.parquet"
    rows = {}
    if path.exists():
        for row in duckdb.connect().execute(f"SELECT * REPLACE (epoch(ts)::BIGINT AS ts) FROM '{path.as_posix()}'").fetchall():
            rows[row[-1]] = row
    for raw, r in zip(db.get("ledger") or [], savedvars.ledger_rows(db)):
        if r["char"] == "?":
            continue
        unit = r.get("unit") or (r["total"] // r["qty"] if r.get("total") and r.get("qty") else None)
        rows[raw] = (r["ts"], r["char"], r["event"], r.get("item"), r.get("qty"), unit, r.get("total"), r.get("fee"),
                     r.get("dep"), r.get("copper"), r.get("delta"), r.get("auction"), r.get("name"), raw)
    if rows:
        _write(path, LEDGER_COLUMNS, sorted(rows.values(), key=lambda row: (row[0], row[-1])), ts_name="ts")
    return len(rows)


def prune(data: Path = DATA, today: dt.date | None = None) -> int:
    """Delete L0 partitions older than L0_DAYS. L1 and the ledger are kept forever."""
    cutoff = ((today or dt.datetime.now(dt.timezone.utc).date()) - dt.timedelta(days=L0_DAYS)).isoformat()
    removed = 0
    for folder in (data / "l0").glob("date=*"):
        if folder.name[5:] < cutoff:
            for file in folder.glob("*.parquet"):
                file.unlink()
                removed += 1
            folder.rmdir()
    return removed


def connect(data: Path = DATA) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with views over the Parquet files:
    l0, l1, ledger, latest (newest snapshot per source and house), hourly (L2), daily (L3)."""
    con = duckdb.connect()

    def view(name, pattern, columns):
        if list(data.glob(pattern)):
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{(data / pattern).as_posix()}', "
                        "hive_partitioning = true, union_by_name = true)")
        else:   # nothing stored yet: an empty view with the right columns
            cols = ", ".join(f"NULL::{'TIMESTAMP' if c in ('ts', 'snapshot_ts') else kind} AS {c}" for c, kind in columns.items())
            con.execute(f"CREATE VIEW {name} AS SELECT {cols} WHERE false")

    ts = lambda cols: {("snapshot_ts" if k == "ts" else k): v for k, v in cols.items()}   # noqa: E731
    view("l1", "l1/*/*.parquet", ts(L1_COLUMNS))
    view("l0", "l0/*/*.parquet", ts(L0_COLUMNS))
    view("ledger", "ledger.parquet", LEDGER_COLUMNS)
    con.execute("CREATE VIEW latest AS SELECT * FROM l1 "
                "QUALIFY snapshot_ts = max(snapshot_ts) OVER (PARTITION BY source, house)")
    con.execute(f"""CREATE VIEW hourly AS
        SELECT * EXCLUDE (pick) FROM (
            SELECT *, date_trunc('hour', snapshot_ts) AS hour,
                   row_number() OVER (PARTITION BY house, item_id, date_trunc('hour', snapshot_ts)
                                      ORDER BY {SOURCE_RANK}, snapshot_ts DESC) AS pick
            FROM l1)
        WHERE pick = 1""")
    con.execute("""CREATE VIEW daily AS
        SELECT house, item_id, CAST(hour AS DATE) AS day, min(min_buyout) AS min_buyout,
               CAST(median(median) AS BIGINT) AS median, CAST(avg(quantity) AS BIGINT) AS quantity,
               max(sold_est_per_day) AS sold_est_per_day, count(*) AS hours
        FROM hourly GROUP BY house, item_id, CAST(hour AS DATE)""")
    return con


def status(data: Path = DATA) -> str:
    con = connect(data)
    lines = []
    for source, house, snapshots, first, last, items in con.execute(
            "SELECT source, house, count(DISTINCT snapshot_ts), min(snapshot_ts), max(snapshot_ts), count(DISTINCT item_id) "
            "FROM l1 GROUP BY source, house ORDER BY house, source").fetchall():
        lines.append(f"L1  {house:28} {source:9} {snapshots:4} snapshots  {first:%Y-%m-%d %H:%M} .. {last:%Y-%m-%d %H:%M} UTC  {items} items")
    scans, auctions = con.execute("SELECT count(DISTINCT (house, snapshot_ts)), count(*) FROM l0").fetchone()
    lines.append(f"L0  {scans} raw scans, {auctions:,} auction rows (kept {L0_DAYS} days)")
    lines.append(f"ledger  {con.execute('SELECT count(*) FROM ledger').fetchone()[0]} rows")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["ingest", "status"])
    parser.add_argument("--sv", help="SavedVariables/ForeverAH.lua (else FOREVERAH_SV or data/local.json)")
    args = parser.parse_args()
    if args.command == "ingest":
        from dashboard.build import sv_path   # the one place that knows where the file is
        table = savedvars.load(sv_path(args.sv))
        scans = ingest_scans(table)
        print(f"own scans: {scans['l1']} new in L1, {scans['l0']} new in L0"
              + (f"; realms not in plan/houses.yaml: {sorted(scans['unknown_realm'])}" if scans["unknown_realm"] else ""))
        print(f"AHledger: {ingest_ahledger()} new snapshots; ledger: {ingest_ledger(table)} rows; "
              f"L0 files pruned: {prune()}")
    print(status())
