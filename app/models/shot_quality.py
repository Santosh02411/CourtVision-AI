"""Shot-quality models.

* `ShotQualityModel` - XGBoost regressor trained on SYNTHETIC shots (data/synthetic/shot_quality_training.csv).
* `RealShotModel`    - optional XGBoost classifier trained on REAL shot-chart outcomes by
  `scripts/train_real_shot_model.py` (loaded from data/models/shot_xg_real.joblib when present).

Which one is serving, and how it scored on real shots, is always reported by `metadata()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import DMatrix, XGBRegressor

from app.config import Config

SHOT_FEATURES = ["distance", "angle", "defender_distance", "shot_clock", "game_situation"]
REAL_SHOT_FEATURES = ["distance", "angle", "loc_x", "loc_y", "is_three", "period", "secs_left"]
FEATURE_LABELS = {
    "distance": "Shot distance", "angle": "Shot angle", "defender_distance": "Defender distance",
    "shot_clock": "Shot clock", "game_situation": "Game situation", "loc_x": "Court x", "loc_y": "Court y",
    "is_three": "Three-point attempt", "period": "Period", "secs_left": "Time left in period",
}
# Tracking-only inputs that public shot charts do not provide: held at neutral values (documented in the UI).
NEUTRAL_DEFENDER_DISTANCE = 4.5
NEUTRAL_SHOT_CLOCK = 12.0


@dataclass(frozen=True)
class ShotContext:
    distance: float
    angle: float
    defender_distance: float
    shot_clock: float
    game_situation: int

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame([[self.distance, self.angle, self.defender_distance, self.shot_clock, self.game_situation]],
                            columns=SHOT_FEATURES)


def _synthetic_shot_training_data(rows: int = 2500, seed: int = 7) -> tuple[pd.DataFrame, pd.Series]:
    """SYNTHETIC generator - a hand-written quality function, not real shot outcomes."""
    rng = np.random.default_rng(seed)
    distance = rng.uniform(1, 31, rows)
    angle = rng.uniform(-55, 55, rows)
    defender_distance = rng.uniform(0, 12, rows)
    shot_clock = rng.uniform(0, 24, rows)
    game_situation = rng.integers(0, 4, rows)

    quality = (0.23 + np.clip((28 - distance) / 28, 0, 1) * 0.38 + np.clip(defender_distance / 10, 0, 1) * 0.22
               + np.clip(shot_clock / 24, 0, 1) * 0.10
               + ((distance > 21) & (np.abs(angle) > 35)).astype(float) * 0.05
               - (game_situation == 3).astype(float) * 0.05 - np.clip(np.abs(angle) / 55, 0, 1) * 0.10
               + rng.normal(0, 0.035, rows))
    frame = pd.DataFrame({"distance": distance, "angle": angle, "defender_distance": defender_distance,
                          "shot_clock": shot_clock, "game_situation": game_situation}, columns=SHOT_FEATURES)
    return frame, pd.Series(np.clip(quality, 0.05, 0.82), name="shot_quality")


class ShotQualityModel:
    def __init__(self, model_path: Path | str | None = None) -> None:
        self.model_path = Path(model_path or Config.DATA_DIR / "models" / "shot_quality_xgb.json")
        self.model = self._load_or_train()
        self._eval = self._evaluate()

    def _load_or_train(self) -> XGBRegressor:
        if self.model_path.exists():
            model = XGBRegressor()
            model.load_model(str(self.model_path))  # native JSON: stable across xgboost versions
            return model
        x_train, y_train = _synthetic_shot_training_data()
        model = XGBRegressor(objective="reg:squarederror", n_estimators=180, max_depth=4, learning_rate=0.055,
                             subsample=0.88, colsample_bytree=0.9, random_state=7)
        model.fit(x_train, y_train)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(str(self.model_path))
        return model

    def predict(self, context: ShotContext) -> float:
        return float(np.clip(self.model.predict(context.as_frame())[0], 0.01, 0.99))

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        return np.clip(self.model.predict(frame[SHOT_FEATURES]), 0.01, 0.99)

    def explain(self, context: ShotContext) -> dict:
        """Exact TreeSHAP values via XGBoost's native `pred_contribs` (no extra dependency)."""
        contribs = self.model.get_booster().predict(DMatrix(context.as_frame()), pred_contribs=True)[0]
        rows = [{"feature": f, "label": FEATURE_LABELS[f], "value": round(float(getattr(context, f)), 2),
                 "contribution": round(float(c), 4)} for f, c in zip(SHOT_FEATURES, contribs[:-1])]
        rows.sort(key=lambda r: -abs(r["contribution"]))
        return {"method": "TreeSHAP (XGBoost pred_contribs)", "base_value": round(float(contribs[-1]), 4), "factors": rows}

    def feature_importance(self) -> dict[str, float]:
        scores = getattr(self.model, "feature_importances_", np.zeros(len(SHOT_FEATURES)))
        return {f: round(float(s), 4) for f, s in zip(SHOT_FEATURES, scores)}

    def _evaluate(self, rows: int = 2000, seed: int = 99) -> dict:
        x_eval, y_eval = _synthetic_shot_training_data(rows=rows, seed=seed)
        pred = self.model.predict(x_eval)
        return {"r2": round(float(r2_score(y_eval, pred)), 4), "mae": round(float(mean_absolute_error(y_eval, pred)), 4),
                "holdout_rows": rows, "holdout_kind": "synthetic"}

    def evaluation(self) -> dict:
        return dict(self._eval)


class RealShotModel:
    """Loads the real-data shot model bundle written by scripts/train_real_shot_model.py (if present)."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or Config.DATA_DIR / "models" / "shot_xg_real.joblib")
        self.bundle = None
        if self.path.exists():
            try:
                self.bundle = joblib.load(self.path)
            except Exception:
                self.bundle = None

    @property
    def available(self) -> bool:
        return self.bundle is not None

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        return np.clip(self.bundle["model"].predict_proba(frame[REAL_SHOT_FEATURES])[:, 1], 0.01, 0.99)

    def explain(self, row: dict) -> dict:
        frame = pd.DataFrame([row])[REAL_SHOT_FEATURES]
        contribs = self.bundle["model"].get_booster().predict(DMatrix(frame), pred_contribs=True)[0]
        rows = [{"feature": f, "label": FEATURE_LABELS[f], "value": round(float(row[f]), 2), "contribution": round(float(c), 4)}
                for f, c in zip(REAL_SHOT_FEATURES, contribs[:-1])]
        rows.sort(key=lambda r: -abs(r["contribution"]))
        return {"method": "TreeSHAP (log-odds)", "base_value": round(float(contribs[-1]), 4), "factors": rows}

    def metrics(self) -> dict:
        return (self.bundle or {}).get("metrics", {})
