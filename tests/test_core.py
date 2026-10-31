from datetime import date

import numpy as np
import pytest

from app.services import teams as T
from app.services.util import clock_seconds, elapsed_seconds, time_remaining


def test_season_is_dynamic():
    assert T.current_season(date(2026, 11, 1)) == "2026-27"
    assert T.current_season(date(2026, 9, 30)) == "2025-26"
    assert T.current_season(date(2027, 1, 15)) == "2026-27"
    assert T.valid_season("2026-27", date(2026, 11, 1)) == "2026-27"
    assert T.valid_season("2026-28", date(2026, 11, 1)) is None
    assert T.valid_season("2030-31", date(2026, 11, 1)) is None
    assert T.valid_season("abc") is None


def test_team_resolution_and_aliases():
    assert T.resolve_team("NY")["abbr"] == "NYK"
    assert T.resolve_team("lakers")["abbr"] == "LAL"
    assert T.resolve_team(1610612738)["abbr"] == "BOS"
    assert len(T.TEAMS) == 30 and T.resolve_team("nope") is None


def test_clock_math():
    assert clock_seconds("PT05M32.00S") == 332
    assert time_remaining(4, "PT00M00.00S") == 0
    assert time_remaining(1, "PT12M00.00S") == 2880
    assert elapsed_seconds(2, "PT12M00.00S") == 720
    assert elapsed_seconds(5, "PT05M00.00S") == 2880


def test_win_probability_is_sensible_and_explained():
    from app.models.win_probability import WinProbabilityModel
    m = WinProbabilityModel()
    base = {"score_diff": 0, "time_remaining": 600, "home_possession": 0.5, "home_fouls": 3, "away_fouls": 3, "shot_quality": 0.45}
    up, down = m.predict_home_win_probability({**base, "score_diff": 8}), m.predict_home_win_probability({**base, "score_diff": -8})
    assert up > 0.5 > down
    late = m.predict_home_win_probability({**base, "score_diff": 8, "time_remaining": 60})
    assert late > up                                   # same lead is safer with less time left
    ex = m.explain({**base, "score_diff": 8})
    total = sum(f["contribution"] for f in ex["factors"])
    p, p0 = m.predict_home_win_probability({**base, "score_diff": 8}), ex["baseline_probability"]
    raw = m._raw_batch(np.stack([__import__("app.models.win_probability", fromlist=["x"]).normalize_features({**base, "score_diff": 8})]))[0]
    assert total == pytest.approx(np.log(raw / (1 - raw)) - np.log(p0 / (1 - p0)), abs=1e-3)   # Shapley efficiency


def test_shot_model_treeshap_adds_up():
    from app.models.shot_quality import ShotContext, ShotQualityModel
    m = ShotQualityModel(); ctx = ShotContext(4, 0, 4.5, 12, 1)
    ex = m.explain(ctx)
    assert ex["base_value"] + sum(f["contribution"] for f in ex["factors"]) == pytest.approx(m.predict(ctx), abs=1e-3)
    assert m.predict(ShotContext(2, 0, 6, 12, 1)) > m.predict(ShotContext(28, 0, 6, 12, 1))
    assert m.evaluation()["holdout_kind"] == "synthetic"


def test_elo_is_zero_sum_and_rewards_upsets():
    from app.services.team_intel import elo_update
    h, a = elo_update(1500, 1500, 110, 100)
    assert h + a == pytest.approx(3000) and h > 1500
    h2, _ = elo_update(1400, 1600, 100, 99)            # underdog narrowly wins -> bigger gain than a favourite would get
    h3, _ = elo_update(1600, 1400, 100, 99)
    assert h2 - 1400 > h3 - 1600


def test_pregame_training_pipeline_on_fixture_games():
    from app.services.pregame_training import fit_and_evaluate
    from app.services.team_intel import games_from_log
    from tests.fakes import FakeNBAData
    fake = FakeNBAData(past_games=350)
    seasons = ["2022-23", "2023-24", "2024-25", "2025-26"]
    model = fit_and_evaluate([(s, games_from_log(fake.team_game_log(s).data, s)) for s in seasons])
    ev = model["evaluation"]
    assert model["trained_on"] == "real" and ev["test_season"] == "2025-26" and ev["test_games"] >= 100
    assert ev["accuracy"] > 0.5 and ev["calibration"] and ev["baselines"]["elo_only_log_loss"]


def test_shot_training_pipeline_on_fixture_shots():
    import pandas as pd
    from app.models.shot_quality import ShotQualityModel
    from app.services.shot_analysis import shot_frame
    from app.services.shot_training import train_and_evaluate
    from tests.fakes import FakeNBAData
    fake = FakeNBAData(); syn = ShotQualityModel()
    frame = pd.concat([shot_frame(fake.shot_chart(1630000 + i, "2026-27").data["shots"]) for i in range(16)], ignore_index=True)

    def scorer(df):
        f = df.copy(); f["angle"] = f["angle"].clip(-55, 55); f["defender_distance"] = 4.5; f["shot_clock"] = 12.0; f["game_situation"] = (f["period"] - 1).clip(0, 2)
        return syn.predict_frame(f)
    report, iso, bundle = train_and_evaluate(frame, scorer)
    assert report["test_shots"] > 500 and 0 < report["real_model"]["auc"] <= 1 and bundle["features"]
