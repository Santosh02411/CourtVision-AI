"""Player intelligence: league table, percentiles, form/trend analysis, similarity, archetypes, comparison."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.services import teams as T
from app.services.cache import DataUnavailable, Fetched
from app.services.nba_data import NBAData
from app.services.util import num, parse_date, percentile_rank, rnd

logger = logging.getLogger("courtvision.players")

RADAR = [  # key, label, source fn, higher_is_better
    ("scoring", "Scoring", lambda p: p["pts"], True),
    ("playmaking", "Playmaking", lambda p: p["ast"], True),
    ("rebounding", "Rebounding", lambda p: p["reb"], True),
    ("defense", "Defense (STL+BLK)", lambda p: (p["stl"] or 0) + (p["blk"] or 0), True),
    ("efficiency", "Efficiency (TS%)", lambda p: p["ts_pct"], True),
    ("usage", "Usage", lambda p: p["usg_pct"], True),
    ("impact", "Impact (PIE)", lambda p: p["pie"], True),
    ("security", "Ball security", lambda p: p["tov"], False),
]
STRENGTH_METRICS = [("pts", "scoring", True), ("ast", "playmaking", True), ("reb", "rebounding", True),
                    ("stl", "steals", True), ("blk", "rim protection", True), ("ts_pct", "scoring efficiency", True),
                    ("fg3m", "three-point volume", True), ("tov", "ball security", False), ("pie", "overall impact", True)]
SIM_FEATURES = ["pts36", "reb36", "ast36", "stl36", "blk36", "tov36", "fg3m36", "ts_pct", "usg_pct", "ast_pct", "reb_pct"]
ARCHETYPES = [  # label, scoring fn over centroid z-dict
    ("Playmaker", lambda c: c["ast36"] + c["ast_pct"] - 0.3 * c["blk36"]),
    ("Rim-protecting big", lambda c: c["blk36"] + c["reb_pct"] + 0.5 * c["reb36"] - c["fg3m36"]),
    ("Scoring engine", lambda c: c["pts36"] + c["usg_pct"] + 0.3 * c["ts_pct"]),
    ("3&D wing", lambda c: c["fg3m36"] + c["stl36"] - 0.6 * c["usg_pct"] - 0.4 * c["tov36"]),
    ("Two-way forward", lambda c: 0.6 * c["reb36"] + c["stl36"] + 0.5 * c["blk36"] + 0.3 * c["pts36"]),
]


def _pct(v: Any) -> float | None:
    f = num(v)
    return None if f is None else round(f * 100, 1)


class PlayerIntel:
    def __init__(self, data: NBAData) -> None:
        self.data = data
        self._model_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ table
    def table(self, season: str) -> tuple[dict[str, Any], list[Fetched]]:
        base = self.data.player_stats(season, "Base")
        adv = self.data.player_stats(season, "Advanced")
        prov = [base, adv]
        l10 = None
        try:
            l10 = self.data.player_stats(season, "Base", last_n=10); prov.append(l10)
        except DataUnavailable:
            pass
        adv_by = {r["player_id"]: r for r in adv.data}
        l10_by = {r["player_id"]: r for r in (l10.data if l10 else [])}
        rows = []
        for r in base.data:
            pid = r["player_id"]; a = adv_by.get(pid, {}); l = l10_by.get(pid)
            team = T.team_by_id(r.get("team_id"))
            gp, mins = num(r.get("gp"), 0), num(r.get("min"), 0)
            m36 = 36.0 / mins if mins else 0.0
            rows.append({
                "id": pid, "name": r.get("player_name"), "team": team["abbr"] if team else r.get("team_abbreviation"),
                "team_id": r.get("team_id"), "age": rnd(r.get("age"), 0), "gp": gp, "min": rnd(mins),
                "pts": rnd(r.get("pts")), "reb": rnd(r.get("reb")), "ast": rnd(r.get("ast")), "stl": rnd(r.get("stl")),
                "blk": rnd(r.get("blk")), "tov": rnd(r.get("tov")), "fg3m": rnd(r.get("fg3m")),
                "fg_pct": _pct(r.get("fg_pct")), "fg3_pct": _pct(r.get("fg3_pct")), "ft_pct": _pct(r.get("ft_pct")),
                "plus_minus": rnd(r.get("plus_minus")), "ts_pct": _pct(a.get("ts_pct")), "efg_pct": _pct(a.get("efg_pct")),
                "usg_pct": _pct(a.get("usg_pct")), "pie": _pct(a.get("pie")), "net_rating": rnd(a.get("net_rating")),
                "off_rating": rnd(a.get("off_rating")), "def_rating": rnd(a.get("def_rating")),
                "ast_pct": _pct(a.get("ast_pct")), "reb_pct": _pct(a.get("reb_pct")),
                "l10_gp": num(l.get("gp")) if l else None, "l10_pts": rnd(l.get("pts")) if l else None,
                "l10_reb": rnd(l.get("reb")) if l else None, "l10_ast": rnd(l.get("ast")) if l else None,
                "l10_min": rnd(l.get("min")) if l else None,
                "_per36": {k: (num(r.get(k), 0) or 0) * m36 for k in ("pts", "reb", "ast", "stl", "blk", "tov", "fg3m")},
            })
        if not rows:
            raise DataUnavailable("NBA Stats", "player table is empty")
        max_gp = max(r["gp"] for r in rows)
        q_gp = max(3, int(0.25 * max_gp))
        for r in rows:
            r["qualified"] = bool(r["gp"] >= q_gp and (r["min"] or 0) >= 12)
        qual = [r for r in rows if r["qualified"]]
        self._form(rows, qual)
        self._percentiles(rows, qual)
        self.attach_metric_percentiles(rows)
        arche = self._archetypes(qual)
        for r in rows:
            r["archetype"] = arche.get(r["id"])
            r["headshot"] = T.headshot_url(r["id"])
        rows.sort(key=lambda r: -(r["pie"] or -1))
        return {"players": rows, "qualification": {"min_gp": q_gp, "min_mpg": 12, "qualified": len(qual), "total": len(rows)}}, prov

    # ------------------------------------------------------------------ derived
    @staticmethod
    def _form(rows: list[dict], qual: list[dict]) -> None:
        deltas = [r["l10_pts"] - r["pts"] for r in qual if r["l10_pts"] is not None and (r["l10_gp"] or 0) >= 4]
        sd = float(np.std(deltas)) if len(deltas) > 5 else 0.0
        for r in rows:
            if r["l10_pts"] is None or (r["l10_gp"] or 0) < 4 or not sd:
                r["form_delta"], r["form_label"] = None, None
                continue
            d = r["l10_pts"] - r["pts"]
            r["form_delta"] = round(d, 1)
            z = d / sd
            r["form_label"] = "Hot" if z >= 1.0 else "Warm" if z >= 0.4 else "Cold" if z <= -1.0 else "Cool" if z <= -0.4 else "Steady"

    @staticmethod
    def _percentiles(rows: list[dict], qual: list[dict]) -> None:
        pops = {}
        for key, _, fn, hi in RADAR:
            pops[key] = [fn(p) for p in qual if fn(p) is not None]
        for r in rows:
            pct = {}
            for key, _, fn, hi in RADAR:
                v = fn(r)
                if v is None or not pops[key]:
                    pct[key] = None
                    continue
                p = percentile_rank(v, pops[key])
                pct[key] = p if hi else round(100 - p, 1)
            r["percentiles"] = pct

    @staticmethod
    def _vec(r: dict) -> list[float]:
        p36 = r["_per36"]
        return [p36["pts"], p36["reb"], p36["ast"], p36["stl"], p36["blk"], p36["tov"], p36["fg3m"],
                r["ts_pct"] or 0, r["usg_pct"] or 0, r["ast_pct"] or 0, r["reb_pct"] or 0]

    def _zmatrix(self, qual: list[dict]) -> np.ndarray:
        X = np.array([self._vec(r) for r in qual], dtype=float)
        sd = X.std(axis=0); sd[sd == 0] = 1.0
        return (X - X.mean(axis=0)) / sd

    def _archetypes(self, qual: list[dict]) -> dict[int, str]:
        if len(qual) < 40:
            return {}
        from sklearn.cluster import KMeans
        Z = self._zmatrix(qual)
        k = len(ARCHETYPES) + 1
        km = KMeans(n_clusters=k, n_init=10, random_state=7).fit(Z)
        cents = [dict(zip(SIM_FEATURES, c)) for c in km.cluster_centers_]
        labels, taken = {}, set()
        for name, fn in ARCHETYPES:
            best = max((i for i in range(k) if i not in taken), key=lambda i: fn(cents[i]))
            labels[best] = name; taken.add(best)
        return {r["id"]: labels.get(int(c), "Role player") for r, c in zip(qual, km.labels_)}

    def similar(self, rows: list[dict], player_id: int, n: int = 6) -> list[dict]:
        qual = [r for r in rows if r["qualified"]]
        idx = next((i for i, r in enumerate(qual) if r["id"] == player_id), None)
        if idx is None:
            return []
        Z = self._zmatrix(qual)
        norms = np.linalg.norm(Z, axis=1); norms[norms == 0] = 1.0
        sims = (Z @ Z[idx]) / (norms * norms[idx])
        order = [i for i in np.argsort(-sims) if i != idx][:n]
        return [{"id": qual[i]["id"], "name": qual[i]["name"], "team": qual[i]["team"],
                 "similarity": round(float(sims[i]) * 100, 1), "pts": qual[i]["pts"], "reb": qual[i]["reb"],
                 "ast": qual[i]["ast"], "headshot": qual[i]["headshot"]} for i in order]

    # ------------------------------------------------------------------ game-log form analysis
    @staticmethod
    def form_analysis(log_rows: list[dict]) -> dict[str, Any]:
        games = []
        for r in log_rows:
            d = parse_date(r.get("game_date"))
            if not d:
                continue
            fga, fta, pts = num(r.get("fga"), 0) or 0, num(r.get("fta"), 0) or 0, num(r.get("pts"), 0) or 0
            games.append({
                "game_id": r.get("game_id"), "date": d.isoformat(), "matchup": r.get("matchup"), "wl": r.get("wl"),
                "min": num(r.get("min")), "pts": pts, "reb": num(r.get("reb")), "ast": num(r.get("ast")),
                "stl": num(r.get("stl")), "blk": num(r.get("blk")), "tov": num(r.get("tov")),
                "fg_pct": _pct(r.get("fg_pct")), "fg3m": num(r.get("fg3m")), "plus_minus": num(r.get("plus_minus")),
                "ts_pct": round(100 * pts / (2 * (fga + 0.44 * fta)), 1) if (fga + 0.44 * fta) > 0 else None,
            })
        games.sort(key=lambda g: g["date"])
        if not games:
            return {"games": [], "summary": None}
        pts = np.array([g["pts"] for g in games], dtype=float)
        roll, ew, e = [], [], pts[0]
        for i, v in enumerate(pts):
            roll.append(round(float(pts[max(0, i - 4): i + 1].mean()), 2))
            e = 0.3 * v + 0.7 * e if i else v
            ew.append(round(float(e), 2))
        for g, r5, ev in zip(games, roll, ew):
            g["rolling5"], g["ewma"] = r5, ev
        season_avg, season_sd = float(pts.mean()), float(pts.std(ddof=1)) if len(pts) > 1 else 0.0
        last5 = pts[-5:]
        z = (last5.mean() - season_avg) / (season_sd / np.sqrt(len(last5))) if season_sd and len(pts) >= 8 else None
        recent = pts[-10:]
        slope = float(np.polyfit(np.arange(len(recent)), recent, 1)[0]) if len(recent) >= 5 else None
        label = None if z is None else "Hot" if z >= 1.0 else "Warming" if z >= 0.4 else "Cold" if z <= -1.0 else "Cooling" if z <= -0.4 else "Steady"
        best, worst = max(games, key=lambda g: g["pts"]), min(games, key=lambda g: g["pts"])
        return {"games": games, "summary": {
            "games": len(games), "season_avg_pts": round(season_avg, 1), "last5_avg_pts": round(float(last5.mean()), 1),
            "last10_avg_pts": round(float(recent.mean()), 1), "trend_slope_pts_per_game": None if slope is None else round(slope, 2),
            "form_z": None if z is None else round(float(z), 2), "form_label": label,
            "consistency": round(max(0.0, 1 - season_sd / season_avg), 2) if season_avg else None,
            "best_game": {"date": best["date"], "pts": best["pts"], "matchup": best["matchup"]},
            "worst_game": {"date": worst["date"], "pts": worst["pts"], "matchup": worst["matchup"]},
            "method": "Form z-score = (last-5 mean − season mean) / (season SD / √5); trend = OLS slope of last 10 games.",
        }}

    # ------------------------------------------------------------------ comparison
    @staticmethod
    def strengths(p: dict) -> dict[str, list[str]]:
        scored = []
        pops = p.get("_pops")
        for key, label, hi in STRENGTH_METRICS:
            pctl = (p.get("metric_pct") or {}).get(key)
            if pctl is not None:
                scored.append((pctl if hi else 100 - pctl, label))
        scored.sort(reverse=True)
        return {"strengths": [f"{l} ({int(v)}th pct)" for v, l in scored[:3] if v >= 70],
                "weaknesses": [f"{l} ({int(v)}th pct)" for v, l in reversed(scored[-3:]) if v <= 35]}

    def attach_metric_percentiles(self, rows: list[dict]) -> None:
        qual = [r for r in rows if r["qualified"]]
        pops = {k: [r[k] for r in qual if r[k] is not None] for k, _, _ in STRENGTH_METRICS}
        for r in rows:
            r["metric_pct"] = {k: (percentile_rank(r[k], pops[k]) if r[k] is not None and pops[k] else None)
                               for k, _, _ in STRENGTH_METRICS}
