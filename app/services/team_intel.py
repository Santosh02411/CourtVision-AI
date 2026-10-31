"""Team intelligence: Elo (538 method), ratings table, power rankings, form and the pre-game feature state."""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import date
from math import log
from typing import Any

from app.services import teams as T
from app.services.cache import DataUnavailable, Fetched
from app.services.nba_data import NBAData
from app.services.util import num, rnd, zscores

logger = logging.getLogger("courtvision.teams")

ELO_INITIAL, ELO_MEAN, ELO_K, ELO_HOME, ELO_CARRY = 1500.0, 1505.0, 20.0, 100.0, 0.75
ELO_SEASONS = 3
MARGIN_SHRINK_K, FORM_SHRINK_K, FORM_WINDOW = 8.0, 5.0, 10


# ---------------------------------------------------------------- game list from team game log
def games_from_log(rows: list[dict], season: str) -> list[dict]:
    """Pair the two team rows of each game into one chronological game record."""
    by_game: dict[str, dict] = {}
    for r in rows:
        gid, tid, matchup = r.get("game_id"), r.get("team_id"), r.get("matchup") or ""
        pts = num(r.get("pts"))
        if not gid or not tid or pts is None:
            continue
        g = by_game.setdefault(gid, {"game_id": gid, "date": str(r.get("game_date"))[:10], "season": season})
        g["home_id" if " vs. " in matchup else "away_id"] = tid
        g["home_pts" if " vs. " in matchup else "away_pts"] = pts
    games = [g for g in by_game.values() if {"home_id", "away_id", "home_pts", "away_pts"} <= g.keys()]
    games.sort(key=lambda g: (g["date"], g["game_id"]))
    return games


# ---------------------------------------------------------------- Elo / feature state
def elo_expected(elo_home: float, elo_away: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(elo_home + ELO_HOME - elo_away) / 400.0))


def elo_update(elo_home: float, elo_away: float, home_pts: float, away_pts: float) -> tuple[float, float]:
    home_win = home_pts > away_pts
    exp_home = elo_expected(elo_home, elo_away)
    winner_diff = (elo_home + ELO_HOME - elo_away) if home_win else (elo_away - elo_home - ELO_HOME)
    mov = abs(home_pts - away_pts)
    mult = ((mov + 3) ** 0.8) / (7.5 + 0.006 * winner_diff)
    delta = ELO_K * mult * ((1.0 if home_win else 0.0) - exp_home)
    return elo_home + delta, elo_away - delta


FEATURES = ["elo_diff", "margin_diff", "form_diff", "rest_diff", "b2b_home", "b2b_away"]
FEATURE_LABELS = {
    "elo_diff": "Elo rating gap", "margin_diff": "Season point differential", "form_diff": "Recent form (last 10)",
    "rest_diff": "Rest advantage", "b2b_home": "Home back-to-back", "b2b_away": "Away back-to-back",
}


class LeagueState:
    """Replays games chronologically; `features()` is always computed from games strictly before the target game."""

    def __init__(self) -> None:
        self.elo: dict[int, float] = defaultdict(lambda: ELO_INITIAL)
        self.margins: dict[int, list[float]] = defaultdict(list)
        self.recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=FORM_WINDOW))
        self.last_date: dict[int, date] = {}
        self.season: str | None = None
        self.results: dict[int, list[dict]] = defaultdict(list)       # current-season results per team
        self.elo_history: dict[int, list[dict]] = defaultdict(list)    # current-season Elo path per team
        self.games_by_season: list[tuple[str, list[dict]]] = []

    def start_season(self, season: str) -> None:
        for tid in list(self.elo):
            self.elo[tid] = ELO_CARRY * self.elo[tid] + (1 - ELO_CARRY) * ELO_MEAN
        self.margins.clear(); self.recent.clear(); self.last_date.clear(); self.results.clear(); self.elo_history.clear()
        self.season = season

    def _rest(self, tid: int, d: date) -> int:
        last = self.last_date.get(tid)
        return 3 if last is None else max(0, min(4, (d - last).days - 1))

    def team_margin(self, tid: int) -> float:
        m = self.margins[tid]
        return sum(m) / (len(m) + MARGIN_SHRINK_K) if m else 0.0

    def team_form(self, tid: int) -> float:
        r = self.recent[tid]
        return sum(r) / (len(r) + FORM_SHRINK_K) if r else 0.0

    def features(self, home: int, away: int, d: date) -> dict[str, float]:
        rest_h, rest_a = self._rest(home, d), self._rest(away, d)
        return {
            "elo_diff": (self.elo[home] - self.elo[away]) / 100.0,
            "margin_diff": self.team_margin(home) - self.team_margin(away),
            "form_diff": self.team_form(home) - self.team_form(away),
            "rest_diff": float(max(-3, min(3, rest_h - rest_a))),
            "b2b_home": 1.0 if rest_h == 0 else 0.0,
            "b2b_away": 1.0 if rest_a == 0 else 0.0,
            "_rest_home": rest_h, "_rest_away": rest_a,
        }

    def update(self, g: dict, d: date, keep_history: bool = False) -> None:
        h, a, hp, ap = g["home_id"], g["away_id"], g["home_pts"], g["away_pts"]
        self.elo[h], self.elo[a] = elo_update(self.elo[h], self.elo[a], hp, ap)
        self.margins[h].append(hp - ap); self.margins[a].append(ap - hp)
        self.recent[h].append(hp - ap); self.recent[a].append(ap - hp)
        self.last_date[h] = self.last_date[a] = d
        if keep_history:
            for tid, opp, pts, opp_pts, home in ((h, a, hp, ap, True), (a, h, ap, hp, False)):
                self.results[tid].append({"game_id": g["game_id"], "date": g["date"], "opp_id": opp, "home": home,
                                          "pts": pts, "opp_pts": opp_pts, "win": pts > opp_pts})
                self.elo_history[tid].append({"date": g["date"], "elo": round(self.elo[tid], 1)})


def replay(games_by_season: list[tuple[str, list[dict]]], on_game=None) -> LeagueState:
    """games_by_season oldest -> newest. `on_game(state, game, date, features)` fires before each update."""
    from app.services.util import parse_date
    state = LeagueState()
    last_idx = len(games_by_season) - 1
    for idx, (season, games) in enumerate(games_by_season):
        state.start_season(season)
        for g in games:
            d = parse_date(g["date"])
            if d is None:
                continue
            if on_game:
                on_game(state, g, d, state.features(g["home_id"], g["away_id"], d))
            state.update(g, d, keep_history=(idx == last_idx))
    return state


# ---------------------------------------------------------------- service
class TeamIntel:
    def __init__(self, data: NBAData) -> None:
        self.data = data

    # -- season resolution: never show an empty new season ---------------------------------
    def resolve_season(self, requested: str | None) -> tuple[str, list[str], list[Fetched]]:
        season = requested or T.current_season()
        notes: list[str] = []
        if season == T.current_season():
            try:
                f = self.data.standings(season)
                played = sum((num(r.get("wins"), 0) or 0) + (num(r.get("losses"), 0) or 0) for r in f.data)
                if played == 0:
                    prev = T.previous_season(season)
                    notes.append(f"{season} has no completed games yet - showing {prev} final statistics.")
                    return prev, notes, []
                return season, notes, [f]
            except DataUnavailable:
                notes.append("Standings are unavailable right now, so the season state couldn't be verified; sections load independently.")
                return season, notes, []
        return season, notes, []

    # -- team state (Elo etc.) ---------------------------------------------------------------
    def state(self, season: str) -> tuple[LeagueState, list[Fetched]]:
        seasons = list(reversed(T.recent_seasons(season, ELO_SEASONS)))
        prov, per_season = [], []
        for s in seasons:
            try:
                f = self.data.team_game_log(s)
            except DataUnavailable:
                if s == season:
                    raise
                continue  # an older season missing only weakens the Elo prior
            prov.append(f)
            per_season.append((s, games_from_log(f.data, s)))
        st = replay(per_season)
        st.games_by_season = per_season
        return st, prov

    # -- league table ------------------------------------------------------------------------
    def table(self, season: str) -> dict[str, Any]:
        adv = self.data.team_stats(season, "Advanced")
        base = self.data.team_stats(season, "Base")
        stand = self.data.standings(season)
        prov = [adv, base, stand]
        l10 = None
        try:
            l10 = self.data.team_stats(season, "Advanced", last_n=10); prov.append(l10)
        except DataUnavailable:
            pass
        state, p2 = self.state(season); prov += p2

        base_by = {r["team_id"]: r for r in base.data}
        stand_by = {r["teamid"]: r for r in stand.data}
        l10_by = {r["team_id"]: r for r in (l10.data if l10 else [])}
        rows = []
        for r in adv.data:
            tid = r["team_id"]; meta = T.team_by_id(tid)
            if not meta:
                continue
            b, s, f = base_by.get(tid, {}), stand_by.get(tid, {}), l10_by.get(tid)
            form = state.recent.get(tid)
            rows.append({
                **{k: meta[k] for k in ("id", "abbr", "name", "conference", "division", "primary", "secondary", "logo")},
                "gp": r.get("gp"), "w": r.get("w"), "l": r.get("l"), "w_pct": rnd(r.get("w_pct"), 3),
                "off_rating": rnd(r.get("off_rating")), "def_rating": rnd(r.get("def_rating")),
                "net_rating": rnd(r.get("net_rating")), "pace": rnd(r.get("pace")),
                "efg_pct": rnd(num(r.get("efg_pct"), 0) * 100), "ts_pct": rnd(num(r.get("ts_pct"), 0) * 100),
                "tov_pct": rnd(num(r.get("tm_tov_pct"), 0) * 100 if num(r.get("tm_tov_pct"), 0) < 1 else r.get("tm_tov_pct")),
                "oreb_pct": rnd(num(r.get("oreb_pct"), 0) * 100), "ast_pct": rnd(num(r.get("ast_pct"), 0) * 100),
                "pie": rnd(num(r.get("pie"), 0) * 100), "pts": rnd(b.get("pts")), "reb": rnd(b.get("reb")),
                "ast": rnd(b.get("ast")), "fg_pct": rnd(num(b.get("fg_pct"), 0) * 100),
                "fg3_pct": rnd(num(b.get("fg3_pct"), 0) * 100),
                "elo": round(state.elo[tid], 1) if tid in state.elo else None,
                "last10": s.get("l10"), "streak": (s.get("strcurrentstreak") or "").strip(),
                "home_record": s.get("home"), "road_record": s.get("road"),
                "conf_rank": s.get("playoffrank"), "conf_gb": s.get("conferencegamesback"),
                "l10_net_rating": rnd(f.get("net_rating")) if f else None,
                "l10_margin": rnd(sum(form) / len(form)) if form else None,
                "net_trend": rnd(num(f.get("net_rating"), 0) - num(r.get("net_rating"), 0)) if f else None,
            })
        if not rows:
            raise DataUnavailable("NBA Stats", "team table is empty")
        rows.sort(key=lambda x: -(x["net_rating"] or -99))
        return {"teams": rows, "league_avg": self._league_avg(rows)}, prov, state

    @staticmethod
    def _league_avg(rows: list[dict]) -> dict[str, float]:
        keys = ["off_rating", "def_rating", "net_rating", "pace", "efg_pct", "ts_pct", "tov_pct", "oreb_pct", "pts", "fg3_pct"]
        return {k: round(sum(r[k] or 0 for r in rows) / len(rows), 2) for k in keys}

    # -- power rankings ----------------------------------------------------------------------
    def power_rankings(self, rows: list[dict]) -> list[dict]:
        z_net = zscores([r["net_rating"] for r in rows])
        z_elo = zscores([r["elo"] for r in rows])
        z_form = zscores([r["l10_margin"] for r in rows])
        z_win = zscores([r["w_pct"] for r in rows])
        out = []
        for i, r in enumerate(rows):
            comp = 0.40 * z_net[i] + 0.30 * z_elo[i] + 0.20 * z_form[i] + 0.10 * z_win[i]
            out.append({**r, "power_score": round(max(0, min(100, 50 + 18 * comp)), 1),
                        "components": {"net_rating_z": round(z_net[i], 2), "elo_z": round(z_elo[i], 2),
                                       "form_z": round(z_form[i], 2), "win_pct_z": round(z_win[i], 2)}})
        out.sort(key=lambda r: -r["power_score"])
        for rank, r in enumerate(out, 1):
            r["power_rank"] = rank
            r["record_rank"] = None
            r["tier"] = "Contender" if rank <= 6 else "Playoff team" if rank <= 12 else "Bubble" if rank <= 20 else "Rebuilding"
            r["blurb"] = self.blurb(r)
        by_w = sorted(out, key=lambda r: -(r["w_pct"] or 0))
        for i, r in enumerate(by_w, 1):
            r["record_rank"] = i
        return out

    @staticmethod
    def blurb(r: dict) -> str:
        parts = [f"{r['name']} are {r['w']}-{r['l']} with a {r['net_rating']:+.1f} net rating"]
        if r.get("off_rating") is not None:
            parts.append(f"({r['off_rating']:.1f} ORtg / {r['def_rating']:.1f} DRtg)")
        txt = " ".join(parts) + "."
        if r.get("net_trend") is not None and abs(r["net_trend"]) >= 3:
            txt += f" Last 10 games net rating is {'up' if r['net_trend'] > 0 else 'down'} {abs(r['net_trend']):.1f} vs the season."
        return txt

    # -- single-team profile -----------------------------------------------------------------
    def profile(self, rows: list[dict], state: LeagueState, team: dict, schedule: list[dict] | None) -> dict:
        row = next((r for r in rows if r["id"] == team["id"]), None)
        if row is None:
            raise KeyError(team["abbr"])
        results = state.results.get(team["id"], [])
        margins = [r["pts"] - r["opp_pts"] for r in results]
        roll = []
        for i in range(len(margins)):
            w = margins[max(0, i - 9): i + 1]
            roll.append({"date": results[i]["date"], "rolling_margin": round(sum(w) / len(w), 2), "margin": margins[i]})
        recent = []
        for r in reversed(results[-10:]):
            opp = T.team_by_id(r["opp_id"]) or {}
            recent.append({"game_id": r["game_id"], "date": r["date"], "opp": opp.get("abbr"), "home": r["home"],
                           "pts": int(r["pts"]), "opp_pts": int(r["opp_pts"]), "win": r["win"]})
        upcoming = []
        for g in (schedule or []):
            if g["status"] != "final" and team["abbr"] in (g["home"]["abbr"], g["away"]["abbr"]):
                upcoming.append(g)
        upcoming = sorted(upcoming, key=lambda g: (g["date"], g["start_utc"] or ""))[:6]
        return {"team": row, "elo_history": state.elo_history.get(team["id"], []), "rolling_margin": roll,
                "recent_results": recent, "upcoming": upcoming}
