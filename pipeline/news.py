"""News that may move the market: Wowhead's Forever feed.

    python -m pipeline.news pull       fetch the feed, add new stories to data/news/wowhead.json
    python -m pipeline.news pending    list flagged stories nobody has reviewed yet

We keep headline, date, link and a short summary only; the article stays on wowhead.com.
Credit Wowhead with a link wherever these are shown (ATTRIBUTION). data/ is never committed.
Reviewed stories live in plan/news-log.yaml (committed) - see "News review" in CLAUDE.md.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

FEED = "https://www.wowhead.com/news/rss/forever"
ATTRIBUTION = {"text": "News from Wowhead", "url": "https://www.wowhead.com/news"}
USER_AGENT = "WarrenBuffet/0.1 (personal AH planner)"
ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "news" / "wowhead.json"
LOG = ROOT / "plan" / "news-log.yaml"
SUMMARY_CHARS = 300
REVIEW_SCORE = 2   # flagged stories at or above this wait for a review; weaker ones are only listed

# Why a headline is flagged. Whole words only - a bare "ore" would match "Forever".
TERMS = {
    "prices": r"vendor|sell prices?|auction house|black market|gold|deposit|econom\w+|gdkp|bann?ed|ban wave|bots?",
    "supply": r"drop rates?|drop chances?|respawn\w*|spawn rates?|nodes?|gathering|herbalism|herbs?|mining|skinning|fishing|scarce",
    "crafting": r"recipes?|professions?|craft\w*|alchemy|enchant\w*|blacksmithing|leatherworking|tailoring|engineering|cooking|transmut\w*|bags?",
    "dates": r"release date|launch date|roadmap|phase \d|hotfix\w*|raids? unlock\w*",
    "balance": r"(?:un-?)?nerf\w*|buff\w*",
}
WEIGHT = {"item": 3, "prices": 2, "supply": 2, "crafting": 2, "dates": 1, "balance": 1}
_PATTERNS = {reason: re.compile(rf"\b(?:{terms})\b", re.I) for reason, terms in TERMS.items()}


def parse_feed(xml_text: str) -> list[dict]:
    """RSS -> [{title, link, published (UTC ISO), summary}], newest first as in the feed."""
    stories = []
    for item in ET.fromstring(xml_text).iter("item"):
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        summary = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))).strip()
        summary = re.sub(r"\s*Continue reading\W*$", "", summary)
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).astimezone(dt.timezone.utc).isoformat()
        except (TypeError, ValueError):
            published = None
        stories.append({"title": html.unescape(title), "link": link, "published": published,
                        "summary": summary[:SUMMARY_CHARS]})
    return stories


def pull(store: Path = STORE) -> tuple[int, int]:
    """Fetch the feed and merge it into the store. Returns (new stories, stories stored)."""
    req = urllib.request.Request(FEED, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        fetched = parse_feed(resp.read().decode("utf-8", errors="replace"))
    stories = load(store)
    known = {s["link"] for s in stories}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    new = [dict(s, first_seen=now) for s in fetched if s["link"] not in known]
    stories = sorted(stories + new, key=lambda s: s.get("published") or s["first_seen"], reverse=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(stories, indent=1, ensure_ascii=False), encoding="utf-8")
    return len(new), len(stories)


def load(store: Path = STORE) -> list[dict]:
    return json.loads(store.read_text(encoding="utf-8")) if store.exists() else []


def flag(story: dict, item_names=()) -> list[str]:
    """Reasons a story may matter, strongest first: 'item: Linen Cloth', 'prices: sell prices', ..."""
    text = f"{story['title']}. {story.get('summary', '')}"
    reasons = [f"item: {name}" for name in sorted(set(item_names))
               if re.search(rf"\b{re.escape(name)}\b", text, re.I)]
    for reason, pattern in _PATTERNS.items():
        found = sorted({m.group(0).lower() for m in pattern.finditer(text)})
        if found:
            reasons.append(f"{reason}: {', '.join(found[:3])}")
    return sorted(reasons, key=lambda r: -WEIGHT[r.split(":")[0]])


def score(reasons: list[str]) -> int:
    return sum(WEIGHT[r.split(":")[0]] for r in reasons)


def reviewed(log: Path = LOG) -> list[dict]:
    return (yaml.safe_load(log.read_text(encoding="utf-8")) or {}).get("reviewed") or [] if log.exists() else []


def flagged(stories, item_names=(), log: Path = LOG, days: int = 14, today: dt.date | None = None) -> list[dict]:
    """Flagged stories from the last `days` days that are not in the review log, strongest first.
    Those with score >= REVIEW_SCORE are the ones waiting for a review (see pending)."""
    done = {r["link"] for r in reviewed(log)}
    cutoff = (today or dt.date.today()) - dt.timedelta(days=days)
    out = []
    for story in stories:
        when = story.get("published") or story.get("first_seen") or ""
        if story["link"] in done or when[:10] < cutoff.isoformat():
            continue
        reasons = flag(story, item_names)
        if reasons:
            out.append(dict(story, reasons=reasons, score=score(reasons)))
    out.sort(key=lambda s: s.get("published") or "", reverse=True)   # newest first ...
    return sorted(out, key=lambda s: -s["score"])                      # ... within each score


def pending(stories, item_names=(), **kwargs) -> list[dict]:
    return [s for s in flagged(stories, item_names, **kwargs) if s["score"] >= REVIEW_SCORE]


def watch_names() -> list[str]:
    """Names to look for in headlines: the watchlist plus every item name we have cached."""
    watch = yaml.safe_load((ROOT / "plan" / "watchlist.yaml").read_text(encoding="utf-8"))["categories"]
    names = {e["name"] for entries in watch.values() for e in entries}
    cache = ROOT / "data" / "reference" / "item_names.json"
    if cache.exists():
        names.update(json.loads(cache.read_text(encoding="utf-8")).values())
    return sorted(names)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) == 2 else ""
    if command == "pull":
        new, total = pull()
        print(f"{new} new stories, {total} stored - {ATTRIBUTION['text']} ({ATTRIBUTION['url']})")
    elif command == "pending":
        for s in flagged(load(), watch_names()):
            mark = "REVIEW" if s["score"] >= REVIEW_SCORE else "weak  "
            print(f"\n{mark} [{s['score']}] {(s.get('published') or '')[:10]}  {s['title']}\n    {s['link']}\n"
                  f"    why: {'; '.join(s['reasons'])}\n    {s['summary']}")
    else:
        sys.exit(__doc__)
