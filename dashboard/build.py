"""Static dashboard from the addon's SavedVariables and the latest AHledger pricetable.

    python -m dashboard.build --sv "<...>\\SavedVariables\\ForeverAH.lua" [--pull]

Writes two pages to dashboard/site/ (ignored by git):
  index.html   Today  - suggestions from pipeline/planner.py, each with its reason
  market.html  Market - all tables and charts
First skeleton: it reads the SavedVariables file directly and will move to the Parquet/DuckDB
views once they exist (docs/04).
AHledger numbers are credited in the page footer and beside each use.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from collections import Counter
from pathlib import Path

import jinja2
import plotly.offline
import yaml

# Changed 2026-10-11: planner added for the Today page; money() moved to pipeline/analytics.py.
# from pipeline import ahledger, analytics, savedvars
from pipeline import ahledger, analytics, houses, news, planner, savedvars   # news, houses added 2026-10-11
from pipeline.analytics import money

ROOT = Path(__file__).resolve().parent.parent
# Changed 2026-10-11: the realm -> house mapping moved to plan/houses.yaml (pipeline/houses.py).
# # realm + faction -> AHledger market id (D12). Extend at launch.
# HOUSES = {("Classic Beta PvE", "Horde"): "forever.normal.horde.us",
#           ("Classic Beta PvE", "Alliance"): "forever.normal.alliance.us"}
DEPTH_ITEMS = [2589, 2770]   # order books shown: Linen Cloth, Copper Ore
MIN_SOLD = 50                # sold/day for an item to count as liquid


# def money(copper: float) -> str:   (moved to pipeline/analytics.py, see the import above)
#     copper = round(copper)
#     sign, copper = ("-" if copper < 0 else ""), abs(copper)
#     g, s, c = copper // 10000, copper // 100 % 100, copper % 100
#     return sign + (f"{g:,}g {s:02}s" if g else f"{s}s {c:02}c" if s else f"{c}c")


def pct(new: float, old: float) -> str:
    if not old:
        return ""
    change = (new - old) / old * 100
    return "no change" if abs(change) < 0.5 else f"{'▲' if change > 0 else '▼'} {abs(change):,.0f}%"


def when(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# Changed 2026-10-11: two accounts means two SavedVariables files, and the launch client will use
# another folder. The function now returns a list and can find every account's file by itself
# from the game folder ("wow" in data/local.json). savedvars.load merges a list into one table.
# def sv_path(arg: str | None) -> Path:
#     """SavedVariables file: --sv, else FOREVERAH_SV, else "sv" in data/local.json (not committed)."""
#     local = ROOT / "data" / "local.json"
#     path = arg or os.environ.get("FOREVERAH_SV") or (
#         json.loads(local.read_text(encoding="utf-8")).get("sv") if local.exists() else None)
#     if not path:
#         raise SystemExit('no SavedVariables path: pass --sv, set FOREVERAH_SV, or put {"sv": "..."} in data/local.json')
#     return Path(path)
def sv_path(arg: str | None) -> list[Path]:
    """SavedVariables files, one per account. In order: --sv, FOREVERAH_SV, "sv" in data/local.json
    (a path or a list), else every WTF/Account/*/SavedVariables/ForeverAH.lua under "wow" in
    data/local.json. data/local.json is not committed."""
    file = ROOT / "data" / "local.json"
    local = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    explicit = arg or os.environ.get("FOREVERAH_SV") or local.get("sv")
    if explicit:
        return [Path(p) for p in ([explicit] if isinstance(explicit, str) else explicit)]
    if local.get("wow"):
        found = sorted(Path(local["wow"]).glob("WTF/Account/*/SavedVariables/ForeverAH.lua"))
        if found:
            return found
        raise SystemExit(f"no ForeverAH.lua under {local['wow']} - has the addon run and the game been reloaded?")
    raise SystemExit('no SavedVariables path: pass --sv, set FOREVERAH_SV, or put {"wow": "<game folder>"} in data/local.json')


# Changed 2026-10-11: `today` added so a date can be previewed (launch week before launch).
# def build(sv, market: str | None, pull: bool, out: Path) -> Path:   # sv: a path, or one per account
def build(sv, market: str | None, pull: bool, out: Path, today: dt.date | None = None) -> Path:
    today = today or dt.date.today()
    db = savedvars.load(sv)
    scans = [s for s in db.get("scans") or [] if s.get("raw")]
    if not scans:
        raise SystemExit("no scan with raw rows in the SavedVariables file")
    # Changed 2026-10-11: alts on the other faction scan a different house, so "previous" must
    # be the previous scan of the same house, not simply the one before.
    # cur, prev = scans[-1], (scans[-2] if len(scans) > 1 else None)
    cur = scans[-1]
    house = [s for s in scans if (s["realm"], s["faction"]) == (cur["realm"], cur["faction"])]
    prev = house[-2] if len(house) > 1 else None
    # market = market or HOUSES.get((cur["realm"], cur["faction"]))
    market = market or houses.house_id(cur["realm"], cur["faction"])
    if not market:
        # raise SystemExit(f"no house id known for {cur['realm']} / {cur['faction']} - pass --market")
        raise SystemExit(f"realm {cur['realm']!r} is not in plan/houses.yaml - add it there, or pass --market")

    rows = savedvars.raw_rows(cur)
    book, agg = analytics.books(rows), savedvars.agg_rows(cur)
    prev_rows = savedvars.raw_rows(prev) if prev else []
    prev_book, prev_agg = analytics.books(prev_rows), (savedvars.agg_rows(prev) if prev else {})

    if pull:
        ahledger.pull_pricetable(market, ROOT / "data")
    table = ahledger.latest_pricetable(market, ROOT / "data")
    if not table:
        raise SystemExit("no AHledger pricetable in data/ - run with --pull")
    ahl_head, ahl = table
    sold = {i: p.sold_per_day or 0 for i, p in ahl.items()}
    median = {i: analytics.weighted_median(b) for i, b in book.items()}

    watch = yaml.safe_load((ROOT / "plan" / "watchlist.yaml").read_text(encoding="utf-8"))["categories"]
    names = {e["id"]: e["name"] for entries in watch.values() for e in entries if e.get("id")}

    # -- where the gold moves: estimated value traded per day, liquid items only
    markets = sorted(((sold[i] * median[i], i) for i in book if sold.get(i, 0) >= MIN_SOLD), reverse=True)[:12]
    # -- flip candidates: 30 % below both today's median and AHledger's 7-day median
    resale = {i: min(median[i], ahl[i].median_7d or median[i]) for i in book if i in ahl}
    deals = analytics.underpriced(book, resale, sold, min_sold=MIN_SOLD)[:10]
    ledger = savedvars.ledger_rows(db)
    # -- cross-check: own median vs AHledger median, every item both saw
    both = [(i, median[i], ahl[i].median) for i in book if i in ahl and ahl[i].median]
    worst = sorted(((abs(a - b) / b, i, a, b) for i, a, b in both if sold.get(i, 0) >= MIN_SOLD), reverse=True)[:8]
    wanted = [i for _, i in markets] + [d["item_id"] for d in deals] + [w[1] for w in worst]
    wanted += [r["item"] for r in ledger if isinstance(r.get("item"), int)]

    # -- Today page inputs (added 2026-10-11): holdings, own auctions, calendar -> planner
    summary = analytics.ledger_summary(ledger)
    inventories = savedvars.inventory(db)
    # Changed 2026-10-11: every character counts, not just the one seen last. Goods are added
    # up across characters (they all end up with the trader); `where` remembers who holds what.
    # char = max(inventories, key=lambda c: inventories[c].get("bagsTs", 0), default=None)
    # inv = inventories.get(char, {"bags": {}, "bank": {}, "abank": {}, "auctions": []})
    # holdings = Counter(inv["bags"]) + Counter(inv["bank"]) + Counter(inv["abank"])
    trader = db.get("trader")
    holdings, where, own_auctions = Counter(), {}, []
    for who, rec in inventories.items():
        mine = Counter(rec["bags"]) + Counter(rec["bank"])
        holdings += mine
        for item_id, units in mine.items():
            where.setdefault(item_id, []).append(f"{who.split('-')[0]} {units:,}")
        own_auctions += [dict(a, char=who.split("-")[0]) for a in rec["auctions"]]
    shared = max(inventories.values(), key=lambda rec: rec.get("abankTs", 0), default={"abank": {}})["abank"]
    holdings += Counter(shared)   # the account bank is one place: count its newest snapshot once
    for item_id, units in shared.items():
        where.setdefault(item_id, []).append(f"account bank {units:,}")
    inv = {"auctions": own_auctions, "err": "; ".join(r["err"] for r in inventories.values() if r.get("err")) or None}
    for key in ("bagsTs", "auctionsTs"):
        seen = [r[key] for r in inventories.values() if key in r]
        if seen:
            inv[key] = max(seen)
    budget = summary["chars"][trader]["last"] if trader in summary["chars"] else summary["last"]
    plan = yaml.safe_load((ROOT / "plan" / "calendar.yaml").read_text(encoding="utf-8"))
    # Changed 2026-10-11: launch week mode (D30). In a market's first week nothing has a price
    # history, so a different rule set runs: vendor floor, deposit, trend since the last scan.
    # cal = planner.calendar(plan, dt.date.today())
    # sells = planner.sell(dict(holdings), book, ahl, cal["phase"]["id"] if cal["phase"] else None)
    cal = planner.calendar(plan, today)
    phase_id = cal["phase"]["id"] if cal["phase"] else None
    reference = savedvars.items(db)                       # names and vendor prices from the addon
    vendor = {i: r["vendor"] for i, r in reference.items()}
    names.update({i: r["name"] for i, r in reference.items()})
    category = {e["id"]: cat for cat, entries in watch.items() for e in entries if e.get("id")}
    launch = planner.launch_mode(phase_id, book, ahl)
    if launch:
        sells = planner.sell_launch(dict(holdings), book, prev_book, vendor, category)
    else:
        sells = planner.sell(dict(holdings), book, ahl, phase_id)
    reposts = planner.repost(inv["auctions"], book)
    # buys = planner.buy(book, ahl, summary["last"])   (2026-10-11: the trader's gold is the budget)
    # buys = planner.buy(book, ahl, budget)   (2026-10-11: no flips in launch week, only below-vendor lots)
    buys = [] if launch else planner.buy(book, ahl, budget)
    vendor_buys = planner.below_vendor(book, vendor, budget) if launch else []
    wanted += [d["item_id"] for d in vendor_buys]
    wanted += list(holdings) + [a["item"] for a in inv["auctions"]] + [d["item_id"] for d in buys]
    names.update(ahledger.item_names(market, [i for i in wanted if i not in names], ROOT / "data"))

    def name(item_id):
        return names.get(item_id, f"item {item_id}")

    figs = {}
    top = markets[::-1]   # largest at the top of a horizontal bar chart
    figs["fig-markets"] = {
        "data": [{"type": "bar", "orientation": "h", "meta": {"role": "primary"},
                  "y": [name(i) for _, i in top], "x": [round(v / 10000, 1) for v, _ in top],
                  "text": [f"{v / 10000:,.0f}g" for v, _ in top], "textposition": "outside", "cliponaxis": False,
                  "customdata": [[round(sold[i]), money(median[i])] for _, i in top],
                  "hovertemplate": "<b>%{y}</b><br>%{x:,.0f}g traded per day<br>%{customdata[0]:,} sold/day"
                                   " at %{customdata[1]}<extra></extra>"}],
        "layout": {"height": 30 * len(top) + 60, "margin": {"l": 170, "r": 60, "t": 8, "b": 36}, "bargap": 0.45,
                   "barcornerradius": 4, "xaxis": {"title": {"text": "gold traded per day (estimate)"}},
                   "yaxis": {"showgrid": False}},
    }

    for item_id in DEPTH_ITEMS:
        if item_id not in book:
            continue
        limit = median[item_id] * 1.6
        traces = []
        for label, b, role in ((when(prev["ts"])[11:] if prev else "", prev_book.get(item_id), "context"),
                               (when(cur["ts"])[11:], book[item_id], "primary")):
            if not b:
                continue
            xs, ys, cum = [], [], 0
            for price, qty in b:
                if price > limit:
                    break
                cum += qty
                xs.append(price)
                ys.append(cum)
            traces.append({"type": "scatter", "mode": "lines", "name": f"scan {label}", "meta": {"role": role},
                           "x": xs, "y": ys, "line": {"shape": "hv", "width": 2},
                           "hovertemplate": "%{y:,} units at %{x}c or less<extra>scan " + label + "</extra>"})
        figs[f"fig-book-{item_id}"] = {
            "data": traces,
            "layout": {"height": 300, "margin": {"l": 64, "r": 16, "t": 8, "b": 44}, "hovermode": "x unified",
                       "xaxis": {"title": {"text": "unit price (copper)"}},
                       "yaxis": {"title": {"text": "units listed at or below"}, "rangemode": "tozero"},
                       "legend": {"orientation": "h", "x": 0, "y": 1.12}},
        }

    agree = sum(abs(a - b) <= 0.10 * b for _, a, b in both)
    lo, hi = 1, max(max(a, b) for _, a, b in both)
    figs["fig-check"] = {
        "data": [{"type": "scatter", "mode": "lines", "x": [lo, hi], "y": [lo, hi], "meta": {"role": "context"},
                  "line": {"width": 1}, "hoverinfo": "skip", "showlegend": False},
                 {"type": "scattergl", "mode": "markers", "meta": {"role": "primary"}, "showlegend": False,
                  "x": [b for _, _, b in both], "y": [a for _, a, _ in both], "text": [name(i) for i, _, _ in both],
                  "marker": {"size": 6, "opacity": 0.45},
                  "hovertemplate": "<b>%{text}</b><br>own scan %{y:,}c<br>AHledger %{x:,}c<extra></extra>"}],
        "layout": {"height": 380, "margin": {"l": 64, "r": 16, "t": 8, "b": 44},
                   "xaxis": {"type": "log", "title": {"text": "AHledger median (copper)"}},
                   "yaxis": {"type": "log", "title": {"text": "own scan median (copper)"}}},
    }

    # -- watchlist: now vs previous scan, depth, days of stock
    watchlist = []
    watch_ids = {e["id"] for entries in watch.values() for e in entries}
    for item_id, label in names.items():
        if item_id not in agg or item_id not in watch_ids:
            continue
        low, _, _, med, qty, _ = agg[item_id]
        p_low, _, _, p_med, p_qty, _ = prev_agg.get(item_id, (0,) * 6)
        per_day = sold.get(item_id, 0)
        watchlist.append({"name": label, "min": money(low), "min_change": pct(low, p_low), "median": money(med),
                          "median_change": pct(med, p_med), "units": qty, "units_change": pct(qty, p_qty),
                          "depth": analytics.depth(book[item_id]) if item_id in book else 0,
                          "sold": round(per_day), "days": f"{qty / per_day:.1f}" if per_day else "",
                          "sort": -per_day})
    watchlist.sort(key=lambda r: r["sort"])

    # summary = analytics.ledger_summary(ledger)   (2026-10-11: computed earlier, the planner needs the balance)
    shown = {"post", "cancel", "bought", "sold", "expired", "cancelled", "money"}
    trades = [{"time": when(r["ts"])[11:], "event": r["event"],
               "item": r.get("name") or (name(r["item"]) if r.get("item") else ""),
               "qty": r.get("qty", ""), "amount": money(r["unit"] * r["qty"]) if r["event"] == "post" and r.get("unit")
               else money(r["total"]) if r.get("total") else money(r["delta"]) if "delta" in r else ""}
              for r in ledger if r["event"] in shown]

    bands = dict(p.split(":") for p in (cur.get("tl") or "").split(",") if p)
    hours = (cur["ts"] - prev["ts"]) / 3600 if prev else 0
    context = {
        "page": "market",   # added 2026-10-11: two pages share base.html.j2
        "title": f"{cur['realm']} · {cur['faction']}", "market": market, "scan_time": when(cur["ts"]),
        "prev_time": when(prev["ts"])[11:] if prev else None, "hours": f"{hours:.1f}",
        "ahl_time": when(ahl_head["ts"])[11:], "attribution": ahledger.ATTRIBUTION, "min_sold": MIN_SOLD,
        "tiles": [
            {"label": "Auctions", "value": f"{cur['rows']:,}", "note": pct(cur["rows"], prev["rows"]) + f" vs {when(prev['ts'])[11:]}" if prev else ""},
            {"label": "Units listed", "value": f"{cur['units']:,}", "note": pct(cur["units"], prev["units"]) + f" vs {when(prev['ts'])[11:]}" if prev else ""},
            {"label": "Items", "value": f"{cur['items']:,}", "note": "distinct item ids"},
            {"label": "Listed value", "value": money(sum(r[2] for r in rows)).split(" ")[0], "note": "sum of all buyouts"},
            {"label": "Ending soonest", "value": f"{int(bands.get('1', 0)):,}", "note": f"{int(bands.get('1', 0)) / cur['rows']:.1%} of auctions in time-left band 1"},
        ],
        "markets": [{"name": name(i), "value": money(v), "sold": round(sold[i]), "price": money(median[i])} for v, i in markets],
        "deals": [{"name": name(d["item_id"]), "units": d["units"], "avg": money(d["avg_buy"]), "resale": money(d["resale"]),
                   "cost": money(d["cost"]), "profit": money(d["profit"]), "roi": f"{d['profit'] / d['cost']:.0%}",
                   "sold": round(d["sold_per_day"])} for d in deals],
        "books": [{"id": f"fig-book-{i}", "name": name(i), "depth": analytics.depth(book[i]), "min": money(book[i][0][0]),
                   "levels": [{"price": money(p), "units": q} for p, q in book[i][:10]]} for i in DEPTH_ITEMS if i in book],
        "check": {"count": len(both), "agree": f"{agree / len(both):.0%}",
                  "worst": [{"name": name(i), "own": money(a), "ahl": money(b), "diff": f"{d:.0%}"} for d, i, a, b in worst]},
        "watchlist": watchlist,
        "ledger": {"start": money(summary["first"]), "end": money(summary["last"]), "bought": money(summary["bought"]),
                   "sold": money(summary["sold"]), "other": money(summary["other"]), "posts": summary["posts"]},
        "trades": trades,
        "figs_json": json.dumps(figs),
        "plotlyjs": plotly.offline.get_plotlyjs(),
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # ---- Today page (added 2026-10-11): the planner's suggestions, formatted
    goals_file = ROOT / "plan" / "goals.yaml"
    mount = (yaml.safe_load(goals_file.read_text(encoding="utf-8")) or {}).get("mount", {}) if goals_file.exists() else {}
    mount_goal = mount.get("gold", planner.MOUNT_FUND / 10000) * 10000
    labels = {"vendor": "Vendor it", "choice": "Your call",   # launch week actions, added 2026-10-11
              "sell": "Sell", "hold": "Hold", "keep": "Keep collecting", "price": "Check price",
              "repost": "Repost", "leave": "Leave", "buy": "Buy", "short": "Over budget"}
    quiet = {"keep", "price", "leave", "short", "hold"}

    def row(rec, action, **extra):
        return {"label": labels[action], "quiet": action in quiet, "name": name(rec["item_id"]),
                "units": rec["units"], "why": rec["why"], **extra}

    age_min = max(0, (time.time() - cur["ts"]) / 60)
    active = [a for a in inv["auctions"] if a["status"] == 0]
    nxt = cal["upcoming"][0] if cal["upcoming"] else None

    def event_label(event_id):
        return event_id.replace("_", " ").capitalize()

    # -- news (added 2026-10-11): flagged headlines waiting for a review, and what past reviews found
    stories, watch_names = news.load(), news.watch_names()
    flagged = news.flagged(stories, watch_names)
    recent = (dt.date.today() - dt.timedelta(days=14)).isoformat()

    def story(s):
        return {"title": s["title"], "link": s["link"], "date": (s.get("published") or "")[:10],
                "why": "; ".join(s["reasons"])}

    news_ctx = {
        "waiting": [story(s) for s in flagged if s["score"] >= news.REVIEW_SCORE],
        "weak": [story(s) for s in flagged if s["score"] < news.REVIEW_SCORE],
        "reviewed": [r for r in sorted(news.reviewed(), key=lambda r: str(r.get("date")), reverse=True)
                     if r.get("verdict") in ("relevant", "minor") and str(r.get("date")) >= recent],
        "stored": len(stories), "attribution": news.ATTRIBUTION,
        "prompt": "Review the flagged news",
    }

    today = {
        "news": news_ctx,
        "page": "today", "title": context["title"], "market": market, "attribution": ahledger.ATTRIBUTION,
        "generated": context["generated"], "scan_time": when(cur["ts"])[11:],
        "age": f"{age_min / 60:.0f} h {age_min % 60:.0f} min" if age_min >= 60 else f"{age_min:.0f} min",
        # "stale": age_min > 60, "balance": money(summary["last"]),   (2026-10-11: trader-aware)
        "stale": age_min > 60,
        "balance": f"{trader.split('-')[0]} has {money(budget)}" if trader in summary["chars"] else f"You have {money(budget)}",
        "has_inventory": "bagsTs" in inv, "inv_time": when(inv["bagsTs"])[11:] if "bagsTs" in inv else "",
        "has_auctions": "auctionsTs" in inv, "auctions_time": when(inv["auctionsTs"])[11:] if "auctionsTs" in inv else "",
        "inv_err": inv.get("err"),
        "tiles": [
            # {"label": "Gold", "value": money(summary["last"]), "note": f"{char or 'no character yet'}"},
            {"label": "Gold", "value": money(summary["last"]),
             "note": f"{len(summary['chars'])} character{'s' if len(summary['chars']) != 1 else ''}"
                     + (f", trader {trader.split('-')[0]}" if trader else ", no trader set (/fah trader)")},
            {"label": "Items held", "value": f"{len(holdings):,}", "note": "sellable, in bags and bank"},
            {"label": "Own auctions", "value": f"{len(active):,}", "note": "active"},
            {"label": "Next date", "value": f"{nxt['days']} days" if nxt else "-", "note": event_label(nxt["id"]) if nxt else ""},
        ],
        # Changed 2026-10-11: who holds it / whose auction it is.
        # "sells": [row(r, r["action"], price=money(r["price"]) if "price" in r else "",
        #               net=money(r["net"]) if r["action"] in ("sell", "hold") else "") for r in sells],
        # "reposts": [row(r, r["action"], price=money(r["price"]), cheapest=money(r["cheapest"]) if r["cheapest"] else "none",
        #                 left=f"{r['hours']:.1f} h") for r in reposts],
        # "net" also shown for vendor and your-call rows (2026-10-11)
        "sells": [row(r, r["action"], price=money(r["price"]) if "price" in r else "",
                      net=money(r["net"]) if r["action"] in ("sell", "hold", "vendor", "choice") else "",
                      where=", ".join(where.get(r["item_id"], []))) for r in sells],
        # Launch week mode (added 2026-10-11)
        "launch": {"day": cal["phase_day"], "focus": cal["phase"].get("focus", "") if cal["phase"] else "",
                   "dated": phase_id in planner.NO_HOLD_PHASES} if launch else None,
        # Changed 2026-10-11: the goal comes from plan/goals.yaml - the price is only reported, and
        # which characters need a mount is the player's choice. planner.MOUNT_FUND is the fallback.
        # "mount": {"have": money(summary["last"]), "goal": money(planner.MOUNT_FUND),
        #           "pct": f"{min(1, summary['last'] / planner.MOUNT_FUND):.0%}"},
        "mount": {"have": money(summary["last"]), "goal": money(mount_goal), "label": mount.get("label", "level 40 mount"),
                  "pct": f"{min(1, summary['last'] / mount_goal):.0%}", "confirmed": mount.get("status") == "confirmed"},
        "has_vendor": bool(vendor),
        "vendor_buys": [row(d, "buy" if d["affordable"] else "short", max_price=money(d["max_price"]),
                            vendor=money(d["vendor"]), cost=money(d["cost"]), profit=money(d["profit"]))
                        for d in vendor_buys],
        "reposts": [row(r, r["action"], price=money(r["price"]), cheapest=money(r["cheapest"]) if r["cheapest"] else "none",
                        left=f"{r['hours']:.1f} h", char=r["char"]) for r in reposts],
        "buys": [row(d, "buy" if d["affordable"] else "short", max_price=money(d["max_price"]), resale=money(d["resale"]),
                     cost=money(d["cost"]), profit=money(d["profit"])) for d in buys],
        "phase": {"label": event_label(cal["phase"]["id"]), "focus": cal["phase"].get("focus", "")} if cal["phase"] else None,
        "upcoming": [{"days": e["days"], "date": e["date"].isoformat(), "label": event_label(e["id"]), "note": e["note"]}
                     for e in cal["upcoming"]],
    }

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / "dashboard" / "templates"), autoescape=True)
    # Changed 2026-10-11: two pages instead of one; `out` is now the site directory.
    # out.parent.mkdir(parents=True, exist_ok=True)
    # out.write_text(env.get_template("index.html.j2").render(**context), encoding="utf-8")
    # return out
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(env.get_template("today.html.j2").render(**today), encoding="utf-8")
    (out / "market.html").write_text(env.get_template("market.html.j2").render(**context), encoding="utf-8")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Changed 2026-10-11: the path can also come from data/local.json, see sv_path().
    # parser.add_argument("--sv", default=os.environ.get("FOREVERAH_SV"), help="path to SavedVariables/ForeverAH.lua")
    parser.add_argument("--sv", help="path to SavedVariables/ForeverAH.lua (else FOREVERAH_SV or data/local.json)")
    parser.add_argument("--market", help="AHledger market id; default from realm and faction")
    parser.add_argument("--pull", action="store_true", help="fetch a fresh AHledger pricetable first")
    # parser.add_argument("--out", default=str(ROOT / "dashboard" / "site" / "index.html"))   (2026-10-11: a directory now)
    parser.add_argument("--out", default=str(ROOT / "dashboard" / "site"), help="output directory")
    parser.add_argument("--date", type=dt.date.fromisoformat,   # added 2026-10-11
                        help="pretend today is this date, e.g. 2026-11-06 to preview launch week")
    args = parser.parse_args()
    # if not args.sv:
    #     parser.error("--sv or FOREVERAH_SV is required")
    # print(build(Path(args.sv), args.market, args.pull, Path(args.out)))
    # print(build(sv_path(args.sv), args.market, args.pull, Path(args.out)))
    print(build(sv_path(args.sv), args.market, args.pull, Path(args.out), args.date))
