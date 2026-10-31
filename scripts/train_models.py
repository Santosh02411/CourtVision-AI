"""(Re)train the SYNTHETIC-data models and write their artifacts.

    python scripts/train_models.py

Writes data/models/{shot_quality_xgb.json, win_probability.pt} and data/synthetic/shot_quality_training.csv.
These models are trained on generated data; measure them on real games/shots with scripts/evaluate_real.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.models.shot_quality import ShotQualityModel, _synthetic_shot_training_data  # noqa: E402
from app.models.win_probability import WinProbabilityModel  # noqa: E402


def main() -> None:
    models = Config.DATA_DIR / "models"
    for name in ("shot_quality_xgb.json", "win_probability.pt"):
        (models / name).unlink(missing_ok=True)          # force a fresh fit
    shot = ShotQualityModel()
    WinProbabilityModel()
    x, y = _synthetic_shot_training_data()
    out = Config.DATA_DIR / "synthetic" / "shot_quality_training.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([x, y], axis=1).to_csv(out, index=False)
    print("synthetic holdout:", shot.evaluation(), "\nartifacts in", models)


if __name__ == "__main__":
    main()
