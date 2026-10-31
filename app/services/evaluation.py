"""Model cards: what each model is, what it was trained on, and how it scored on REAL vs SYNTHETIC data."""
from __future__ import annotations

import json
from typing import Any

import numpy as np
from sklearn.metrics import log_loss

from app.config import Config
from app.models.shot_quality import ShotQualityModel
from app.models.win_probability import WinProbabilityModel, _synthetic_win_training_data
from app.services.predictor import Predictor
from app.services.shot_analysis import ShotScorer

REAL_REPORT = Config.DATA_DIR / "real" / "evaluation_report.json"
SAMPLE_REPORT = Config.DATA_DIR / "real" / "sample_backtest_2_games.json"


def _load(path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def model_cards(predictor: Predictor, win: WinProbabilityModel, shot: ShotQualityModel, scorer: ShotScorer) -> dict[str, Any]:
    report = _load(REAL_REPORT) or {}
    sample = _load(SAMPLE_REPORT)

    x, y = _synthetic_win_training_data(rows=2000, seed=99)
    raw_p = win._raw_batch(x.numpy())
    syn_win = {"log_loss": round(float(log_loss(y.numpy().ravel(), np.clip(raw_p, 1e-4, 1 - 1e-4))), 4),
               "accuracy": round(float(((raw_p > 0.5) == y.numpy().ravel()).mean()), 4), "rows": 2000}

    pre = predictor.model_card()
    cards = [
        {"id": "pregame", "name": "Pre-game win probability", "type": pre["type"], "trained_on": pre["trained_on"],
         "fitted_on_real": pre["fitted"], "status": "validated" if pre["fitted"] else "uncalibrated-prior",
         "real_evaluation": pre["evaluation"], "note": pre.get("evaluation_note") or pre.get("warning"),
         "used_for": "Predictions Center, scoreboard pre-game odds, matchup explainability"},
        {"id": "winprob", "name": "In-game win probability", "type": win.metadata()["framework"], "trained_on": "synthetic",
         "fitted_on_real": False, "recalibrated_on_real": bool(win.calibration),
         "status": "real-evaluated" if report.get("win_probability") else "synthetic-only",
         "synthetic_evaluation": syn_win,
         "real_evaluation": report.get("win_probability"),
         "tiny_sample": (sample or {}).get("win_probability") if not report.get("win_probability") else None,
         "note": "Trained on a synthetic generator. Run scripts/evaluate_real.py to score it on real play-by-play and fit a recalibration."
         if not report.get("win_probability") else "Scored on real play-by-play; Platt recalibration applied when it improved held-out log loss.",
         "used_for": "Live win-probability, Game Impact Analyzer"},
        {"id": "shot", "name": "Shot quality / expected FG%", "type": scorer.label["model"], "trained_on": scorer.label["trained_on"],
         "fitted_on_real": scorer.label["trained_on"] == "real", "recalibrated_on_real": bool(scorer.calibrator),
         "status": "real-evaluated" if report.get("shot_model") else "synthetic-only",
         "synthetic_evaluation": shot.evaluation(), "real_evaluation": report.get("shot_model"),
         "tiny_sample": (sample or {}).get("shot_quality") if not report.get("shot_model") else None,
         "note": scorer.label.get("caveat") or "Trained and evaluated on real shot outcomes (time-based holdout).",
         "used_for": "Shot Analysis, Game Impact Analyzer shot map"},
        {"id": "archetypes", "name": "Player archetypes & similarity", "type": "K-means (k=6) + cosine similarity on per-36 and rate stats",
         "trained_on": "real (unsupervised, current-season league data)", "fitted_on_real": True, "status": "unsupervised",
         "note": "No ground-truth labels exist, so there is no accuracy metric; labels are assigned by centroid characteristics.",
         "used_for": "Player Intelligence, Player Comparison"},
    ]
    return {"cards": cards, "feature_importance": {"shot_quality_synthetic": shot.feature_importance()},
            "real_report_generated_at": report.get("generated_at")}
