"""Score the in-game win-probability model on REAL finished games and fit a Platt recalibration (held-out by game)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from app.models.win_probability import WinProbabilityModel
from app.services.live import attach_win_probability, build_states
from app.services.pregame_training import calibration_bins


def _metrics(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {"log_loss": round(float(log_loss(y, p, labels=[0, 1])), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "accuracy": round(float(((p > 0.5) == y).mean()), 4)}


def evaluate(games: list[dict], model: WinProbabilityModel, scorer, stride: int = 10) -> tuple[dict, dict | None]:
    """games: [{game_id, home_id, away_id, actions, home_won}] -> (report, platt params or None)."""
    P, Y, G, PH = [], [], [], []
    for gi, g in enumerate(games):
        rows, _ = build_states(g["actions"], g["home_id"], g["away_id"], scorer)
        if len(rows) < 50:
            continue
        feats = [{"score_diff": r["sh"] - r["sa"], "time_remaining": r["tr"], "home_possession": r["poss_home"],
                  "home_fouls": r["hf"], "away_fouls": r["af"], "shot_quality": r["quality"]} for r in rows]
        p = model.predict_batch(feats, raw=True)
        for i in range(0, len(rows) - 2, stride):          # exclude the last events, whose outcome is already decided
            P.append(p[i]); Y.append(1 if g["home_won"] else 0); G.append(gi)
            frac = rows[i]["elapsed"] / 2880.0
            PH.append("Q1" if frac < .25 else "Q2" if frac < .5 else "Q3" if frac < .75 else "Q4" if frac < 1 else "OT")
    P, Y, G, PH = np.array(P), np.array(Y), np.array(G), np.array(PH)
    n_games = len(set(G.tolist()))
    if n_games < 20:
        raise ValueError(f"Need at least 20 usable finished games (got {n_games}).")
    cut = sorted(set(G.tolist()))[int(0.7 * n_games)]
    tr, te = G < cut, G >= cut
    z = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4))).reshape(-1, 1)
    lr = LogisticRegression(C=100.0, max_iter=500).fit(z(P[tr]), Y[tr])
    platt = {"a": float(lr.coef_[0][0]), "b": float(lr.intercept_[0]), "n_fit_snapshots": int(tr.sum()),
             "fitted_at": datetime.now(timezone.utc).isoformat()}
    p_cal = lr.predict_proba(z(P[te]))[:, 1]
    raw_m, cal_m = _metrics(P[te], Y[te]), _metrics(p_cal, Y[te])
    use_cal = cal_m["log_loss"] < raw_m["log_loss"]
    report = {
        "games": n_games, "snapshots": int(len(P)), "test_games": int(len(set(G[te].tolist()))), "test_snapshots": int(te.sum()),
        "raw": raw_m, "calibrated": cal_m, "recalibration_applied": use_cal,
        "baseline_constant_home_rate": _metrics(np.full(te.sum(), Y[tr].mean()), Y[te]),
        "by_phase": [{"phase": ph, "n": int((PH[te] == ph).sum()), **_metrics((p_cal if use_cal else P[te])[PH[te] == ph], Y[te][PH[te] == ph])}
                     for ph in ("Q1", "Q2", "Q3", "Q4", "OT") if (PH[te] == ph).sum() >= 20],
        "calibration_bins": calibration_bins(p_cal if use_cal else P[te], Y[te]),
        "note": "Held-out by game: recalibration fit on the first 70% of games, metrics on the last 30%.",
    }
    return report, (platt if use_cal else None)
