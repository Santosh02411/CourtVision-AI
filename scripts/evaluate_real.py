"""Score the models on REAL NBA data (needs network) and write data/real/evaluation_report.json.

    python scripts/evaluate_real.py --games 120 --players 60

* Win probability: replays real finished games' play-by-play, scores the PyTorch model, fits a held-out Platt recalibration.
* Shot model: pulls real shot charts of the top shooters, trains an XGBoost classifier on earlier games, scores the
  synthetic-trained model, a recalibrated version and the real-trained model on the most recent shots.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.models.shot_quality import (NEUTRAL_DEFENDER_DISTANCE, NEUTRAL_SHOT_CLOCK, RealShotModel,  # noqa: E402
                                     ShotQualityModel)
from app.models.win_probability import WinProbabilityModel  # noqa: E402
from app.services import teams as T  # noqa: E402
from app.services.cache import DataUnavailable  # noqa: E402
from app.services.nba_data import NBAData  # noqa: E402
from app.services.shot_analysis import ShotScorer, shot_frame  # noqa: E402
from app.services.shot_training import train_and_evaluate  # noqa: E402
from app.services.winprob_eval import evaluate  # noqa: E402

REAL = Config.DATA_DIR / "real"


def eval_winprob(data: NBAData, n_games: int, report: dict) -> None:
    sched = [g for g in data.schedule().data if g["status"] == "final" and g["stage"] in ("regular", "playoffs")]
    if len(sched) < 30:
        print("not enough finished games on the schedule yet - skipping win-probability evaluation"); return
    step = max(1, len(sched) // n_games)
    games = []
    for g in sched[::step][:n_games]:
        try:
            actions = data.playbyplay(g["game_id"], final=True).data
            games.append({"game_id": g["game_id"], "home_id": g["home"]["id"], "away_id": g["away"]["id"], "actions": actions,
                          "home_won": g["home"]["score"] > g["away"]["score"]})
        except DataUnavailable as exc:
            print("skip", g["game_id"], exc.reason)
    model = WinProbabilityModel()
    scorer = ShotScorer(ShotQualityModel(), RealShotModel())
    wp_report, platt = evaluate(games, model, scorer)
    report["win_probability"] = wp_report
    path = REAL / "winprob_calibration.json"
    if platt:
        path.write_text(json.dumps(platt, indent=2)); print("saved", path)
    elif path.exists():
        path.unlink()
    print("win prob:", wp_report["raw"], "->", wp_report["calibrated"], "applied:", wp_report["recalibration_applied"])


def eval_shots(data: NBAData, n_players: int, report: dict) -> None:
    from app.services.player_intel import PlayerIntel
    season = T.current_season()
    table, _ = PlayerIntel(data).table(season)
    seasons = [season, T.previous_season(season)]
    top = sorted(table["players"], key=lambda p: -(p["pts"] or 0))[:n_players]
    frames = []
    for p in top:
        for s in seasons:
            try:
                rows = data.shot_chart(p["id"], s).data["shots"]
                f = shot_frame(rows)
                if len(f):
                    frames.append(f)
            except DataUnavailable:
                continue
    if not frames:
        print("no shot data - skipping"); return
    frame = pd.concat(frames, ignore_index=True)
    syn = ShotQualityModel()

    def syn_scorer(df: pd.DataFrame):
        f = df.copy()
        f["angle"] = f["angle"].clip(-55, 55); f["defender_distance"] = NEUTRAL_DEFENDER_DISTANCE
        f["shot_clock"] = NEUTRAL_SHOT_CLOCK; f["game_situation"] = (f["period"] - 1).clip(0, 2)
        return syn.predict_frame(f)

    shot_report, iso, bundle = train_and_evaluate(frame, syn_scorer)
    report["shot_model"] = shot_report
    joblib.dump(iso, REAL / "shot_calibrator.joblib")
    joblib.dump(bundle, Config.DATA_DIR / "models" / "shot_xg_real.joblib")
    print("shots:", {k: shot_report[k] for k in ("baseline_constant_fg", "synthetic_model", "synthetic_model_recalibrated", "real_model")})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=120); ap.add_argument("--players", type=int, default=60)
    ap.add_argument("--skip-shots", action="store_true"); ap.add_argument("--skip-winprob", action="store_true")
    a = ap.parse_args()
    data, report = NBAData(), {}
    report["generated_at"] = pd.Timestamp.utcnow().isoformat()
    if not a.skip_winprob:
        eval_winprob(data, a.games, report)
    if not a.skip_shots:
        eval_shots(data, a.players, report)
    (REAL / "evaluation_report.json").write_text(json.dumps(report, indent=2))
    print("wrote", REAL / "evaluation_report.json")


if __name__ == "__main__":
    main()
