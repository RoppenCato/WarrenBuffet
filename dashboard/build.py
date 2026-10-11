"""Static dashboard from the addon's SavedVariables and the latest AHledger pricetable.

    python -m dashboard.build --sv "<...>\\SavedVariables\\ForeverAH.lua" [--pull]

Writes dashboard/site/index.html (ignored by git). First skeleton: it reads the SavedVariables
file directly and will move to the Parquet/DuckDB views once they exist (docs/04).
AHledger numbers are credited in the page footer and beside each use.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import jinja2
import plotly.offline
import yaml

from pipeline import ahledger, analytics, savedvars

ROOT = Path(__file__).resolve().parent.parent
# realm + faction -> AHledger market id (D12). Extend at launch.
HOUSES = {("Classic Beta PvE", "Horde"): "forever.normal.horde.us",
          ("Classic Beta PvE", "Alliance"): "forever.normal.alliance.us"}
DEPTH_ITEMS = [2589, 2770]   # order books shown: Linen Cloth, Copper Ore
MIN_SOLD = 50                # sold/day for an item to count as liquid


def money(copper: float) -> str:
    copper = round(copper)
    sign, copper = ("-" if copper < 0 else ""), abs(copper)
    g, s, c = copper // 10000, copper // 100 % 100, copper % 100
    return sign + (f"{g:,}g {s:02}s" if g else f"{s}s {c:02}c" if s else f"{c}c")


def pct(new: float, old: float) -> str:
    if not old:
        return ""
    change = (new - old) / old * 100
    return "no change" if abs(change) < 0.5 else f"{'▲' if change > 0 else '▼'} {abs(change):,.0f}%"


def when(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def build(sv: Path, market: str | None, pull: bool, out: Path) -> Path:
    db = savedvars.load(sv)
    scans = [s for s in db.get("scans") or [] if s.get("raw")]
    if not scans:
        raise SystemExit("no scan with raw rows in the SavedVariables file")
    cur, prev = scans[-1], (scans[-2] if len(scans) > 1 else None)
    market = market or HOUSES.get((cur["realm"], cur["faction"]))
    if not market:
        raise SystemExit(f"no house id known for {cur['realm']} / {cur['faction']} - pass --market")

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

    summary = analytics.ledger_summary(ledger)
    shown = {"post", "cancel", "bought", "sold", "expired", "cancelled", "money"}
    trades = [{"time": when(r["ts"])[11:], "event": r["event"],
               "item": r.get("name") or (name(r["item"]) if r.get("item") else ""),
               "qty": r.get("qty", ""), "amount": money(r["unit"] * r["qty"]) if r["event"] == "post" and r.get("unit")
               else money(r["total"]) if r.get("total") else money(r["delta"]) if "delta" in r else ""}
              for r in ledger if r["event"] in shown]

    bands = dict(p.split(":") for p in (cur.get("tl") or "").split(",") if p)
    hours = (cur["ts"] - prev["ts"]) / 3600 if prev else 0
    context = {
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
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / "dashboard" / "templates"), autoescape=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(env.get_template("index.html.j2").render(**context), encoding="utf-8")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sv", default=os.environ.get("FOREVERAH_SV"), help="path to SavedVariables/ForeverAH.lua")
    parser.add_argument("--market", help="AHledger market id; default from realm and faction")
    parser.add_argument("--pull", action="store_true", help="fetch a fresh AHledger pricetable first")
    parser.add_argument("--out", default=str(ROOT / "dashboard" / "site" / "index.html"))
    args = parser.parse_args()
    if not args.sv:
        parser.error("--sv or FOREVERAH_SV is required")
    print(build(Path(args.sv), args.market, args.pull, Path(args.out)))
