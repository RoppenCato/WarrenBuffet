"""Local dashboard server with a Refresh endpoint.

    python -m dashboard.serve [--sv <path>] [--port 8765]

Serves dashboard/site on 127.0.0.1 only. POST /refresh pulls the news feed and the AHledger
pricetable, re-reads the SavedVariables file and rebuilds both pages - the Refresh button on
the pages calls it. Without this server the pages still open as plain files; only the button
does nothing.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
from pathlib import Path

from dashboard.build import ROOT, build, sv_path
from pipeline import news, planfile, savedvars, storage

SITE = ROOT / "dashboard" / "site"


def refresh(sv: Path, out: Path = SITE) -> list[str]:
    """Pull what can be pulled, rebuild either way. Returns one line per step."""
    steps = []
    try:
        new, _ = news.pull()
        steps.append(f"news: {new} new")
    except Exception as err:   # offline or feed down: keep what we have
        steps.append(f"news pull failed ({err})")
    try:
        # build(sv, None, True, out)   (2026-10-11: the in-game plan is written too)
        build(sv, None, True, out, plan_to=planfile.target())
        steps.append("prices pulled, pages and in-game plan rebuilt")
    except (Exception, SystemExit) as err:
        # build(sv, None, False, out)
        build(sv, None, False, out, plan_to=planfile.target())
        steps.append(f"price pull failed ({err}); rebuilt from stored data")
    try:   # added 2026-10-11: keep the Parquet store current as well
        table = savedvars.load(sv)
        scans = storage.ingest_scans(table)
        storage.ingest_ahledger()
        storage.ingest_ledger(table)
        storage.prune()
        steps.append(f"stored {scans['l1']} new scans")
    except Exception as err:
        steps.append(f"store failed ({err})")
    return steps


class Handler(http.server.SimpleHTTPRequestHandler):
    sv: Path

    def do_POST(self):
        # The custom header keeps other websites from triggering a refresh: browsers will not
        # send it cross-site without a preflight, and we never answer one.
        if self.path != "/refresh" or self.headers.get("X-ForeverAH") != "refresh":
            return self.send_error(404)
        try:
            body = {"ok": True, "steps": refresh(self.sv)}
        except (Exception, SystemExit) as err:
            body = {"ok": False, "steps": [f"build failed: {err}"]}
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sv", help="path to SavedVariables/ForeverAH.lua (else FOREVERAH_SV or data/local.json)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.sv = sv_path(args.sv)
    # build(Handler.sv, None, False, SITE)   # make sure the pages exist and match the current code
    build(Handler.sv, None, False, SITE, plan_to=planfile.target())   # pages and plan match the current code
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(Handler, directory=str(SITE)))
    print(f"ForeverAH dashboard on http://localhost:{args.port} - Ctrl+C to stop")
    server.serve_forever()
