"""Live scoreboard, box score parsing, and the Game Impact Analyzer (win-probability timeline, swings, runs)."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.models.win_probability import WinProbabilityModel
from app.services import teams as T
from app.services.cache import DataUnavailable, Fetched
from app.services.nba_data import NBAData
from app.services.shot_analysis import ShotScorer
from app.services.util import clock_seconds, elapsed_seconds, fmt_clock, num, time_remaining

logger = logging.getLogger("courtvision.live")
NEUTRAL_Q = 0.45
SWING_THRESHOLD = 0.04   # 4 percentage points counts as a swing play
_SHOT_TYPES = {"2pt", "3pt"}
_END_OF_POSSESSION = {"rebound", "turnover"}


def _int(v: Any, d: int = 0) -> int:
    f = num(v)
    return d if f is None else int(f)


def _opt(d: dict, key: str) -> int | None:
    """None (not 0) when the source layout doesn't provide the stat."""
    return _int(d[key]) if d.get(key) is not None else None


def live_wp_from_state(model: WinProbabilityModel, home_score: int, away_score: int, period: int, clock: str | None) -> float:
    """Cheap state-only live win probability (score, clock) - used for scoreboard cards."""
    return model.predict_home_win_probability({
        "score_diff": home_score - away_score, "time_remaining": time_remaining(period, clock),
        "home_possession": 0.5, "home_fouls": 3, "away_fouls": 3, "shot_quality": NEUTRAL_Q})


# ------------------------------------------------------------------ box score
def parse_boxscore(game: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for side in ("homeTeam", "awayTeam"):
        t = game.get(side) or {}
        players = []
        for p in t.get("players", []):
            s = p.get("statistics") or {}
            mins = clock_seconds(s.get("minutes")) / 60.0
            if not mins and not _int(s.get("points")):
                continue
            players.append({
                "id": p.get("personId"), "name": p.get("name") or p.get("nameI"), "jersey": p.get("jerseyNum"),
                "position": p.get("position"), "starter": p.get("starter") == "1", "oncourt": p.get("oncourt") == "1",
                "min": round(mins, 1), "pts": _int(s.get("points")), "reb": _int(s.get("reboundsTotal")),
                "ast": _int(s.get("assists")), "stl": _int(s.get("steals")), "blk": _int(s.get("blocks")),
                "tov": _int(s.get("turnovers")), "fgm": _int(s.get("fieldGoalsMade")), "fga": _int(s.get("fieldGoalsAttempted")),
                "fg3m": _int(s.get("threePointersMade")), "fg3a": _int(s.get("threePointersAttempted")),
                "ftm": _int(s.get("freeThrowsMade")), "fta": _int(s.get("freeThrowsAttempted")),
                "plus_minus": num(s.get("plusMinusPoints"), 0), "pf": _int(s.get("foulsPersonal")),
                "headshot": T.headshot_url(p["personId"]) if p.get("personId") else None,
            })
        players.sort(key=lambda r: (-r["pts"], -r["min"]))
        ts = t.get("statistics") or {}
        pct = lambda a, b: round(100 * a / b, 1) if b else None
        fgm, fga = _int(ts.get("fieldGoalsMade")), _int(ts.get("fieldGoalsAttempted"))
        tm, ta = _int(ts.get("threePointersMade")), _int(ts.get("threePointersAttempted"))
        fm, fa = _int(ts.get("freeThrowsMade")), _int(ts.get("freeThrowsAttempted"))
        out["home" if side == "homeTeam" else "away"] = {
            "id": t.get("teamId"), "abbr": t.get("teamTricode"), "score": _int(t.get("score")), "players": players,
            "periods": [_int(p.get("score")) for p in t.get("periods", [])],
            "stats": {"fg_pct": pct(fgm, fga), "fg3_pct": pct(tm, ta), "ft_pct": pct(fm, fa),
                      "reb": _int(ts.get("reboundsTotal")), "ast": _int(ts.get("assists")), "tov": _int(ts.get("turnovers")),
                      "stl": _int(ts.get("steals")), "blk": _int(ts.get("blocks")),
                      "paint": _opt(ts, "pointsInThePaint"), "fast_break": _opt(ts, "pointsFastBreak"),
                      "second_chance": _opt(ts, "pointsSecondChance"), "bench": _opt(ts, "benchPoints"),
                      "biggest_lead": _opt(ts, "biggestLead")},
        }
    return out


# ------------------------------------------------------------------ play-by-play -> states
def build_states(actions: list[dict], home_id: int, away_id: int, scorer: ShotScorer | None) -> tuple[list[dict], list[dict]]:
    """Return (state rows, shot list). Each row carries the model inputs; win probability is added by the caller."""
    rows, shots = [], []
    sh = sa = 0
    fouls = {home_id: 0, away_id: 0}
    cur_period = 0
    quality = NEUTRAL_Q
    poss_home = 0.5
    shot_rows: list[tuple[int, dict]] = []
    for a in actions:
        atype = (a.get("actionType") or "").lower()
        period = _int(a.get("period"), 1)
        if period != cur_period:
            fouls = {home_id: 0, away_id: 0}; cur_period = period
        if a.get("scoreHome") not in (None, "") and a.get("scoreAway") not in (None, ""):
            sh, sa = _int(a["scoreHome"], sh), _int(a["scoreAway"], sa)
        tid = a.get("teamId")
        if atype == "foul" and tid in fouls:
            fouls[tid] += 1
        if a.get("possession") in (home_id, away_id):
            poss_home = 1.0 if a["possession"] == home_id else 0.0
        if atype in _SHOT_TYPES and a.get("xLegacy") is not None and tid in (home_id, away_id):
            shot_rows.append((len(rows), a))
        row = {
            "n": a.get("actionNumber"), "period": period, "clock": a.get("clock"), "elapsed": elapsed_seconds(period, a.get("clock")),
            "tr": time_remaining(period, a.get("clock")), "sh": sh, "sa": sa, "poss_home": poss_home,
            "hf": fouls[home_id], "af": fouls[away_id], "type": atype, "team_id": tid, "desc": a.get("description") or "",
            "player": a.get("playerNameI") or a.get("playerName"), "result": a.get("shotResult"),
            "quality": NEUTRAL_Q, "_a": a,
        }
        rows.append(row)

    # shot quality for every located field-goal attempt (one batch through the model)
    if scorer is not None and shot_rows:
        df = pd.DataFrame([{
            "loc_x": num(a.get("xLegacy"), 0), "loc_y": num(a.get("yLegacy"), 0), "distance": num(a.get("shotDistance"), 0),
            "angle": float(np.degrees(np.arctan2(num(a.get("xLegacy"), 0) / 10.0, max(num(a.get("yLegacy"), 0) / 10.0, 0.1)))),
            "is_three": 1 if (a.get("actionType") or "").lower() == "3pt" else 0, "period": _int(a.get("period"), 1),
            "secs_left": clock_seconds(a.get("clock")),
        } for _, a in shot_rows])
        q = scorer.score(df)
        for (idx, a), qv in zip(shot_rows, q):
            rows[idx]["_shot_q"] = float(qv)
            shots.append({"x": int(num(a.get("xLegacy"), 0)), "y": int(num(a.get("yLegacy"), 0)),
                          "made": 1 if (a.get("shotResult") or "").lower() == "made" else 0,
                          "team_id": a.get("teamId"), "team": a.get("teamTricode"), "player": a.get("playerNameI"),
                          "player_id": a.get("personId"), "quality": round(float(qv), 3), "period": _int(a.get("period"), 1),
                          "clock": fmt_clock(a.get("clock")), "pts": 3 if (a.get("actionType") or "").lower() == "3pt" else 2,
                          "dist": num(a.get("shotDistance")), "desc": a.get("description") or ""})

    # home-oriented, possession-scoped shot-quality feature
    cur_q = NEUTRAL_Q
    for r in rows:
        if "_shot_q" in r:
            sign = 1.0 if r["team_id"] == home_id else -1.0
            cur_q = float(np.clip(NEUTRAL_Q + sign * (r["_shot_q"] - NEUTRAL_Q), 0.0, 1.0))
        r["quality"] = cur_q
        if r["type"] in _END_OF_POSSESSION or (r["type"] in _SHOT_TYPES and (r.get("result") or "").lower() == "made"):
            cur_q = NEUTRAL_Q
    return rows, shots


def attach_win_probability(rows: list[dict], model: WinProbabilityModel) -> None:
    feats = [{"score_diff": r["sh"] - r["sa"], "time_remaining": r["tr"], "home_possession": r["poss_home"],
              "home_fouls": r["hf"], "away_fouls": r["af"], "shot_quality": r["quality"]} for r in rows]
    for r, p in zip(rows, model.predict_batch(feats)):
        r["wp"] = p


# ------------------------------------------------------------------ impact analysis
def analyze_impact(rows: list[dict], home: dict, away: dict, final: bool) -> dict[str, Any]:
    if not rows:
        return {"timeline": [], "swings": [], "runs": [], "turning_point": None, "summary": {}}
    prev = 0.5
    timeline = []
    for r in rows:
        r["delta"] = r["wp"] - prev
        prev = r["wp"]
        timeline.append({"t": round(r["elapsed"]), "wp": r["wp"], "h": r["sh"], "a": r["sa"], "p": r["period"]})

    def team_abbr(tid: Any) -> str | None:
        return home["abbr"] if tid == home["id"] else away["abbr"] if tid == away["id"] else None

    cand = [r for r in rows if r["type"] in {"2pt", "3pt", "freethrow", "turnover", "steal", "block", "foul"} and r["desc"]]
    # a made basket / turnover is credited with the swing across the following possession boundary
    swings = sorted(cand, key=lambda r: -abs(r["delta"]))[:8]
    swings = [r for r in swings if abs(r["delta"]) >= 0.01]
    swing_out = []
    for r in sorted(swings, key=lambda r: r["elapsed"]):
        favors = home["abbr"] if r["delta"] > 0 else away["abbr"]
        swing_out.append({
            "n": r["n"], "period": r["period"], "clock": fmt_clock(r["clock"]), "t": round(r["elapsed"]), "desc": r["desc"],
            "team": team_abbr(r["team_id"]), "player": r["player"], "wp_before": round(r["wp"] - r["delta"], 3),
            "wp_after": r["wp"], "delta_pp": round(100 * r["delta"], 1), "favors": favors,
            "score": f"{r['sa']}-{r['sh']}", "big": abs(r["delta"]) >= SWING_THRESHOLD,
        })

    # scoring runs
    runs, run_team, run_pts, run_start = [], None, 0, 0
    last_h = last_a = 0
    start_wp = 0.5
    for i, r in enumerate(rows):
        dh, da = r["sh"] - last_h, r["sa"] - last_a
        if dh > 0 or da > 0:
            scorer = home["id"] if dh > 0 else away["id"]
            pts = dh if dh > 0 else da
            if scorer == run_team:
                run_pts += pts
            else:
                if run_team and run_pts >= 7:
                    runs.append((run_team, run_pts, run_start, i - 1, start_wp))
                run_team, run_pts, run_start = scorer, pts, i
                start_wp = rows[i - 1]["wp"] if i else 0.5
            run_end = i
        last_h, last_a = r["sh"], r["sa"]
        if run_team and run_pts >= 7 and i == len(rows) - 1:
            runs.append((run_team, run_pts, run_start, i, start_wp))
    run_out = []
    for tid, pts, i0, i1, wp0 in sorted(runs, key=lambda x: -x[1])[:5]:
        wp1 = rows[i1]["wp"]
        run_out.append({"team": team_abbr(tid), "points": pts, "period_start": rows[i0]["period"], "clock_start": fmt_clock(rows[i0]["clock"]),
                        "period_end": rows[i1]["period"], "clock_end": fmt_clock(rows[i1]["clock"]),
                        "t_start": round(rows[i0]["elapsed"]), "t_end": round(rows[i1]["elapsed"]),
                        "wp_swing_pp": round(100 * (wp1 - wp0) * (1 if tid == home["id"] else -1), 1)})

    # turning point: strongest 5-minute window of win-probability movement
    el = np.array([r["elapsed"] for r in rows]); wp = np.array([r["wp"] for r in rows])
    best, j = (0.0, 0, 0), 0
    for i in range(len(rows)):
        while el[i] - el[j] > 300:
            j += 1
        move = wp[i] - wp[j]
        if abs(move) > abs(best[0]):
            best = (float(move), j, i)
    turning = None
    if abs(best[0]) >= 0.05:
        a0, a1 = rows[best[1]], rows[best[2]]
        turning = {"favors": home["abbr"] if best[0] > 0 else away["abbr"], "swing_pp": round(100 * abs(best[0]), 1),
                   "start": {"period": a0["period"], "clock": fmt_clock(a0["clock"]), "score": f"{a0['sa']}-{a0['sh']}", "t": round(a0["elapsed"])},
                   "end": {"period": a1["period"], "clock": fmt_clock(a1["clock"]), "score": f"{a1['sa']}-{a1['sh']}", "t": round(a1["elapsed"])}}

    # lead changes & clutch leverage
    sign = np.sign([r["sh"] - r["sa"] for r in rows]); lead_changes = 0; last = 0
    for s in sign:
        if s != 0:
            if last != 0 and s != last:
                lead_changes += 1
            last = s
    clutch = [abs(r["delta"]) for r in rows if r["period"] >= 4 and r["tr"] <= 300]
    other = [abs(r["delta"]) for r in rows if not (r["period"] >= 4 and r["tr"] <= 300)]
    diffs = [r["sh"] - r["sa"] for r in rows]
    summary = {
        "lead_changes": lead_changes, "largest_home_lead": max(0, max(diffs)), "largest_away_lead": max(0, -min(diffs)),
        "min_home_win_prob": round(float(wp.min()), 3), "max_home_win_prob": round(float(wp.max()), 3),
        "clutch_leverage": round(100 * float(np.mean(clutch)), 2) if clutch else None,
        "avg_leverage": round(100 * float(np.mean(other)), 2) if other else None,
        "final_home_win_prob": rows[-1]["wp"],
    }
    if final:
        home_won = rows[-1]["sh"] > rows[-1]["sa"]
        w_min = summary["min_home_win_prob"] if home_won else 1 - summary["max_home_win_prob"]
        summary["winner_lowest_win_prob"] = round(float(w_min), 3)
        summary["winner"] = home["abbr"] if home_won else away["abbr"]
    return {"timeline": timeline, "swings": swing_out, "runs": run_out, "turning_point": turning, "summary": summary}


# ------------------------------------------------------------------ service
class LiveService:
    def __init__(self, data: NBAData, win_model: WinProbabilityModel, scorer: ShotScorer) -> None:
        self.data, self.win, self.scorer = data, win_model, scorer

    def games_for_date(self, d: date) -> tuple[list[dict], list[Fetched], list[str]]:
        games, prov, notes = [], [], []
        sched = None
        try:
            sched = self.data.schedule(); prov.append(sched)
            games = [g for g in sched.data if g["date"] == d.isoformat()]
        except DataUnavailable as exc:
            notes.append(f"Season schedule unavailable ({exc.reason or 'upstream error'}).")
        try:
            sb = self.data.scoreboard_today(); prov.append(sb)
            sb_date = str(sb.data.get("date") or "")[:10]
            if sb_date == d.isoformat() or (not sb_date and d == date.today()):
                live_by_id = {g["game_id"]: g for g in sb.data["games"]}
                if games:
                    games = [{**g, **{k: v for k, v in live_by_id.get(g["game_id"], {}).items() if v is not None}} for g in games]
                else:
                    games = sb.data["games"]
        except DataUnavailable as exc:
            if d == date.today():
                notes.append(f"Live scoreboard unavailable ({exc.reason or 'upstream error'}) - scores may be delayed.")
        if not games and not prov:
            raise DataUnavailable("NBA schedule & scoreboard", "no source reachable")
        games.sort(key=lambda g: (g["start_utc"] or "", g["game_id"]))
        for g in games:
            if g["status"] in ("live", "final") and g["home"]["score"] is not None:
                g["live_wp"] = live_wp_from_state(self.win, int(g["home"]["score"]), int(g["away"]["score"]),
                                                  _int(g.get("period"), 1), g.get("clock")) if g["status"] == "live" else None
        return games, prov, notes

    def find_game(self, game_id: str) -> dict | None:
        try:
            for g in self.data.schedule().data:
                if g["game_id"] == game_id:
                    base = g
                    break
            else:
                base = None
        except DataUnavailable:
            base = None
        try:
            for g in self.data.scoreboard_today().data["games"]:
                if g["game_id"] == game_id:
                    return {**(base or {}), **g}
        except DataUnavailable:
            pass
        return base

    def game_detail(self, game_id: str) -> tuple[dict[str, Any], list[Fetched], list[str]]:
        meta = self.find_game(game_id)
        notes: list[str] = []
        final = bool(meta and meta["status"] == "final")
        prov: list[Fetched] = []
        box = self.data.boxscore(game_id, final=final); prov.append(box)
        bx = parse_boxscore(box.data)
        home_id = (meta or {}).get("home", {}).get("id") or bx.get("home", {}).get("id")
        away_id = (meta or {}).get("away", {}).get("id") or bx.get("away", {}).get("id")
        if not home_id or not away_id:
            raise DataUnavailable("NBA CDN", "game teams could not be determined")
        home, away = T.team_by_id(home_id), T.team_by_id(away_id)
        status = (meta or {}).get("status") or ("final" if box.data.get("gameStatus") == 3 else "live" if box.data.get("gameStatus") == 2 else "scheduled")
        if status == "scheduled":
            return {"game": meta, "home": home, "away": away, "status": status, "boxscore": None, "impact": None, "shots": []}, prov, \
                ["Game has not started - see the prediction for pre-game odds."]
        try:
            pbp = self.data.playbyplay(game_id, final=final); prov.append(pbp)
            rows, shots = build_states(pbp.data, home_id, away_id, self.scorer)
            attach_win_probability(rows, self.win)
            impact = analyze_impact(rows, home, away, final)
            if final and rows:  # settle the last point on the actual result, not a model guess
                pass
        except DataUnavailable as exc:
            rows, shots, impact = [], [], None
            notes.append(f"Play-by-play unavailable ({exc.reason or 'upstream error'}) - win-probability analysis skipped.")
        return {
            "game": meta, "home": home, "away": away, "status": status, "boxscore": bx, "impact": impact, "shots": shots,
            "win_model": self.win.metadata(), "shot_model": self.scorer.label,
            "box_status_text": (meta or {}).get("status_text"),
        }, prov, notes
