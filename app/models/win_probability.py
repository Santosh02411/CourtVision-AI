"""PyTorch in-game win-probability model.

Trained on SYNTHETIC game states shipped with the repo (see `_synthetic_win_training_data`). Real-world
reliability is measured separately by `scripts/evaluate_real.py` (real play-by-play snapshots), which also
fits an optional Platt recalibration stored in `data/real/winprob_calibration.json`. Both facts are surfaced
in the UI through `metadata()` - synthetic training is never presented as real-world performance.
"""
from __future__ import annotations

import itertools
import json
from math import factorial
from pathlib import Path

import numpy as np
import torch
from torch import nn

from app.config import Config

WIN_FEATURES = ["score_diff", "time_remaining", "home_possession", "home_fouls", "away_fouls", "shot_quality"]
FEATURE_LABELS = {
    "score_diff": "Score margin", "time_remaining": "Time remaining", "home_possession": "Possession",
    "home_fouls": "Home team fouls", "away_fouls": "Away team fouls", "shot_quality": "Shot quality",
}
# Neutral reference state used for Shapley attributions ("tied, mid-game, no edge").
BASELINE = {"score_diff": 0.0, "time_remaining": 1440.0, "home_possession": 0.5, "home_fouls": 3.0,
            "away_fouls": 3.0, "shot_quality": 0.45}


class WinProbabilityNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(len(WIN_FEATURES), 24), nn.ReLU(), nn.Linear(24, 12), nn.ReLU(), nn.Linear(12, 1), nn.Sigmoid(),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features)


def normalize_features(values: dict[str, float]) -> np.ndarray:
    return np.array(
        [
            np.clip(values["score_diff"] / 35, -1.5, 1.5),
            np.clip(values["time_remaining"] / 2880, 0, 1),
            values["home_possession"],
            np.clip(values["home_fouls"] / 8, 0, 1.5),
            np.clip(values["away_fouls"] / 8, 0, 1.5),
            np.clip(values["shot_quality"], 0, 1),
        ],
        dtype=np.float32,
    )


def _synthetic_win_training_data(rows: int = 6000, seed: int = 11) -> tuple[torch.Tensor, torch.Tensor]:
    """SYNTHETIC generator - a hand-written logistic game model, not real NBA outcomes."""
    rng = np.random.default_rng(seed)
    time_remaining = rng.uniform(0, 2880, rows)
    score_diff = rng.normal(0, 13, rows) * (0.3 + (1 - time_remaining / 2880))
    home_possession = rng.integers(0, 2, rows)
    home_fouls = rng.integers(0, 7, rows)
    away_fouls = rng.integers(0, 7, rows)
    shot_quality = rng.uniform(0.15, 0.78, rows)

    late_weight = 1.1 + 3.4 * (1 - time_remaining / 2880)
    logits = (score_diff / 12) * late_weight + (home_possession * 2 - 1) * 0.12 + (away_fouls - home_fouls) * 0.04 \
        + (shot_quality - 0.45) * 0.35
    labels = rng.binomial(1, 1 / (1 + np.exp(-logits))).astype(np.float32)

    x = np.stack([
        normalize_features({
            "score_diff": score_diff[i], "time_remaining": time_remaining[i], "home_possession": home_possession[i],
            "home_fouls": home_fouls[i], "away_fouls": away_fouls[i], "shot_quality": shot_quality[i],
        }) for i in range(rows)
    ])
    return torch.tensor(x, dtype=torch.float32), torch.tensor(labels.reshape(-1, 1), dtype=torch.float32)


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


class WinProbabilityModel:
    def __init__(self, model_path: Path | str | None = None, calibration_path: Path | str | None = None) -> None:
        self.model_path = Path(model_path or Config.DATA_DIR / "models" / "win_probability.pt")
        self.calibration_path = Path(calibration_path or Config.DATA_DIR / "real" / "winprob_calibration.json")
        self.model = WinProbabilityNet()
        self._load_or_train()
        self.model.eval()
        self.calibration = self._load_calibration()

    # -- lifecycle ---------------------------------------------------------
    def _load_or_train(self) -> None:
        if self.model_path.exists():
            self.model.load_state_dict(torch.load(self.model_path, map_location="cpu", weights_only=True))
            return
        x_train, y_train = _synthetic_win_training_data()
        torch.manual_seed(11)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.012)
        loss_fn = nn.BCELoss()
        self.model.train()
        for _ in range(160):
            optimizer.zero_grad()
            loss_fn(self.model(x_train), y_train).backward()
            optimizer.step()
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), self.model_path)

    def _load_calibration(self) -> dict | None:
        try:
            cal = json.loads(self.calibration_path.read_text())
            return cal if {"a", "b"} <= cal.keys() else None
        except Exception:
            return None

    # -- inference ---------------------------------------------------------
    def _raw_batch(self, features: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return self.model(torch.tensor(features, dtype=torch.float32)).numpy().reshape(-1)

    def _calibrate(self, p: np.ndarray) -> np.ndarray:
        if not self.calibration:
            return p
        z = self.calibration["a"] * _logit(p) + self.calibration["b"]
        return 1 / (1 + np.exp(-z))

    def predict_batch(self, rows: list[dict[str, float]], raw: bool = False) -> list[float]:
        """Home win probabilities. `raw=True` skips the real-data Platt recalibration (used when fitting it)."""
        if not rows:
            return []
        p = self._raw_batch(np.stack([normalize_features(r) for r in rows]))
        p = p if raw else self._calibrate(p)
        return [round(float(v), 4) for v in np.clip(p, 0.01, 0.99)]

    def predict_home_win_probability(self, values: dict[str, float]) -> float:
        return self.predict_batch([values])[0]

    def explain(self, values: dict[str, float]) -> dict:
        """Exact Shapley attribution (baseline-substitution) in log-odds space over the 6 inputs."""
        n = len(WIN_FEATURES)
        x, b = normalize_features(values), normalize_features(BASELINE)
        masks = list(itertools.product([0, 1], repeat=n))
        batch = np.stack([np.where(np.array(m, dtype=bool), x, b) for m in masks])
        v = dict(zip(masks, _logit(self._raw_batch(batch))))
        phi = np.zeros(n)
        for i in range(n):
            for m in masks:
                if m[i]:
                    continue
                s = sum(m)
                w = factorial(s) * factorial(n - s - 1) / factorial(n)
                m_i = tuple(1 if j == i else m[j] for j in range(n))
                phi[i] += w * (v[m_i] - v[m])
        base_logit = float(v[tuple([0] * n)])
        out = [{"feature": f, "label": FEATURE_LABELS[f], "value": round(float(values[f]), 3),
                "contribution": round(float(phi[k]), 4)} for k, f in enumerate(WIN_FEATURES)]
        out.sort(key=lambda r: -abs(r["contribution"]))
        return {"method": "Exact Shapley values (baseline substitution), log-odds space",
                "baseline_probability": round(float(1 / (1 + np.exp(-base_logit))), 4), "factors": out}

    def metadata(self) -> dict:
        return {
            "name": "In-game win probability", "framework": "PyTorch MLP (6 → 24 → 12 → 1)",
            "trained_on": "synthetic", "recalibrated_on_real": bool(self.calibration),
            "calibration": self.calibration,
        }
