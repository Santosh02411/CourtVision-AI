"""TEST-ONLY deterministic stand-in for NBAData (never imported by the app).

It reproduces the *shape* of the NBA Stats / CDN responses so every endpoint and the whole UI can be exercised offline.
Nothing here is ever served as real data by the application.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from app.services import teams as T
from app.services.cache import Fetched, TTLCache
from app.services.nba_data import NBAData

TODAY = date(2026, 11, 1)
ABBRS = sorted(T.BY_ABBR)


def _f(data, source="fake", status="fresh"):
    import time
    return Fetched(data, source, status, time.time())


class FakeNBAData(NBAData):
    def __init__(self, season_games: int = 8, past_games: int = 300, seed: int = 5) -> None:
        super().__init__(cache=TTLCache(None))
        self.rng = np.random.default_rng(seed)
        self.strength = {t["id"]: float(self.rng.normal(0, 4.5)) for t in T.TEAMS.values()}
        self.season_games, self.past_games = season_games, past_games
        self._logs: dict[str, list[dict]] = {}
        self._players = self._make_players()

    # ---------------------------------------------------------------- teams
    def _games(self, season: str) -> list[dict]:
        if season in self._logs:
            return self._logs[season]
        rng = np.random.default_rng(abs(hash(season)) % 10_000)
        cur = season == T.current_season()
        n = self.season_games * 15 if cur else self.past_games
        start = date(int(season[:4]), 10, 22)
        ids = list(T.TEAMS)
        rows = []
        for gi in range(n):
            h, a = rng.choice(ids, 2, replace=False)
            d = start + timedelta(days=int(gi / 7.5))
            if cur and d >= TODAY:
                break
            margin = (self.strength[h] - self.strength[a]) + 2.3 + rng.normal(0, 11)
            hp = int(round(112 + margin / 2 + rng.normal(0, 4))); ap = int(round(hp - margin))
            if hp == ap:
                hp += 1
            gid = f"002{season[2:4]}{gi:05d}"
            for tid, opp, pts, opp_pts, home in ((h, a, hp, ap, True), (a, h, ap, hp, False)):
                t, o = T.team_by_id(tid), T.team_by_id(opp)
                rows.append({"season_id": f"2{season[:4]}", "team_id": int(tid), "team_abbreviation": t["abbr"], "game_id": gid, "game_date": d.isoformat(),
                             "matchup": f"{t['abbr']} vs. {o['abbr']}" if home else f"{t['abbr']} @ {o['abbr']}", "wl": "W" if pts > opp_pts else "L",
                             "pts": pts, "plus_minus": pts - opp_pts})
        self._logs[season] = rows
        return rows

    def team_game_log(self, season):
        return _f(self._games(season))

    def _team_rows(self, season, measure, last_n=0):
        rng = np.random.default_rng(11 + last_n)
        played = {}
        for r in self._games(season):
            played.setdefault(r["team_id"], []).append(r)
        out = []
        for tid, t in T.TEAMS.items():
            g = played.get(tid, []); w = sum(1 for r in g if r["wl"] == "W"); gp = len(g)
            net = self.strength[tid] + (rng.normal(0, 2.5) if last_n else 0)
            off = 114 + net / 2 + rng.normal(0, 1); de = off - net
            base = {"team_id": tid, "team_name": t["name"], "gp": gp, "w": w, "l": gp - w, "w_pct": w / gp if gp else 0}
            if measure == "Advanced":
                out.append({**base, "off_rating": off, "def_rating": de, "net_rating": net, "pace": 98 + rng.normal(0, 2), "efg_pct": 0.54 + net / 400, "ts_pct": 0.575 + net / 380,
                            "tm_tov_pct": 0.135 + rng.normal(0, 0.008), "oreb_pct": 0.27 + rng.normal(0, .02), "ast_pct": 0.62 + rng.normal(0, .03), "pie": 0.5 + net / 90})
            else:
                out.append({**base, "pts": off + 2, "reb": 44 + rng.normal(0, 2), "ast": 25 + rng.normal(0, 2), "fg_pct": 0.465 + net / 500, "fg3_pct": 0.36 + rng.normal(0, .01)})
        return out

    def team_stats(self, season, measure="Advanced", last_n=0):
        return _f(self._team_rows(season, measure, last_n))

    def standings(self, season):
        rows = []
        adv = {r["team_id"]: r for r in self._team_rows(season, "Advanced")}
        for conf in ("East", "West"):
            ts = sorted([t for t in T.TEAMS.values() if t["conference"] == conf], key=lambda t: -adv[t["id"]]["w_pct"])
            for rank, t in enumerate(ts, 1):
                r = adv[t["id"]]
                rows.append({"teamid": t["id"], "conference": conf, "playoffrank": rank, "wins": r["w"], "losses": r["l"], "winpct": round(r["w_pct"], 3), "conferencegamesback": rank - 1,
                             "home": "3-1", "road": "2-2", "l10": "6-4", "strcurrentstreak": "W2", "conferencerecord": "3-2", "pointspg": 114.0, "opppointspg": 111.0, "diffpointspg": 3.0, "clinchindicator": ""})
        return _f(rows)

    # ---------------------------------------------------------------- players
    def _make_players(self):
        rng = np.random.default_rng(3); first = ["Jalen", "Marcus", "Devin", "Tyrese", "Luka", "Nikola", "Jayson", "Anthony", "Jaylen", "Cade"]; last = ["Brooks", "Carter", "Dawson", "Ellis", "Foster", "Grant", "Hayes", "Irving", "Jones", "Knight", "Lewis", "Moore"]
        out = []
        for i in range(210):
            t = T.team_by_id(list(T.TEAMS)[i % 30]); star = rng.random() < .15
            m = float(rng.uniform(24, 36) if i % 7 < 5 else rng.uniform(8, 20))
            out.append({"id": 1630000 + i, "name": f"{first[i % 10]} {last[(i * 7) % 12]} {i}", "team_id": t["id"], "min": m, "pts": float(m * rng.uniform(.35, .75) * (1.25 if star else 1)),
                        "reb": float(m * rng.uniform(.1, .35)), "ast": float(m * rng.uniform(.05, .3)), "stl": float(rng.uniform(.3, 1.8)), "blk": float(rng.uniform(.1, 1.6)), "tov": float(rng.uniform(.8, 3.2)),
                        "fg3m": float(rng.uniform(.2, 3.4)), "ts": float(rng.uniform(.5, .66)), "usg": float(rng.uniform(.14, .33)), "pie": float(rng.uniform(.06, .19) + (.03 if star else 0)), "age": int(rng.integers(20, 36))})
        return out

    def player_stats(self, season, measure="Base", last_n=0):
        rng = np.random.default_rng(21 + last_n); gp = 8 if last_n == 0 else 8
        rows = []
        for p in self._players:
            j = 1 + (rng.normal(0, .18) if last_n else 0)
            if measure == "Base":
                rows.append({"player_id": p["id"], "player_name": p["name"], "team_id": p["team_id"], "team_abbreviation": T.team_by_id(p["team_id"])["abbr"], "age": p["age"], "gp": gp, "min": p["min"], "pts": p["pts"] * j,
                             "reb": p["reb"], "ast": p["ast"], "stl": p["stl"], "blk": p["blk"], "tov": p["tov"], "fg3m": p["fg3m"], "fg_pct": 0.47, "fg3_pct": 0.36, "ft_pct": 0.8, "plus_minus": (p["pie"] - .1) * 40})
            else:
                rows.append({"player_id": p["id"], "ts_pct": p["ts"], "efg_pct": p["ts"] - .03, "usg_pct": p["usg"], "pie": p["pie"], "net_rating": (p["pie"] - .1) * 60, "off_rating": 115, "def_rating": 112, "ast_pct": p["ast"] / 40, "reb_pct": p["reb"] / 60})
        return _f(rows)

    def player_game_log(self, player_id, season):
        rng = np.random.default_rng(player_id); p = next((x for x in self._players if x["id"] == player_id), self._players[0]); rows = []
        for i in range(12):
            d = TODAY - timedelta(days=2 * (12 - i)); pts = max(0, int(rng.normal(p["pts"], 6)))
            rows.append({"game_id": f"002{i:07d}", "game_date": d.strftime("%b %d, %Y").upper(), "matchup": "LAL vs. DEN", "wl": "W" if rng.random() > .45 else "L", "min": int(p["min"]), "fgm": pts // 3, "fga": max(1, pts // 2), "fg_pct": .47,
                         "fg3m": 2, "fta": 4, "reb": int(rng.normal(p["reb"], 2)), "ast": int(rng.normal(p["ast"], 2)), "stl": 1, "blk": 0, "tov": 2, "pts": pts, "plus_minus": int(rng.normal(0, 8))})
        return _f(rows)

    def player_info(self, player_id):
        return _f({"position": "Guard", "height": "6-5", "weight": "205", "jersey": "7", "country": "USA", "school": "Duke", "draft_year": "2019", "draft_number": "4", "from_year": 2019})

    def shot_chart(self, player_id, season):
        rng = np.random.default_rng(player_id % 997); shots = []
        for i in range(380):
            if rng.random() < .35:
                r, th = rng.uniform(0, 38), rng.uniform(-math.pi / 2, math.pi / 2)
            else:
                r, th = rng.uniform(40, 300), rng.uniform(-1.4, 1.4)
            x, y = r * math.sin(th), r * math.cos(th); dist = math.hypot(x, y) / 10
            three = dist >= 23.75 or (abs(x) >= 220 and y <= 90)
            if abs(x) < 80 and y < 142: zone = "Restricted Area" if dist <= 4 else "In The Paint (Non-RA)"
            elif dist <= 4: zone = "Restricted Area"
            elif abs(x) >= 220 and y <= 89.5: zone = "Left Corner 3" if x < 0 else "Right Corner 3"
            elif three: zone = "Above the Break 3"
            else: zone = "Mid-Range"
            p = 0.64 if dist < 4 else 0.42 if dist < 22 else 0.36
            shots.append({"game_id": f"002{i % 8:07d}", "game_date": (TODAY - timedelta(days=(i % 8) * 2)).strftime("%Y%m%d"), "period": 1 + i % 4, "minutes_remaining": int(rng.integers(0, 12)), "seconds_remaining": int(rng.integers(0, 60)),
                          "shot_type": "3PT Field Goal" if three else "2PT Field Goal", "shot_zone_basic": zone, "shot_zone_area": "Center(C)", "shot_zone_range": "8-16 ft.", "shot_distance": int(dist), "loc_x": int(x), "loc_y": int(y),
                          "shot_made_flag": int(rng.random() < p), "action_type": "Jump Shot"})
        lg = [{"shot_zone_basic": z, "shot_zone_area": "Center(C)", "shot_zone_range": "x", "fga": 1000, "fgm": int(1000 * f), "fg_pct": f} for z, f in [("Restricted Area", .65), ("In The Paint (Non-RA)", .42), ("Mid-Range", .41), ("Left Corner 3", .38), ("Right Corner 3", .38), ("Above the Break 3", .36)]]
        return _f({"shots": shots, "league_avg": lg})

    # ---------------------------------------------------------------- schedule / live
    def _sched(self):
        ids = list(T.TEAMS); rng = np.random.default_rng(8); games = []
        for k in range(-6, 8):
            d = TODAY + timedelta(days=k)
            for j in range(4 + (k % 3)):
                h, a = ids[(k * 7 + j * 3) % 30], ids[(k * 11 + j * 5 + 7) % 30]
                if h == a: a = ids[(ids.index(a) + 1) % 30]
                st = 3 if k < 0 else (2 if (k == 0 and j == 0) else 1)
                ht, at = T.team_by_id(h), T.team_by_id(a)
                games.append({"game_id": f"00226{(k + 6):02d}{j:03d}", "date": d.isoformat(), "start_utc": f"{d.isoformat()}T{23 + 0 if j < 1 else 19 + j}:30:00Z".replace("T23", "T23").replace("T20:", "T20:"),
                              "status": {1: "scheduled", 2: "live", 3: "final"}[st], "status_text": {1: "7:30 pm ET", 2: "Q3 5:12", 3: "Final"}[st], "period": 3 if st == 2 else (4 if st == 3 else 0), "clock": "PT05M12.00S" if st == 2 else None,
                              "home": {"id": h, "abbr": ht["abbr"], "name": ht["name"], "wins": 4, "losses": 3, "score": int(100 + rng.integers(0, 25)) if st > 1 else None},
                              "away": {"id": a, "abbr": at["abbr"], "name": at["name"], "wins": 3, "losses": 4, "score": int(100 + rng.integers(0, 25)) if st > 1 else None},
                              "arena": f"{ht['city']} Arena", "label": "", "sub_label": "", "series": "", "stage": "regular"})
        return games

    def schedule(self):
        return _f(self._sched())

    def scoreboard_today(self):
        g = [x for x in self._sched() if x["date"] == TODAY.isoformat()]
        for x in g:
            x["periods"] = {"home": [28, 25, 20], "away": [26, 27, 22]}; x["leaders"] = {"home": None, "away": None}
        return _f({"date": TODAY.isoformat(), "games": g})

    def _game(self, gid):
        return next((x for x in self._sched() if x["game_id"] == gid), self._sched()[0])

    def playbyplay(self, game_id, final=False):
        g = self._game(game_id); h, a = g["home"]["id"], g["away"]["id"]; rng = np.random.default_rng(int(game_id[-4:] or 1)); acts = []; sh = sa = 0; n = 0
        for period in range(1, 5 if g["status"] == "final" else 4):
            secs = 720.0
            while secs > 8:
                secs -= float(rng.uniform(8, 26)); secs = max(secs, 0.0); n += 1
                team = h if rng.random() < .5 else a; r = rng.random()
                clock = f"PT{int(secs // 60):02d}M{secs % 60:05.2f}S"
                base = {"actionNumber": n, "clock": clock, "period": period, "teamId": team, "teamTricode": T.team_by_id(team)["abbr"], "possession": team, "scoreHome": str(sh), "scoreAway": str(sa), "personId": 1630000 + n % 200, "playerNameI": f"P. Player{n % 9}", "description": ""}
                if r < .62:
                    three = rng.random() < .38; made = rng.random() < (.36 if three else .5); pts = 3 if three else 2
                    x = float(rng.uniform(-220, 220)) if three else float(rng.uniform(-90, 90)); y = float(rng.uniform(60, 250)) if three else float(rng.uniform(0, 120)); dist = round(math.hypot(x, y) / 10, 1)
                    if made:
                        if team == h: sh += pts
                        else: sa += pts
                    acts.append({**base, "actionType": "3pt" if three else "2pt", "isFieldGoal": 1, "shotResult": "Made" if made else "Missed", "xLegacy": int(x), "yLegacy": int(y), "shotDistance": dist,
                                 "scoreHome": str(sh), "scoreAway": str(sa), "description": f"{base['playerNameI']} {dist}' {'3PT' if three else '2PT'} {'Made' if made else 'Missed'}"})
                elif r < .75: acts.append({**base, "actionType": "turnover", "description": f"{base['playerNameI']} Turnover"})
                elif r < .85: acts.append({**base, "actionType": "foul", "description": f"{base['playerNameI']} Foul"})
                else: acts.append({**base, "actionType": "rebound", "description": f"{base['playerNameI']} REBOUND"})
        return _f(acts)

    def boxscore(self, game_id, final=False):
        g = self._game(game_id); rng = np.random.default_rng(int(game_id[-4:] or 1)); out = {"gameStatus": 3 if g["status"] == "final" else 2}
        for side in ("home", "away"):
            t = g[side]; players = []
            for i in range(9):
                pts = int(rng.integers(0, 32)); players.append({"personId": 1630000 + i + (0 if side == "home" else 50), "name": f"Player {side[0].upper()}{i}", "jerseyNum": str(i), "position": "G", "starter": "1" if i < 5 else "0", "oncourt": "0",
                                                              "statistics": {"minutes": f"PT{int(rng.integers(8, 38))}M00.00S", "points": pts, "reboundsTotal": int(rng.integers(0, 12)), "assists": int(rng.integers(0, 10)), "steals": 1, "blocks": 0, "turnovers": 2,
                                                                             "fieldGoalsMade": pts // 3, "fieldGoalsAttempted": pts // 2 + 2, "threePointersMade": 2, "threePointersAttempted": 5, "freeThrowsMade": 2, "freeThrowsAttempted": 3, "plusMinusPoints": int(rng.integers(-12, 14)), "foulsPersonal": 2}})
            out[f"{side}Team"] = {"teamId": t["id"], "teamTricode": t["abbr"], "score": t["score"] or 0, "players": players, "periods": [{"period": i + 1, "score": 25 + i} for i in range(4)],
                                  "statistics": {"fieldGoalsMade": 40, "fieldGoalsAttempted": 88, "threePointersMade": 13, "threePointersAttempted": 35, "freeThrowsMade": 18, "freeThrowsAttempted": 22, "reboundsTotal": 44, "assists": 25, "turnovers": 12,
                                                 "steals": 7, "blocks": 4, "pointsInThePaint": 46, "pointsFastBreak": 12, "pointsSecondChance": 14, "benchPoints": 31, "biggestLead": 11}}
        return _f(out)

    def news(self, limit=20):
        return _f([{"headline": "Fixture headline for UI testing", "description": "", "published": TODAY.isoformat(), "url": "https://example.com", "image": None, "source": "ESPN"}])

    def injuries(self):
        p = self._players[0]; t = T.team_by_id(p["team_id"])
        return _f([{"team": t["abbr"], "player": p["name"], "player_id_espn": "1", "status": "Out", "detail": "Fixture injury"}])
