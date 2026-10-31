"""Fit + evaluate the pre-game model on REAL NBA results (needs network).

    python scripts/train_pregame.py            # warm-up + 3 train seasons + latest completed season as test
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.services import teams as T  # noqa: E402
from app.services.nba_data import NBAData  # noqa: E402
from app.services.pregame_training import fit_and_evaluate, save  # noqa: E402
from app.services.team_intel import games_from_log  # noqa: E402


def latest_complete_season() -> str:
    cur = T.current_season()
    f = NBAData().team_game_log(cur).data
    return T.previous_season(cur) if len({r["game_id"] for r in f}) < 1000 else cur


def main(n_seasons: int = 5) -> None:
    data = NBAData()
    last = latest_complete_season()
    seasons = list(reversed(T.recent_seasons(last, n_seasons)))
    games = []
    for s in seasons:
        print(f"fetching {s} ...")
        games.append((s, games_from_log(data.team_game_log(s).data, s)))
    model = fit_and_evaluate(games)
    out = Config.DATA_DIR / "models" / "pregame_model.json"
    save(model, out)
    ev = model["evaluation"]
    print(f"saved {out}\n  test {ev['test_season']}: acc={ev['accuracy']:.3f} logloss={ev['log_loss']:.3f} "
          f"brier={ev['brier']:.3f} | always-home acc={ev['baselines']['always_home_accuracy']:.3f}")


if __name__ == "__main__":
    main()
