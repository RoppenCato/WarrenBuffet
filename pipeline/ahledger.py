"""AHledger API client (docs/02-data-sources.md).

AHledger data must be credited with a link to ahledger.com wherever it is shown - use
ATTRIBUTION. Raw pulls go under data/ (never committed).

    python -m pipeline.ahledger pull forever.normal.horde.us
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

BASE = "https://api.ahledger.com"
ATTRIBUTION = {"text": "Prices from AHledger", "url": "https://ahledger.com"}
USER_AGENT = "WarrenBuffet/0.1 (personal AH planner)"
DATA = Path("data")


class Price(NamedTuple):
    """One pricetable line. Money in copper; sold_per_day is their estimate."""
    median: int
    min_buyout: int
    quantity: int
    median_7d: int | None
    median_30d: int | None
    low_30d: int | None
    high_30d: int | None
    sold_per_day: float | None


def _get(path: str) -> str:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_pricetable(text: str) -> tuple[dict, dict[int, Price]]:
    """Header 'AHL1|forever/normal/horde/us|<unix>|<rows>', then one line per item:
    itemId:median:minBuyout:quantity:median7d:median30d:low30d:high30d:soldPerDay*10"""
    lines = text.strip().splitlines()
    magic, market, ts, rows = lines[0].split("|")
    if magic != "AHL1":
        raise ValueError(f"unknown pricetable format {magic!r}")
    prices = {}
    for line in lines[1:]:
        f = [int(x) if x else None for x in line.split(":")]
        f += [None] * (9 - len(f))
        prices[f[0]] = Price(f[1], f[2], f[3], f[4], f[5], f[6], f[7], None if f[8] is None else f[8] / 10)
    return {"market": market.replace("/", "."), "ts": int(ts), "rows": int(rows)}, prices


# Changed 2026-10-11: a house nobody has scanned yet (EU before launch) answers with a valid
# header, 0 rows and the current time. Saving that every hour would only pile up empty files.
# def pull_pricetable(market: str, data: Path = DATA) -> Path:
#     """Fetch the pricetable and keep the raw text as data/ahledger/<market>/<unix>.txt."""
#     text = _get(f"/v1/pricetable/{market}")
#     header, _ = parse_pricetable(text)
def pull_pricetable(market: str, data: Path = DATA) -> Path | None:
    """Fetch the pricetable and keep the raw text as data/ahledger/<market>/<unix>.txt.
    Returns None, and saves nothing, when the table is empty."""
    text = _get(f"/v1/pricetable/{market}")
    header, prices = parse_pricetable(text)
    if not prices:
        return None
    path = data / "ahledger" / market / f"{header['ts']}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():   # same snapshot again: their scan hasn't changed
        path.write_text(text, encoding="utf-8", newline="\n")
    return path


def latest_pricetable(market: str, data: Path = DATA) -> tuple[dict, dict[int, Price]] | None:
    files = sorted((data / "ahledger" / market).glob("*.txt"), key=lambda p: int(p.stem))
    return parse_pricetable(files[-1].read_text(encoding="utf-8")) if files else None


def item_names(market: str, item_ids, data: Path = DATA) -> dict[int, str]:
    """Item names from AHledger's price endpoint, cached in data/reference/item_names.json."""
    path = data / "reference" / "item_names.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for item_id in item_ids:
        if str(item_id) not in cache:
            try:
                cache[str(item_id)] = json.loads(_get(f"/v1/prices/{market}/{item_id}?range=7d"))["item"]["name"]
            except Exception:   # unknown item or network error: fall back to the id
                continue
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding="utf-8")
    return {int(k): v for k, v in cache.items()}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "pull":
        sys.exit(__doc__)
    saved = pull_pricetable(sys.argv[2])
    if saved is None:   # added 2026-10-11
        sys.exit(f"{sys.argv[2]}: no data yet - nobody has scanned this house")
    head, table = parse_pricetable(saved.read_text(encoding="utf-8"))
    print(f"{saved}: {len(table)} items, their scan at unix {head['ts']} - {ATTRIBUTION['text']} ({ATTRIBUTION['url']})")
