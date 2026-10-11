"""Read ForeverAH SavedVariables (written by addon/ForeverAH).

T4/T5 report:  python -m pipeline.savedvars "<...>\\SavedVariables\\ForeverAH.lua"
"""
from __future__ import annotations

import math
import sys
import time
from collections import Counter
from pathlib import Path

from lupa.lua51 import LuaRuntime, lua_type

CHECK_ITEMS = {2589: "Linen Cloth", 2770: "Copper Ore"}  # T5
MAX_RAW_MB = 10    # T4 pass: per raw scan
MAX_PARSE_S = 10   # T4 pass


def _to_py(obj):
    if lua_type(obj) != "table":
        return obj
    n = len(obj)
    if n and len(list(obj.keys())) == n:
        return [_to_py(obj[i]) for i in range(1, n + 1)]
    return {k: _to_py(v) for k, v in obj.items()}


def merge(dbs: list[dict]) -> dict:
    """Several accounts' tables as one (added 2026-10-11: the user plays two accounts).
    SavedVariables are per account, so each account has its own file. Characters are unique
    across accounts; a scan both accounts made in the same second is kept once."""
    if len(dbs) == 1:
        return dbs[0]
    out = {"scans": [], "ledger": [], "inv": {}, "errors": [], "throttled": 0}
    seen, lines = set(), {}
    for db in dbs:
        for scan in db.get("scans") or []:
            if scan["id"] not in seen:
                seen.add(scan["id"])
                out["scans"].append(scan)
        out["ledger"] += list(db.get("ledger") or [])
        out["inv"].update(db.get("inv") or {})
        out.setdefault("recipes", {}).update(db.get("recipes") or {})          # added 2026-10-11 (v0.9)
        out.setdefault("disenchants", []).extend(db.get("disenchants") or [])  # added 2026-10-11 (v0.9)
        out["errors"] += list(db.get("errors") or [])
        out["throttled"] += db.get("throttled") or 0
        for line in (db.get("items") or "").split("\n"):
            if line:
                lines.setdefault(line.split("\t", 1)[0], line)
        if db.get("vendors"):   # added 2026-10-11 (v0.10): per item, the account read last wins
            known = {line.split("\t", 1)[0]: line for line in (out.get("vendors") or "").split("\n") if line}
            known.update({line.split("\t", 1)[0]: line for line in db["vendors"].split("\n") if line})
            out["vendors"] = "".join(line + "\n" for line in known.values())
        for key in ("trader", "build", "missing", "uiErr"):
            if db.get(key) and not out.get(key):
                out[key] = db[key]
    out["scans"].sort(key=lambda scan: scan["ts"])
    out["ledger"].sort(key=lambda row: int(row.split(",", 1)[0]))
    out["items"] = "".join(line + "\n" for line in lines.values())
    return out


def load(path) -> dict:
    """SavedVariables file -> ForeverAHDB as Python dicts/lists. Empty Lua tables become {}.
    A list of paths (one file per account) is loaded and merged into one table."""
    if isinstance(path, (list, tuple)):
        return merge([load(p) for p in path])
    # The file is Lua code. Run it with no Python access and no os/io.
    lua = LuaRuntime(register_eval=False, register_builtins=False)
    lua.execute("os, io, package, require, debug, dofile, loadfile = nil")
    lua.execute(Path(path).read_text(encoding="utf-8-sig"))
    db = lua.globals().ForeverAHDB
    if db is None:
        raise ValueError(f"ForeverAHDB not found in {path}")
    return _to_py(db)


def _split(chunks) -> list[tuple[int, ...]]:
    return [tuple(map(int, row.split(","))) for chunk in chunks or [] for row in chunk.split(";") if row]


def raw_rows(scan: dict) -> list[tuple[int, ...]]:
    # Changed 2026-10-11 (D15): rows carry a 6th field, the time-left band, from addon v0.2 on.
    # """[(item_id, count, buyout, min_bid, bid), ...] - empty if the addon already dropped raw."""
    """[(item_id, count, buyout, min_bid, bid[, time_left]), ...] - empty if the addon dropped raw.

    buyout is the total for the row. time_left is a band, 1 shortest .. 4 longest, 0 unknown;
    scans from before 2026-10-11 have no 6th field.
    """
    return _split(scan.get("raw"))


def agg_rows(scan: dict) -> dict[int, tuple[int, ...]]:
    """{item_id: (min, p10, p25, median, qty, auctions)} as computed by the addon."""
    return {row[0]: row[1:] for row in _split(scan.get("agg"))}


def aggregate(rows) -> dict[int, tuple[int, ...]]:
    """Per-item aggregates from raw rows. Must match Scanner.lua exactly (see its header)."""
    items: dict[int, list] = {}
    # Changed 2026-10-11 (D15): rows may have 5 or 6 fields; only the first three are used here.
    # for item_id, count, buyout, _min_bid, _bid in rows:
    for row in rows:
        item_id, count, buyout = row[:3]
        it = items.setdefault(item_id, [0, 0, {}])
        it[0] += count
        it[1] += 1
        if buyout > 0:
            unit = max(1, math.floor(buyout / count + 0.5))
            it[2][unit] = it[2].get(unit, 0) + count
    out = {}
    for item_id, (qty, auctions, by_price) in items.items():
        low = p10 = p25 = med = 0
        if by_price:
            prices = sorted(by_price)
            total = sum(by_price.values())
            low, p10, p25, cum = prices[0], None, None, 0
            for price in prices:
                cum += by_price[price]
                if p10 is None and cum * 10 >= total:
                    p10 = price
                if p25 is None and cum * 4 >= total:
                    p25 = price
                if cum * 2 >= total:
                    med = price
                    break
        out[item_id] = (low, p10, p25, med, qty, auctions)
    return out


def ledger_rows(db: dict) -> list[dict]:
    """Ledger strings -> dicts. Format: see Ledger.lua header."""
    out = []
    for row in db.get("ledger") or []:
        head, _, name = row.partition(",name=")
        ts, char, event, *pairs = head.split(",")
        rec = {"ts": int(ts), "char": char, "event": event}
        for pair in pairs:
            key, _, value = pair.partition("=")
            rec[key] = int(value) if value.lstrip("-").isdigit() else value
        if name:
            rec["name"] = name
        out.append(rec)
    return out


def items(db: dict) -> dict[int, dict]:
    """Item reference saved by Items.lua: {item_id: {name, vendor, stack, class_id, subclass_id}}.
    vendor is what a vendor pays for one unit, in copper (0 = not sellable to vendors)."""
    # Changed 2026-10-11: lines from addon v0.9 on also carry quality and item level (eight fields).
    # out = {}
    # for line in (db.get("items") or "").split("\n"):
    #     if line:
    #         item_id, vendor, stack, class_id, subclass_id, name = line.split("\t", 5)
    #         out[int(item_id)] = {"name": name, "vendor": int(vendor), "stack": int(stack),
    #                              "class_id": int(class_id), "subclass_id": int(subclass_id)}
    # return out
    out = {}
    for line in (db.get("items") or "").split("\n"):
        if not line:
            continue
        fields = line.split("\t")
        rec = {"vendor": int(fields[1]), "stack": int(fields[2]), "class_id": int(fields[3]), "subclass_id": int(fields[4])}
        if len(fields) >= 8:
            rec.update(quality=int(fields[5]), level=int(fields[6]), name="\t".join(fields[7:]))
        else:
            rec["name"] = "\t".join(fields[5:])
        out[int(fields[0])] = rec
    return out


def vendors(db: dict) -> dict[int, dict]:
    """What vendors charge, saved by Vendors.lua: {item_id: {price (copper per unit), stack,
    available (-1 = unlimited stock, else how many were left), vendor, zone}}."""
    out = {}
    for line in (db.get("vendors") or "").split("\n"):
        if line:
            item_id, price, stack, available, vendor, zone = line.split("\t")
            out[int(item_id)] = {"price": int(price) / max(1, int(stack)), "stack": int(stack),
                                 "available": int(available), "vendor": vendor, "zone": zone}
    return out


def recipes(db: dict) -> list[dict]:
    """Learned recipes saved by Recipes.lua, one dict per character and recipe:
    char, profession, skill, ts, recipe_id, name, item_id (0 = makes no item), qty_min, qty_max,
    cooldown (seconds left when read), reagents {item_id: qty}."""
    out = []
    for char, professions in (db.get("recipes") or {}).items():
        for profession, rec in professions.items():
            for line in (rec.get("list") or "").split("\n"):
                if not line:
                    continue
                recipe_id, item_id, low, high, cooldown, reagents, name = line.split("\t", 6)
                out.append({"char": char, "profession": profession, "skill": rec.get("skill", 0), "ts": rec.get("ts", 0),
                            "recipe_id": int(recipe_id), "name": name, "item_id": int(item_id), "qty_min": int(low),
                            "qty_max": int(high), "cooldown": int(cooldown), "reagents": _counts(reagents)})
    return out


def disenchants(db: dict) -> list[dict]:
    """Disenchant results saved by Disenchant.lua: ts, item_id, quality, level, class_id, gave {item_id: qty}."""
    out = []
    for line in db.get("disenchants") or []:
        ts, item_id, quality, level, class_id, gave = line.split("\t")
        out.append({"ts": int(ts), "item_id": int(item_id), "quality": int(quality), "level": int(level),
                    "class_id": int(class_id), "gave": _counts(gave)})
    return out


def _counts(text) -> dict[int, int]:
    return {int(i): int(n) for i, n in (pair.split(":") for pair in (text or "").split(",") if pair)}


def inventory(db: dict) -> dict[str, dict]:
    """Holdings per character (Inventory.lua): bags, bank, abank as {item_id: count}, auctions as
    a list of dicts, plus the <key>Ts timestamps and err if a snapshot failed."""
    fields = ("auction", "item", "qty", "buyout", "bid", "status", "seconds")
    out = {}
    for char, inv in (db.get("inv") or {}).items():
        rec = {k: v for k, v in inv.items() if k.endswith("Ts") or k == "err"}
        for key in ("bags", "bank", "abank"):
            rec[key] = _counts(inv.get(key))
        rec["auctions"] = [dict(zip(fields, map(int, row.split(":"))))
                           for row in (inv.get("auctions") or "").split(";") if row]
        out[char] = rec
    return out


def report(path) -> None:
    size_mb = Path(path).stat().st_size / 1e6
    t = time.perf_counter()
    db = load(path)
    parse_s = time.perf_counter() - t
    scans = db.get("scans") or []
    print(f"{path}: {size_mb:.1f} MB, parsed in {parse_s:.2f} s "
          f"[{'ok' if parse_s < MAX_PARSE_S else 'FAIL'} < {MAX_PARSE_S} s]")
    # Changed 2026-10-11: also print the events the client rejected (now saved by Core.lua).
    # print(f"client {db.get('build')}, {len(scans)} scans, {db.get('throttled', 0)} throttled replies")
    print(f"client {db.get('build')}, {len(scans)} scans, {db.get('throttled', 0)} throttled replies, "
          f"events missing in client: {db.get('missing') or 'none'}")
    for scan in scans:
        raw = raw_rows(scan)
        raw_mb = sum(len(c) for c in scan.get("raw") or []) / 1e6
        agg = agg_rows(scan)
        print(f"\nscan {scan['id']} ({scan.get('zone')})")
        print(f"  rows {scan['rows']} of {scan['n']} reported, {scan['items']} items, {scan['units']} units, "
              f"hasAllInfo misses {scan['miss']}, skipped {scan['skip']}")
        print(f"  wait {scan.get('waitSec')} s, process {scan.get('procSec')} s in {scan.get('frames')} frames "
              f"(slowest {scan.get('maxMs')} ms), time-left bands: {scan.get('tl') or 'none'}")
        if raw:
            same = aggregate(raw) == agg
            print(f"  raw {raw_mb:.1f} MB [{'ok' if raw_mb < MAX_RAW_MB else 'FAIL'} < {MAX_RAW_MB} MB], "
                  f"aggregates recomputed from raw: {'match' if same else 'MISMATCH'}")
        else:
            print("  raw dropped (only the newest scans keep it)")
        for item_id, name in CHECK_ITEMS.items():
            if item_id in agg:
                low, p10, p25, med, qty, auctions = agg[item_id]
                print(f"  T5 {name} {item_id}: {auctions} auctions, {qty} units, min {low}, median {med}")
            else:
                print(f"  T5 {name} {item_id}: NOT in scan")
    events = Counter(row["event"] for row in ledger_rows(db))
    print(f"\nledger: {dict(events) or 'empty'}")
    # Added 2026-10-11 (v0.9): recipes and disenchant results.
    known = Counter((r["char"], r["profession"]) for r in recipes(db))
    for (char, profession), count in sorted(known.items()):
        print(f"recipes {char}: {profession}, {count} learned")
    print(f"disenchants logged: {len(disenchants(db))}")
    print(f"vendor prices: {len(vendors(db))} items")   # added 2026-10-11 (v0.10)
    # Added 2026-10-11: holdings saved by Inventory.lua.
    for char, inv in inventory(db).items():
        print(f"inventory {char}: {len(inv['bags'])} items in bags, {len(inv['bank'])} in bank, "
              f"{len(inv['abank'])} in account bank, {len(inv['auctions'])} own auctions"
              + (f", ERROR {inv['err']}" if inv.get("err") else ""))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    report(sys.argv[1])
