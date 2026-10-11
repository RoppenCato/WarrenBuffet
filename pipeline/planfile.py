"""Today's plan as a Lua file the addon shows in game (docs/03-addon.md#planview).

The game cannot read files while it runs: it loads an addon's Lua files at login and on
/reload. So the plan seen in game is the one written before the last /reload - the dashboard is
the live view, the in-game plan a copy of it.

The file goes straight into the installed addon folder:
    <game folder>\\Interface\\AddOns\\ForeverAH\\ForeverAH_Plan.lua
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "ForeverAH_Plan.lua"
ROWS = 8   # suggestions per section; the window is small


def lua(value, indent: str = "") -> str:
    """A Python value as Lua source. Dicts become tables (integer keys as [n]), lists arrays."""
    inner = indent + "  "
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(round(value)) if float(value).is_integer() else repr(float(value))
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = []
        for key, item in value.items():
            name = f"[{key}]" if isinstance(key, int) else key if re.fullmatch(r"[A-Za-z_]\w*", key) else f"[{lua(key)}]"
            parts.append(f"{inner}{name} = {lua(item, inner)},")
        return "{\n" + "\n".join(parts) + f"\n{indent}}}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        return "{\n" + "\n".join(f"{inner}{lua(item, inner)}," for item in value) + f"\n{indent}}}"
    raise TypeError(f"cannot write {type(value).__name__} to Lua")


def make(scan_ts: int, labels: dict, name, sells=(), reposts=(), buys=(), books=None, headline: str = "",
         mode: str = "normal") -> dict:
    """The plan table from the planner's suggestions. `labels` maps an action to its wording,
    `name` an item id to its name. Money stays in copper; the addon formats it."""
    def act(rec, default=None):
        return labels[default or rec["action"]]

    plan = {
        "made": int(time.time()), "scan": scan_ts, "mode": mode, "headline": headline,
        "sell": [{"act": act(r), "item": name(r["item_id"]), "id": r["item_id"], "units": r["units"],
                  "price": r.get("price", 0), "get": round(r.get("net", 0)) if r["action"] != "keep" else 0, "why": r["why"]}
                 for r in list(sells)[:ROWS]],
        "auctions": [{"act": act(r), "item": name(r["item_id"]), "id": r["item_id"], "units": r["units"],
                      "price": r["price"], "cheapest": r["cheapest"] or 0, "why": r["why"]} for r in list(reposts)[:ROWS]],
        "buy": [{"act": act(d, "buy" if d["affordable"] else "short"), "item": name(d["item_id"]), "id": d["item_id"],
                 "units": d["units"], "max": d["max_price"], "cost": round(d["cost"]), "profit": round(d["profit"]),
                 "why": d["why"]} for d in list(buys)[:ROWS]],
        # per item, for tooltips: cheapest listing and median in the scan, and what the plan says
        "min": {i: b[0][0] for i, b in sorted((books or {}).items())},
        "act": {r["item_id"]: act(r) for r in sells},
    }
    return plan


def write(plan: dict, path: Path) -> Path:
    path.write_text("-- Written by pipeline/planfile.py from the latest scan. Do not edit: it is replaced on every\n"
                    "-- dashboard build. The game loads it at login and on /reload.\n"
                    f"ForeverAH_Plan = {lua(plan)}\n", encoding="utf-8", newline="\n")
    return path


def target() -> Path | None:
    """The plan file inside the installed addon, or None when no game folder is configured or the
    addon is not installed there ("wow" in data/local.json)."""
    file = ROOT / "data" / "local.json"
    wow = json.loads(file.read_text(encoding="utf-8")).get("wow") if file.exists() else None
    folder = Path(wow) / "Interface" / "AddOns" / "ForeverAH" if wow else None
    return folder / NAME if folder and folder.is_dir() else None
