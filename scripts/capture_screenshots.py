"""Capture numbered full-page screenshots of every CourtVision page from a RUNNING app.

    pip install playwright
    playwright install chromium
    python app.py                                   # in another terminal
    python scripts/capture_screenshots.py           # -> screenshots/dark/01-overview.png ... 14-models-evaluation.png

Options: --url http://127.0.0.1:5000  --out screenshots  --theme dark|light|both  --width 1440
Detail pages (game, player, team) use real ids looked up from your running app.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests


def pick_ids(base: str) -> dict:
    get = lambda p: requests.get(f"{base}/api/v1{p}", timeout=60).json().get("data") or {}
    ids = {"game": None, "player": None, "team": "LAL"}
    try:
        games = get("/schedule").get("games", [])
        finals = [g for g in games if g["status"] == "final"] or games
        ids["game"] = (finals[-1] if finals else {}).get("game_id")
    except Exception:
        pass
    try:
        ids["player"] = (get("/players?limit=1").get("players") or [{}])[0].get("id")
        top = (get("/teams").get("teams") or [{}])[0].get("abbr")
        ids["team"] = top or ids["team"]
    except Exception:
        pass
    return ids


def pages(ids: dict, tm: str) -> list[tuple[str, str]]:
    p = [("overview", "/overview"), ("live-games", "/live"), ("game-analytics", "/games")]
    if ids["game"]:
        p.append(("game-analytics-detail", f"/games/{ids['game']}"))
    p += [("predictions", "/predictions"), ("player-intelligence", "/players")]
    if ids["player"]:
        p.append(("player-profile", f"/players/{ids['player']}"))
    p += [("compare", "/compare")]
    if ids["player"]:
        p.append(("shot-analysis", f"/shots?player={ids['player']}"))
    else:
        p.append(("shot-analysis", "/shots"))
    p += [("team-analytics", "/teams"), ("team-profile", f"/teams/{ids['team']}"), ("standings-rankings", "/standings"),
          ("schedule", "/schedule"), ("models-evaluation", "/models")]
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:5000"); ap.add_argument("--out", default="screenshots")
    ap.add_argument("--theme", default="dark", choices=["dark", "light", "both"]); ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--wait", type=float, default=3.0, help="seconds to let charts/animations finish")
    ap.add_argument("--executable-path", default=None, help="use a specific Chromium binary instead of Playwright's")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    try:
        requests.get(f"{base}/api/v1/health", timeout=15).raise_for_status()
    except Exception as exc:
        print(f"Can't reach {base} - start the app first (python app.py). {exc}"); return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Run:  pip install playwright   then   playwright install chromium"); return 1

    ids = pick_ids(base)
    themes = ["dark", "light"] if a.theme == "both" else [a.theme]
    with sync_playwright() as pw:
        kw = {"executable_path": a.executable_path} if a.executable_path else {}
        browser = pw.chromium.launch(args=["--no-sandbox"], **kw)
        for theme in themes:
            out = Path(a.out) / theme; out.mkdir(parents=True, exist_ok=True)
            ctx = browser.new_context(viewport={"width": a.width, "height": 900}, color_scheme=theme)
            page = ctx.new_page()
            page.goto(base + "/", wait_until="networkidle"); page.evaluate("t => localStorage.setItem('cv.theme', t)", theme)
            for n, (name, hash_) in enumerate(pages(ids, ids["team"]), 1):
                page.set_viewport_size({"width": a.width, "height": 900})
                page.goto(f"{base}/#{hash_}"); page.reload(wait_until="networkidle"); page.wait_for_timeout(int(a.wait * 1000))
                h = page.evaluate("Math.ceil(document.documentElement.scrollHeight)")
                page.set_viewport_size({"width": a.width, "height": min(max(h, 900), 5000)}); page.wait_for_timeout(700)
                path = out / f"{n:02d}-{name}.png"; page.screenshot(path=str(path)); print("saved", path)
            ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
