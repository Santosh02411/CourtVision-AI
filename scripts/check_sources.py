"""Check which data sources your network can reach, and why a failing one fails.

    python scripts/check_sources.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.services import teams as T  # noqa: E402
from app.services.nba_data import CDN_PROFILES, ESPN_HEADERS, URL_ESPN_NEWS, URL_SCHEDULE, URL_SCOREBOARD  # noqa: E402


def probe(label: str, url: str, headers: dict, proxies=None) -> bool:
    t = time.time()
    try:
        r = requests.get(url, headers=headers, timeout=Config.HTTP_TIMEOUT, proxies=proxies)
        ok = r.status_code == 200
        print(f"{'OK  ' if ok else 'FAIL'} {label:<44} HTTP {r.status_code} in {time.time() - t:.1f}s")
        return ok
    except Exception as exc:
        print(f"FAIL {label:<44} {type(exc).__name__}: {str(exc)[:90]}")
        return False


def main() -> None:
    proxies = {"http": Config.NBA_PROXY, "https": Config.NBA_PROXY} if Config.NBA_PROXY else None
    print(f"timeout={Config.HTTP_TIMEOUT}s proxy={'yes' if proxies else 'no'}\n")
    cdn_ok = any(probe(f"cdn.nba.com schedule (header profile {i})", URL_SCHEDULE, h, proxies) for i, h in enumerate(CDN_PROFILES))
    probe("cdn.nba.com live scoreboard", URL_SCOREBOARD, CDN_PROFILES[0], proxies)
    probe("ESPN news", URL_ESPN_NEWS, ESPN_HEADERS, proxies)
    print("\nstats.nba.com (via nba_api, default headers) ...")
    try:
        from nba_api.stats.endpoints import LeagueStandingsV3
        t = time.time()
        kw = {"proxy": Config.NBA_PROXY} if Config.NBA_PROXY else {}
        rows = LeagueStandingsV3(season=T.current_season(), timeout=Config.HTTP_TIMEOUT, **kw).get_normalized_dict()["Standings"]
        print(f"OK   leaguestandingsv3 {T.current_season()}: {len(rows)} teams in {time.time() - t:.1f}s")
        stats_ok = True
    except Exception as exc:
        print(f"FAIL leaguestandingsv3: {type(exc).__name__}: {str(exc)[:120]}")
        stats_ok = False
    if not (cdn_ok and stats_ok):
        print("\nIf a source fails: try another network (mobile hotspot) or a VPN, raise COURTVISION_HTTP_TIMEOUT, "
              "or set NBA_PROXY in .env. stats.nba.com is frequently slow or blocked from some ISPs and cloud hosts.")


if __name__ == "__main__":
    main()
