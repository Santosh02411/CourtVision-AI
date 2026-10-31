"""Walk-forward training + honest evaluation of the pre-game win model (real NBA results only).

Pipeline: replay N seasons of real games -> features are computed strictly from games BEFORE each game ->
fit a logistic regression on earlier seasons -> evaluate on the held-out most recent season.
The first season is a warm-up for Elo and is excluded from fitting.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from app.services.team_intel import FEATURES, replay


def collect(games_by_season: list[tuple[str, list[dict]]]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    X, y, seasons = [], [], []

    def hook(state, g, d, feats):
        if state.season != games_by_season[0][0]:           # skip warm-up season
            X.append([feats[f] for f in FEATURES])
            y.append(1 if g["home_pts"] > g["away_pts"] else 0)
            seasons.append(state.season)

    replay(games_by_season, on_game=hook)
    return np.array(X, dtype=float), np.array(y, dtype=int), seasons


def calibration_bins(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum():
            out.append({"lo": round(float(lo), 2), "hi": round(float(hi), 2), "n": int(m.sum()),
                        "predicted": round(float(p[m].mean()), 4), "actual": round(float(y[m].mean()), 4)})
    return out


def fit_and_evaluate(games_by_season: list[tuple[str, list[dict]]], c: float = 0.5) -> dict:
    X, y, seasons = collect(games_by_season)
    test_season = games_by_season[-1][0]
    test = np.array([s == test_season for s in seasons])
    if test.sum() < 100 or (~test).sum() < 300:
        raise ValueError("Not enough real games to train and evaluate (need >=300 train and >=100 test games).")
    clf = LogisticRegression(C=c, max_iter=500).fit(X[~test], y[~test])
    p = clf.predict_proba(X[test])[:, 1]
    base_rate = float(y[~test].mean())
    elo_only = LogisticRegression(max_iter=500).fit(X[~test][:, :1], y[~test])
    p_elo = elo_only.predict_proba(X[test][:, :1])[:, 1]
    metrics = {
        "test_season": test_season, "test_games": int(test.sum()), "train_games": int((~test).sum()),
        "accuracy": round(float(((p > 0.5) == y[test]).mean()), 4),
        "log_loss": round(float(log_loss(y[test], p)), 4), "brier": round(float(brier_score_loss(y[test], p)), 4),
        "baselines": {
            "always_home_accuracy": round(float(y[test].mean()), 4),
            "home_rate_log_loss": round(float(log_loss(y[test], np.full(test.sum(), base_rate))), 4),
            "elo_only_accuracy": round(float(((p_elo > 0.5) == y[test]).mean()), 4),
            "elo_only_log_loss": round(float(log_loss(y[test], p_elo)), 4),
        },
        "calibration": calibration_bins(p, y[test]),
    }
    final = LogisticRegression(C=c, max_iter=500).fit(X, y)   # production weights use every real game
    return {
        "name": "Pre-game win model", "type": "Logistic regression on Elo, point differential, form, rest",
        "trained_on": "real", "trained_at": datetime.now(timezone.utc).isoformat(),
        "seasons": [s for s, _ in games_by_season], "features": FEATURES,
        "intercept": float(final.intercept_[0]), "coefficients": dict(zip(FEATURES, map(float, final.coef_[0]))),
        "feature_means": dict(zip(FEATURES, map(float, X.mean(axis=0)))),
        "evaluation": metrics,
        "evaluation_note": f"Out-of-sample: fit on seasons before {test_season}, scored on every {test_season} game. "
                           f"Shipped weights are refit on all {len(y)} games.",
    }


def save(model: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2))
