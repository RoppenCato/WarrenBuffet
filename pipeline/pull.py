"""One pull of everything external: the AHledger pricetable of every tracked house, and the news.

    python -m pipeline.pull

Meant to run hourly (tools\\pull.cmd from Task Scheduler). One line per run goes to
data/pull.log. A source that fails does not stop the others; the exit code is 1 if any failed.
Three small requests an hour - far inside AHledger's limits (300 a minute).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from pipeline import ahledger, houses, news

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "pull.log"


def run(data: Path = ROOT / "data") -> tuple[list[str], bool]:
    """Returns (one status per source, all ok)."""
    status, ok = [], True
    for market in houses.tracked():
        try:
            before = set((data / "ahledger" / market).glob("*.txt"))
            path = ahledger.pull_pricetable(market, data)
            status.append(f"{market}: " + ("empty" if path is None else "unchanged" if path in before else "new snapshot"))
        except Exception as err:
            status.append(f"{market}: FAILED {err}")
            ok = False
    try:
        new, total = news.pull(data / "news" / "wowhead.json")
        status.append(f"news: {new} new of {total}")
    except Exception as err:
        status.append(f"news: FAILED {err}")
        ok = False
    return status, ok


if __name__ == "__main__":
    lines, fine = run()
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {' | '.join(lines)}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(line + "\n")
    print(line)
    sys.exit(0 if fine else 1)
