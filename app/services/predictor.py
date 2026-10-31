"""Pre-game prediction with exact additive attribution and an explicit confidence model."""
from __future__ import annotations

import json
import logging
import unicodedata
from datetime import date
from typing import Any

from app.config import Config
from app.services import teams as T
from app.services.team_intel import FEATURE_LABELS, FEATURES, LeagueState
from app.services.util import clock_seconds, num, parse_date, sigmoid

logger = logging.getLogger("courtvision.predictor")

# Hand-set priors used ONLY until scripts/train_pregame.py writes real fitted weights (flagged in every response).
DEFAULT_MODEL = {
    "name": "Pre-game win model", "type": "Logistic regression on Elo, point differential, form, rest",
    "trained_on": "prior (hand-set, not fitted)", "features": FEATURES, "intercept": 0.25,
    "coefficients": {"elo_diff": 0.35, "margin_diff": 0.06, "form_diff": 0.025, "rest_diff": 0.04,
                     "b2b_home": -0.12, "b2b_away": 0.12},
    "feature_means": {f: 0.0 for f in FEATURES}, "evaluation": None,
}
LOGIT_PER_POINT = 0.145        # ≈ logistic slope of NBA margin (σ≈12 pts)
INJURY_POINTS_CAP, INJURY_PIE_FLOOR, INJURY_SCALE = 7.0, 8.0, 0.4
STATUS_WEIGHT = {"out": 1.0, "doubtful": 0.75, "questionable": 0.25, "day-to-day": 0.2}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def name_key(name: Any) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    parts = [p for p in s.replace(".", "").replace("'", "").replace("-", " ").split() if p not in _SUFFIXES]
    return " ".join(parts)


class Predictor:
    def __init__(self) -> None:
        self.model = self._load()

    @staticmethod
    def _load() -> dict:
        path = Config.DATA_DIR / "models" / "pregame_model.json"
        try:
            m = json.loads(path.read_text())
            if set(FEATURES) <= set(m.get("coefficients", {})):
                return m
        except Exception:
            pass
        return DEFAULT_MODEL

    @property
    def is_fitted(self) -> bool:
        return self.model.get("trained_on") == "real"

    # -- availability ---------------------------------------------------------------------
    @staticmethod
    def availability(team_abbr: str, injuries: list[dict] | None, players: list[dict] | None) -> dict:
        by_name = {name_key(p["name"]): p for p in (players or []) if p.get("team") == team_abbr}
        out, pts = [], 0.0
        for inj in injuries or []:
            if inj.get("team") != team_abbr:
                continue
            w = STATUS_WEIGHT.get((inj.get("status") or "").lower())
            if not w:
                continue
            p = by_name.get(name_key(inj.get("player")))
            impact = 0.0
            if p and p.get("pie") is not None and p.get("min"):
                impact = max(0.0, p["pie"] - INJURY_PIE_FLOOR) * (p["min"] / 36.0) * INJURY_SCALE
            pts += impact * w
            out.append({"player": inj.get("player"), "status": inj["status"], "detail": inj.get("detail"),
                        "impact_pts": round(impact * w, 2), "matched": bool(p), "player_id": (p or {}).get("id")})
        out.sort(key=lambda r: -r["impact_pts"])
        return {"players": out, "points_lost": round(min(pts, INJURY_POINTS_CAP), 2)}

    # -- core -------------------------------------------------------------------------------
    def predict(self, state: LeagueState, home: dict, away: dict, game_date: date,
                home_av: dict | None = None, away_av: dict | None = None, form_note: bool = True) -> dict:
        feats = state.features(home["id"], away["id"], game_date)
        m = self.model
        coefs, means = m["coefficients"], m["feature_means"]
        baseline_logit = m["intercept"] + sum(coefs[f] * means[f] for f in FEATURES)
        contrib = {f: coefs[f] * (feats[f] - means[f]) for f in FEATURES}

        inj_pts = (away_av or {}).get("points_lost", 0.0) - (home_av or {}).get("points_lost", 0.0)
        inj_contrib = inj_pts * LOGIT_PER_POINT
        total_logit = baseline_logit + sum(contrib.values()) + inj_contrib
        p_home = sigmoid(total_logit)
        p_base = sigmoid(baseline_logit)

        # Allocate the probability swing proportionally to each factor's exact log-odds contribution.
        all_c = {**contrib, "availability": inj_contrib}
        denom = sum(abs(v) for v in all_c.values()) or 1.0
        swing = p_home - p_base
        signed_sum = sum(all_c.values())

        def pp(c: float) -> float:
            return round(100 * (swing * (c / signed_sum) if abs(signed_sum) > 1e-6 else swing * abs(c) / denom * (1 if c >= 0 else -1)), 2)

        raw = {**feats, "availability": inj_pts}
        labels = {**FEATURE_LABELS, "availability": "Injury availability (reported)"}
        factors = [{
            "key": k, "label": labels[k], "raw_value": round(raw.get(k, 0.0), 3),
            "contribution_logit": round(c, 4), "contribution_pp": pp(c),
            "favors": home["abbr"] if c > 0.0005 else away["abbr"] if c < -0.0005 else "neutral",
        } for k, c in all_c.items()]
        factors.sort(key=lambda f: -abs(f["contribution_logit"]))

        played = min(len(state.margins[home["id"]]), len(state.margins[away["id"]]))
        conf = self._confidence(p_home, played, home_av, away_av)
        pick = home if p_home >= 0.5 else away
        return {
            "home": home, "away": away, "date": game_date.isoformat(),
            "probabilities": {"home": round(p_home, 4), "away": round(1 - p_home, 4)},
            "pick": pick["abbr"], "pick_probability": round(max(p_home, 1 - p_home), 4),
            "implied_spread": round(total_logit / LOGIT_PER_POINT, 1),
            "baseline_probability": round(p_base, 4), "factors": factors, "confidence": conf,
            "context": {
                "elo": {"home": round(state.elo[home["id"]], 1), "away": round(state.elo[away["id"]], 1)},
                "season_margin": {"home": round(state.team_margin(home["id"]), 2), "away": round(state.team_margin(away["id"]), 2)},
                "last10_margin": {"home": round(state.team_form(home["id"]), 2), "away": round(state.team_form(away["id"]), 2)},
                "rest_days": {"home": feats["_rest_home"], "away": feats["_rest_away"]},
                "games_played": {"home": len(state.margins[home["id"]]), "away": len(state.margins[away["id"]])},
            },
            "availability": {"home": home_av, "away": away_av, "net_points_for_home": round(inj_pts, 2)},
            "model": self.model_card(),
        }

    def _confidence(self, p_home: float, played: int, home_av: dict | None, away_av: dict | None) -> dict:
        sep = abs(p_home - 0.5) * 2
        sample = min(1.0, played / 15.0)
        reasons = []
        score = 0.15 + 0.65 * min(1.0, sep / 0.6) + 0.20 * sample
        if sample < 0.5:
            score -= 0.15
            reasons.append(f"Only {played} game{'' if played == 1 else 's'} played this season - ratings lean on last season's Elo carry-over.")
        if not self.is_fitted:
            score -= 0.15
            reasons.append("Model weights are hand-set priors; run scripts/train_pregame.py to fit on real results.")
        if sep > 0.35:
            reasons.append("Large rating gap between the teams.")
        elif sep < 0.12:
            reasons.append("Teams are closely matched - near coin-flip.")
        if any((a or {}).get("points_lost", 0) >= 2.5 for a in (home_av, away_av)):
            reasons.append("A rotation player is reported unavailable; injury impact is an estimate.")
        score = max(0.05, min(0.95, score))
        label = "High" if score >= 0.68 else "Medium" if score >= 0.45 else "Low"
        return {"label": label, "score": round(score, 2), "reasons": reasons}

    def model_card(self) -> dict:
        m = self.model
        return {"name": m["name"], "type": m["type"], "trained_on": m["trained_on"], "fitted": self.is_fitted,
                "trained_at": m.get("trained_at"), "seasons": m.get("seasons"), "evaluation": m.get("evaluation"),
                "evaluation_note": m.get("evaluation_note"),
                "warning": None if self.is_fitted else "Uncalibrated prior weights - not validated on real games."}

    # -- head to head ------------------------------------------------------------------------
    @staticmethod
    def head_to_head(state: LeagueState, a: dict, b: dict, limit: int = 8) -> dict:
        meetings = []
        for season, games in state.games_by_season:
            for g in games:
                if {g["home_id"], g["away_id"]} == {a["id"], b["id"]}:
                    meetings.append({"season": season, **g})
        meetings.sort(key=lambda g: g["date"], reverse=True)
        a_wins = sum(1 for g in meetings if (g["home_pts"] > g["away_pts"]) == (g["home_id"] == a["id"]))
        margin = [(g["home_pts"] - g["away_pts"]) * (1 if g["home_id"] == a["id"] else -1) for g in meetings]
        return {
            "games": len(meetings), "a": a["abbr"], "b": b["abbr"], "a_wins": a_wins, "b_wins": len(meetings) - a_wins,
            "avg_margin_a": round(sum(margin) / len(margin), 1) if margin else None,
            "recent": [{"date": g["date"], "season": g["season"], "home": T.team_by_id(g["home_id"])["abbr"],
                        "away": T.team_by_id(g["away_id"])["abbr"], "home_pts": int(g["home_pts"]),
                        "away_pts": int(g["away_pts"])} for g in meetings[:limit]],
        }
