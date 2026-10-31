"""Shot analysis: filters, zone efficiency vs league, spatial bins, and model-based expected FG%.

Expected FG% comes from the real-data shot model when one has been trained (scripts/train_real_shot_model.py),
otherwise from the SYNTHETIC-trained XGBoost model with an optional isotonic recalibration fitted on real shots.
Public shot charts carry no defender/shot-clock data, so those synthetic-model inputs are held at neutral values.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from math import atan2, degrees
from typing import Any

import numpy as np
import pandas as pd

from app.config import Config
from app.models.shot_quality import (NEUTRAL_DEFENDER_DISTANCE, NEUTRAL_SHOT_CLOCK, RealShotModel, ShotContext,
                                     ShotQualityModel)
from app.services.util import num

logger = logging.getLogger("courtvision.shots")

ZONE_ORDER = ["Restricted Area", "In The Paint (Non-RA)", "Mid-Range", "Left Corner 3", "Right Corner 3",
              "Above the Break 3", "Backcourt"]
DIST_BUCKETS = [(0, 3, "0-3 ft"), (4, 9, "4-9 ft"), (10, 15, "10-15 ft"), (16, 21, "16-21 ft"), (22, 23, "22-23 ft"), (24, 99, "24+ ft")]


def shot_frame(rows: list[dict]) -> pd.DataFrame:
    recs = []
    for r in rows:
        x, y, dist = num(r.get("loc_x")), num(r.get("loc_y")), num(r.get("shot_distance"))
        if x is None or y is None or dist is None:
            continue
        secs = (num(r.get("minutes_remaining"), 0) or 0) * 60 + (num(r.get("seconds_remaining"), 0) or 0)
        recs.append({
            "loc_x": x, "loc_y": y, "distance": dist, "angle": degrees(atan2(x / 10.0, max(y / 10.0, 0.1))),
            "is_three": 1 if "3PT" in str(r.get("shot_type")) else 0, "period": int(num(r.get("period"), 1) or 1),
            "secs_left": secs, "made": int(num(r.get("shot_made_flag"), 0) or 0), "game_id": r.get("game_id"),
            "game_date": str(r.get("game_date") or ""), "zone": r.get("shot_zone_basic"), "area": r.get("shot_zone_area"),
            "range": r.get("shot_zone_range"), "action": r.get("action_type"),
        })
    return pd.DataFrame(recs)


class ShotScorer:
    def __init__(self, synthetic: ShotQualityModel, real: RealShotModel) -> None:
        self.synthetic, self.real = synthetic, real
        self.calibrator = None
        path = Config.DATA_DIR / "real" / "shot_calibrator.joblib"
        if path.exists():
            try:
                import joblib
                self.calibrator = joblib.load(path)
            except Exception:
                self.calibrator = None

    @property
    def label(self) -> dict[str, Any]:
        if self.real.available:
            return {"model": "xFG (XGBoost, trained on real shots)", "trained_on": "real", "real_metrics": self.real.metrics()}
        return {"model": "Shot quality (XGBoost, trained on synthetic shots)" + (" + isotonic recalibration on real shots" if self.calibrator else ""),
                "trained_on": "synthetic", "recalibrated_on_real": bool(self.calibrator),
                "caveat": "Defender distance and shot clock are unavailable in public data and are held at neutral values."}

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        if frame.empty:
            return np.array([])
        if self.real.available:
            return self.real.predict_frame(frame)
        f = frame.copy()
        f["angle"] = f["angle"].clip(-55, 55)
        f["defender_distance"], f["shot_clock"] = NEUTRAL_DEFENDER_DISTANCE, NEUTRAL_SHOT_CLOCK
        f["game_situation"] = (f["period"] - 1).clip(0, 2)
        p = self.synthetic.predict_frame(f)
        return np.clip(self.calibrator.predict(p), 0.01, 0.99) if self.calibrator else p

    def explain_shot(self, row: dict) -> dict:
        if self.real.available:
            return self.real.explain(row)
        return self.synthetic.explain(ShotContext(row["distance"], max(-55, min(55, row["angle"])), NEUTRAL_DEFENDER_DISTANCE,
                                                  NEUTRAL_SHOT_CLOCK, int(max(0, min(2, row["period"] - 1)))))


def apply_filters(df: pd.DataFrame, *, periods: list[int] | None, shot_type: str | None, result: str | None,
                  dmin: float | None, dmax: float | None, zone: str | None, last_n: int | None) -> pd.DataFrame:
    if df.empty:
        return df
    if last_n:
        games = (df[["game_id", "game_date"]].drop_duplicates().sort_values("game_date", ascending=False).head(last_n)["game_id"])
        df = df[df["game_id"].isin(games)]
    if periods:
        df = df[df["period"].isin(periods)]
    if shot_type in ("2", "3"):
        df = df[df["is_three"] == (1 if shot_type == "3" else 0)]
    if result in ("made", "missed"):
        df = df[df["made"] == (1 if result == "made" else 0)]
    if dmin is not None:
        df = df[df["distance"] >= dmin]
    if dmax is not None:
        df = df[df["distance"] <= dmax]
    if zone:
        df = df[df["zone"] == zone]
    return df


def summarize(df: pd.DataFrame, league_rows: list[dict], scorer: ShotScorer, max_points: int = 1200) -> dict[str, Any]:
    if df.empty:
        return {"empty": True, "totals": {"fga": 0, "fgm": 0}}
    df = df.copy()
    df["xfg"] = scorer.score(df)
    fga, fgm = len(df), int(df["made"].sum())
    threes = df[df["is_three"] == 1]
    efg = (fgm + 0.5 * int(threes["made"].sum())) / fga
    totals = {
        "fga": fga, "fgm": fgm, "fg_pct": round(100 * fgm / fga, 1), "efg_pct": round(100 * efg, 1),
        "fg3a": len(threes), "fg3_pct": round(100 * threes["made"].mean(), 1) if len(threes) else None,
        "avg_distance": round(float(df["distance"].mean()), 1), "xfg_pct": round(100 * float(df["xfg"].mean()), 1),
        "shot_making": round(float(fgm - df["xfg"].sum()), 1),
    }
    lg = defaultdict(lambda: [0, 0])
    for r in league_rows:
        z = r.get("shot_zone_basic")
        lg[z][0] += num(r.get("fga"), 0) or 0; lg[z][1] += num(r.get("fgm"), 0) or 0
    zones = []
    for z, g in df.groupby("zone"):
        a, m = len(g), int(g["made"].sum())
        league_pct = 100 * lg[z][1] / lg[z][0] if lg[z][0] else None
        zones.append({"zone": z, "fga": a, "fgm": m, "fg_pct": round(100 * m / a, 1), "freq_pct": round(100 * a / fga, 1),
                      "league_fg_pct": None if league_pct is None else round(league_pct, 1),
                      "diff": None if league_pct is None else round(100 * m / a - league_pct, 1),
                      "xfg_pct": round(100 * float(g["xfg"].mean()), 1)})
    zones.sort(key=lambda z: ZONE_ORDER.index(z["zone"]) if z["zone"] in ZONE_ORDER else 99)

    buckets = []
    for lo, hi, label in DIST_BUCKETS:
        g = df[(df["distance"] >= lo) & (df["distance"] < hi + 1)]
        if len(g):
            buckets.append({"label": label, "fga": len(g), "fg_pct": round(100 * g["made"].mean(), 1),
                            "xfg_pct": round(100 * float(g["xfg"].mean()), 1)})

    # spatial bins (3 ft cells) for the heat layer
    cell = 30
    bx, by = (df["loc_x"] // cell).astype(int), (df["loc_y"] // cell).astype(int)
    bins = []
    for (cx, cy), g in df.groupby([bx, by]):
        bins.append({"x": int(cx * cell + cell / 2), "y": int(cy * cell + cell / 2), "fga": len(g), "fgm": int(g["made"].sum())})

    pts = df if len(df) <= max_points else df.sample(max_points, random_state=7)
    shots = [[int(r.loc_x), int(r.loc_y), int(r.made), round(float(r.distance), 1), int(r.period), round(float(r.xfg), 3)]
             for r in pts.itertuples()]
    by_period = [{"period": int(p), "fga": len(g), "fg_pct": round(100 * g["made"].mean(), 1)} for p, g in df.groupby("period")]
    return {"empty": False, "totals": totals, "zones": zones, "distance_buckets": buckets, "bins": bins,
            "shots": shots, "shots_sampled": len(pts) < len(df), "by_period": by_period, "model": scorer.label}
