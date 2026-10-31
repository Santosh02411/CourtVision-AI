"""Train / evaluate shot models on REAL shot outcomes (time-based holdout)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from xgboost import XGBClassifier

from app.models.shot_quality import REAL_SHOT_FEATURES
from app.services.pregame_training import calibration_bins


def _m(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {"log_loss": round(float(log_loss(y, p, labels=[0, 1])), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "auc": round(float(roc_auc_score(y, p)), 4)}


def train_and_evaluate(frame: pd.DataFrame, scorer_synthetic) -> tuple[dict, object, dict]:
    """frame: output of shot_analysis.shot_frame (needs game_date). Returns (report, calibrator, real_model_bundle)."""
    df = frame.dropna(subset=REAL_SHOT_FEATURES + ["made"]).sort_values("game_date").reset_index(drop=True)
    if len(df) < 5000:
        raise ValueError(f"Need >=5000 real shots (got {len(df)}). Increase the player count.")
    cut = int(len(df) * 0.8)
    tr, te = df.iloc[:cut], df.iloc[cut:]
    y_tr, y_te = tr["made"].values, te["made"].values

    syn_te = scorer_synthetic(te)
    syn_tr = scorer_synthetic(tr)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(syn_tr, y_tr)

    clf = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.9, colsample_bytree=0.9,
                        min_child_weight=20, eval_metric="logloss", random_state=7)
    clf.fit(tr[REAL_SHOT_FEATURES], y_tr)
    real_te = clf.predict_proba(te[REAL_SHOT_FEATURES])[:, 1]

    bins = []
    for lo, hi, label in [(0, 3, "0-3 ft"), (4, 9, "4-9 ft"), (10, 15, "10-15 ft"), (16, 21, "16-21 ft"), (22, 23, "22-23 ft"), (24, 99, "24+ ft")]:
        m = (te["distance"] >= lo) & (te["distance"] < hi + 1)
        if m.sum() >= 30:
            bins.append({"label": label, "n": int(m.sum()), "actual_fg_pct": round(100 * float(y_te[m.values].mean()), 1),
                         "synthetic_model_pct": round(100 * float(syn_te[m.values].mean()), 1),
                         "real_model_pct": round(100 * float(real_te[m.values].mean()), 1)})
    report = {
        "shots": int(len(df)), "train_shots": int(len(tr)), "test_shots": int(len(te)),
        "train_through": str(tr["game_date"].iloc[-1]), "test_from": str(te["game_date"].iloc[0]),
        "baseline_constant_fg": _m(np.full(len(te), y_tr.mean()), y_te),
        "synthetic_model": _m(syn_te, y_te),
        "synthetic_model_recalibrated": _m(np.clip(iso.predict(syn_te), 0.01, 0.99), y_te),
        "real_model": _m(real_te, y_te), "distance_calibration": bins,
        "calibration_bins_real_model": calibration_bins(real_te, y_te),
        "note": "Time-based split: model fit on earlier games, scored on the most recent 20% of shots.",
    }
    final = XGBClassifier(**clf.get_params()).fit(df[REAL_SHOT_FEATURES], df["made"].values)
    bundle = {"model": final, "features": REAL_SHOT_FEATURES, "metrics": {**report["real_model"], "test_shots": report["test_shots"],
              "trained_at": datetime.now(timezone.utc).isoformat()}}
    return report, iso, bundle
