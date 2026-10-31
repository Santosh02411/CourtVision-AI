"""Single gateway to every external NBA data source.

* stats.nba.com via `nba_api`  - standings, team/player stats, game logs, shot charts
* cdn.nba.com                  - full-season schedule, live scoreboard, box score, play-by-play
* ESPN public JSON             - news and injury reports (context only)

Everything is cached with provenance (see cache.py). Methods return plain JSON-serialisable
structures with snake_case keys and raise `DataUnavailable` when neither a live nor a cached copy exists.
Nothing is ever invented as a fallback.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import requests

from app.config import Config
from app.services import teams as T
from app.services.cache import Fetched, TTLCache
from app.services.util import today_et

logger = logging.getLogger("courtvision.data")

# NOTE: stats.nba.com is called with nba_api's own default headers (it needs several browser-like fields and rejects/ignores
# others), and cdn.nba.com is called with the profiles below. An `Origin` header is deliberately NOT sent (nba_api's own profiles omit it).
CDN_PROFILES = [
    {  # same profile nba_api uses for its live endpoints
        "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Cache-Control": "no-cache",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0", "Referer": "https://www.nba.com/",
    },
    {  # plain browser UA, nothing else
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "*/*",
    },
    {"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
]
ESPN_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CourtVisionAI/2.0)", "Accept": "application/json"}
CDN = "https://cdn.nba.com/static/json"
URL_SCHEDULE = f"{CDN}/staticData/scheduleLeagueV2.json"
URL_SCOREBOARD = f"{CDN}/liveData/scoreboard/todaysScoreboard_00.json"
URL_BOXSCORE = f"{CDN}/liveData/boxscore/boxscore_{{gid}}.json"
URL_PBP = f"{CDN}/liveData/playbyplay/playbyplay_{{gid}}.json"
URL_ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news"
URL_ESPN_INJ = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

HOUR, DAY = 3600, 86400
STATUS = {1: "scheduled", 2: "live", 3: "final"}


class _Sets(dict):
    """Result sets keyed by name; tolerant of casing differences, and of single-set endpoints."""

    def __missing__(self, key: str):
        for k, v in self.items():
            if k.lower().replace("_", "") == str(key).lower().replace("_", ""):
                return v
        if len(self) == 1:
            return next(iter(self.values()))
        raise KeyError(f"result set '{key}' not in {list(self)}")

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


def _lower_keys(rows: list[dict]) -> list[dict]:
    return [{k.lower(): v for k, v in r.items()} for r in rows]


class NBAData:
    def __init__(self, cache: TTLCache | None = None, timeout: int | None = None) -> None:
        self.timeout = timeout or Config.HTTP_TIMEOUT
        self.cache = cache or TTLCache(Config.CACHE_DIR if Config.DISK_CACHE else None)
        self.http = requests.Session()
        self._cdn_profile = 0          # index of the CDN header profile that last worked
        self._cdn_down_until = 0.0     # when cdn.nba.com is blocked for this network, go straight to the stats.nba.com fallback
        if Config.NBA_PROXY:
            self.http.proxies.update({"http": Config.NBA_PROXY, "https": Config.NBA_PROXY})

    # ------------------------------------------------------------------ helpers
    def _json(self, url: str, params: dict | None = None, cdn: bool = False) -> Any:
        """GET JSON. cdn.nba.com tries several header profiles when it answers 403 and remembers the one that works."""
        if not cdn:
            r = self.http.get(url, params=params, headers=ESPN_HEADERS, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        last: Exception | None = None
        order = [self._cdn_profile] + [i for i in range(len(CDN_PROFILES)) if i != self._cdn_profile]
        for i in order:
            try:
                r = self.http.get(url, params=params, headers=CDN_PROFILES[i], timeout=self.timeout)
                if r.status_code == 403:
                    last = requests.HTTPError(f"403 Forbidden from {url} (header profile {i})", response=r)
                    continue
                r.raise_for_status()
                self._cdn_profile = i
                return r.json()
            except requests.HTTPError as exc:
                last = exc
                break
        raise last or RuntimeError("request failed")

    def _stats(self, endpoint: str, **params: Any) -> dict[str, list[dict]]:
        """Call an nba_api stats endpoint and return {result_set_name: [row, ...]} with lower-case keys."""
        from nba_api.stats import endpoints  # imported lazily so tests can run without network libs

        cls = getattr(endpoints, endpoint)
        kwargs = {"proxy": Config.NBA_PROXY} if Config.NBA_PROXY else {}
        obj = cls(timeout=self.timeout, **kwargs, **params)   # default nba_api headers (known to work with stats.nba.com)
        normalized = obj.get_normalized_dict()
        return _Sets({name: _lower_keys(rows) for name, rows in normalized.items()})

    def _stats_dict(self, endpoint: str, **params: Any) -> dict:
        """Raw JSON of an nba_api stats endpoint (used for the V2/V3 endpoints whose payload mirrors the CDN files)."""
        from nba_api.stats import endpoints
        kwargs = {"proxy": Config.NBA_PROXY} if Config.NBA_PROXY else {}
        return getattr(endpoints, endpoint)(timeout=self.timeout, **kwargs, **params).get_dict()

    def _cdn_or_stats(self, cdn_fn, stats_fn):
        """Prefer cdn.nba.com; if it is blocked/unreachable, fall back to the equivalent stats.nba.com endpoint."""
        if time.time() >= self._cdn_down_until:
            try:
                return cdn_fn()
            except Exception as exc:
                self._cdn_down_until = time.time() + 300
                logger.warning("cdn.nba.com unavailable (%s) - using stats.nba.com fallback for 5 min", str(exc)[:120])
        return stats_fn()

    @staticmethod
    def is_current(season: str) -> bool:
        return season == T.current_season()

    def _ttl(self, season: str, current_ttl: int, past_ttl: int = 7 * DAY) -> int:
        return current_ttl if self.is_current(season) else past_ttl

    # ------------------------------------------------------------------ stats.nba.com
    def standings(self, season: str) -> Fetched:
        def go() -> list[dict]:
            return self._stats("LeagueStandingsV3", season=season, season_type="Regular Season")["Standings"]
        return self.cache.get(f"standings:{season}", self._ttl(season, 10 * 60), go, "NBA Stats · leaguestandingsv3")

    def team_stats(self, season: str, measure: str = "Advanced", last_n: int = 0) -> Fetched:
        def go() -> list[dict]:
            return self._stats(
                "LeagueDashTeamStats", season=season, season_type_all_star="Regular Season",
                measure_type_detailed_defense=measure, per_mode_detailed="PerGame", last_n_games=last_n,
            )["LeagueDashTeamStats"]
        return self.cache.get(f"teamstats:{season}:{measure}:{last_n}", self._ttl(season, 15 * 60), go,
                              f"NBA Stats · leaguedashteamstats ({measure}{', L' + str(last_n) if last_n else ''})")

    def player_stats(self, season: str, measure: str = "Base", last_n: int = 0) -> Fetched:
        def go() -> list[dict]:
            return self._stats(
                "LeagueDashPlayerStats", season=season, season_type_all_star="Regular Season",
                measure_type_detailed_defense=measure, per_mode_detailed="PerGame", last_n_games=last_n,
            )["LeagueDashPlayerStats"]
        return self.cache.get(f"playerstats:{season}:{measure}:{last_n}", self._ttl(season, 15 * 60), go,
                              f"NBA Stats · leaguedashplayerstats ({measure}{', L' + str(last_n) if last_n else ''})")

    def team_game_log(self, season: str) -> Fetched:
        def go() -> list[dict]:
            return self._stats("LeagueGameLog", season=season, season_type_all_star="Regular Season",
                               player_or_team_abbreviation="T")["LeagueGameLog"]
        return self.cache.get(f"teamlog:{season}", self._ttl(season, 30 * 60), go, "NBA Stats · leaguegamelog")

    def player_game_log(self, player_id: int, season: str) -> Fetched:
        def go() -> list[dict]:
            return self._stats("PlayerGameLog", player_id=player_id, season=season,
                               season_type_all_star="Regular Season")["PlayerGameLog"]
        return self.cache.get(f"plog:{player_id}:{season}", self._ttl(season, 30 * 60), go, "NBA Stats · playergamelog")

    def shot_chart(self, player_id: int, season: str) -> Fetched:
        def go() -> dict:
            sets = self._stats("ShotChartDetail", player_id=player_id, team_id=0, season_nullable=season,
                               season_type_all_star="Regular Season", context_measure_simple="FGA")
            return {"shots": sets.get("Shot_Chart_Detail", []), "league_avg": sets.get("LeagueAverages", [])}
        return self.cache.get(f"shots:{player_id}:{season}", self._ttl(season, 3 * HOUR), go, "NBA Stats · shotchartdetail")

    def player_info(self, player_id: int) -> Fetched:
        def go() -> dict:
            rows = self._stats("CommonPlayerInfo", player_id=player_id).get("CommonPlayerInfo", [])
            return rows[0] if rows else {}
        return self.cache.get(f"pinfo:{player_id}", 7 * DAY, go, "NBA Stats · commonplayerinfo")

    # ------------------------------------------------------------------ cdn.nba.com
    @staticmethod
    def _norm_team(t: dict) -> dict:
        team = T.team_by_id(t.get("teamId")) or T.team_by_abbr(t.get("teamTricode")) or {}
        return {
            "id": team.get("id") or t.get("teamId"),
            "abbr": team.get("abbr") or t.get("teamTricode"),
            "name": team.get("name") or f"{t.get('teamCity', '')} {t.get('teamName', '')}".strip(),
            "wins": t.get("wins"), "losses": t.get("losses"),
            "score": t.get("score") if t.get("score") not in (None, "") else None,
        }

    def _norm_game(self, g: dict) -> dict:
        status = STATUS.get(g.get("gameStatus"), "scheduled")
        home, away = self._norm_team(g.get("homeTeam") or {}), self._norm_team(g.get("awayTeam") or {})
        if status == "scheduled":
            home["score"] = away["score"] = None
        return {
            "game_id": g.get("gameId"),
            "date": (g.get("gameDateEst") or g.get("gameDate") or g.get("gameTimeUTC") or "")[:10],
            "start_utc": g.get("gameDateTimeUTC") or g.get("gameTimeUTC"),
            "status": status,
            "status_text": (g.get("gameStatusText") or "").strip(),
            "period": g.get("period"),
            "clock": g.get("gameClock"),
            "home": home, "away": away,
            "arena": g.get("arenaName"),
            "label": g.get("gameLabel") or "",
            "sub_label": g.get("gameSubLabel") or "",
            "series": g.get("seriesText") or "",
            "stage": {"001": "preseason", "002": "regular", "004": "playoffs", "005": "play-in", "006": "cup-final"}.get(
                str(g.get("gameId", ""))[:3], "regular"),
        }

    def schedule(self) -> Fetched:
        """Full current-season schedule incl. results (cdn schedule file only covers the current season)."""
        def go() -> list[dict]:
            raw = self._cdn_or_stats(lambda: self._json(URL_SCHEDULE, cdn=True),
                                     lambda: self._stats_dict("ScheduleLeagueV2", season=T.current_season()))
            out = []
            for day in (raw.get("leagueSchedule") or {}).get("gameDates", []):
                for g in day.get("games", []):
                    n = self._norm_game(g)
                    if n["stage"] != "preseason" and n["home"]["abbr"] and n["away"]["abbr"]:
                        out.append(n)
            return out
        return self.cache.get("schedule", 10 * 60, go, "NBA schedule (cdn.nba.com, falls back to stats.nba.com)")

    def scoreboard_today(self) -> Fetched:
        def go() -> dict:
            raw = self._cdn_or_stats(lambda: self._json(URL_SCOREBOARD, cdn=True),
                                     lambda: self._stats_dict("ScoreboardV3", game_date=today_et().isoformat()))
            sb = (raw or {}).get("scoreboard") or {}
            games = []
            for g in sb.get("games", []):
                n = self._norm_game(g)
                n["periods"] = {
                    "home": [p.get("score") for p in (g.get("homeTeam") or {}).get("periods", [])],
                    "away": [p.get("score") for p in (g.get("awayTeam") or {}).get("periods", [])],
                }
                leaders = g.get("gameLeaders") or {}
                n["leaders"] = {
                    side: ({"id": l.get("personId"), "name": l.get("name"), "pts": l.get("points"),
                            "reb": l.get("rebounds"), "ast": l.get("assists")} if l.get("personId") else None)
                    for side, l in (("home", leaders.get("homeLeaders")), ("away", leaders.get("awayLeaders")))
                }
                games.append(n)
            return {"date": sb.get("gameDate"), "games": games}
        return self.cache.get("scoreboard", 5, go, "NBA scoreboard (cdn.nba.com, falls back to stats.nba.com)", persist=False)

    def boxscore(self, game_id: str, final: bool = False) -> Fetched:
        def go() -> dict:
            return self._cdn_or_stats(
                lambda: (self._json(URL_BOXSCORE.format(gid=game_id), cdn=True) or {}).get("game") or {},
                lambda: self.box_from_v3(self._stats_dict("BoxScoreTraditionalV3", game_id=game_id)))
        return self.cache.get(f"box:{game_id}", DAY if final else 8, go, "NBA box score (cdn.nba.com, falls back to stats.nba.com)", persist=final)

    def playbyplay(self, game_id: str, final: bool = False) -> Fetched:
        def go() -> list[dict]:
            return self._cdn_or_stats(
                lambda: ((self._json(URL_PBP.format(gid=game_id), cdn=True) or {}).get("game") or {}).get("actions", []),
                lambda: ((self._stats_dict("PlayByPlayV3", game_id=game_id) or {}).get("game") or {}).get("actions", []))
        return self.cache.get(f"pbp:{game_id}", DAY if final else 8, go, "NBA play-by-play (cdn.nba.com, falls back to stats.nba.com)", persist=final)

    @staticmethod
    def box_from_v3(raw: dict) -> dict:
        """Reshape stats.nba.com BoxScoreTraditionalV3 into the cdn.nba.com boxscore `game` layout used by the parser."""
        g = (raw or {}).get("boxScoreTraditional") or {}
        out: dict[str, Any] = {"gameId": g.get("gameId")}
        for side in ("homeTeam", "awayTeam"):
            t = g.get(side) or {}
            totals = t.get("totals") or {}
            players = []
            for p in t.get("players", []):
                st = dict(p.get("statistics") or {})
                players.append({**p, "name": p.get("name") or p.get("nameI") or f"{p.get('firstName', '')} {p.get('familyName', '')}".strip(),
                                "starter": "1" if (p.get("position") or "").strip() else "0", "statistics": st})
            out[side] = {"teamId": t.get("teamId"), "teamTricode": t.get("teamTricode"), "score": totals.get("points", 0),
                         "players": players, "statistics": totals, "periods": []}
        return out

    # ------------------------------------------------------------------ ESPN (context only)
    def news(self, limit: int = 20) -> Fetched:
        def go() -> list[dict]:
            arts = (self._json(URL_ESPN_NEWS) or {}).get("articles", [])
            return [{
                "headline": a.get("headline"), "description": a.get("description"),
                "published": a.get("published"), "url": ((a.get("links") or {}).get("web") or {}).get("href"),
                "image": next((i.get("url") for i in a.get("images", []) if i.get("url")), None),
                "source": "ESPN",
            } for a in arts[:limit] if a.get("headline")]
        return self.cache.get("news", 10 * 60, go, "ESPN · NBA news")

    def injuries(self) -> Fetched:
        def go() -> list[dict]:
            out = []
            for tm in (self._json(URL_ESPN_INJ) or {}).get("injuries", []):
                team = T.resolve_team(tm.get("displayName"))
                for inj in tm.get("injuries", []):
                    ath = inj.get("athlete") or {}
                    out.append({
                        "team": team["abbr"] if team else None,
                        "player": ath.get("displayName"),
                        "player_id_espn": ath.get("id"),
                        "status": (inj.get("status") or "").strip(),
                        "detail": (inj.get("shortComment") or "")[:220],
                    })
            return out
        return self.cache.get("injuries", 15 * 60, go, "ESPN · injury report")

    # ------------------------------------------------------------------ health
    def probe(self) -> dict[str, Any]:
        """Cheap connectivity check for /health - reads cache state only, never blocks on the network."""
        keys = {"schedule": "schedule", "scoreboard": "scoreboard", "standings": f"standings:{T.current_season()}"}
        return {name: ("cached" if self.cache.peek(k) is not None else "cold") for name, k in keys.items()}
