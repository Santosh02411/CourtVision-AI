"""Fallback paths. Payload shapes below follow the documented stats.nba.com V2/V3 layouts (assumed, not captured live)."""
from app.services.live import parse_boxscore
from app.services.nba_data import NBAData
from app.services.cache import TTLCache


def test_box_from_v3_feeds_the_existing_parser():
    raw = {"boxScoreTraditional": {"gameId": "0022600001",
        "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "totals": {"points": 110, "fieldGoalsMade": 40, "fieldGoalsAttempted": 85, "reboundsTotal": 44},
                     "players": [{"personId": 1, "nameI": "A. Davis", "position": "F-C", "jerseyNum": "3",
                                  "statistics": {"minutes": "35:12", "points": 28, "reboundsTotal": 11, "assists": 3, "fieldGoalsMade": 10, "fieldGoalsAttempted": 18, "plusMinusPoints": 7}}]},
        "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "totals": {"points": 104}, "players": []}}}
    game = NBAData.box_from_v3(raw)
    bx = parse_boxscore(game)
    assert bx["home"]["score"] == 110 and bx["away"]["score"] == 104
    p = bx["home"]["players"][0]
    assert p["name"] == "A. Davis" and p["pts"] == 28 and abs(p["min"] - 35.2) < 0.1 and p["starter"]
    assert bx["home"]["stats"]["paint"] is None          # unavailable stats stay None, never a fake 0


def test_cdn_block_switches_to_stats_fallback_and_remembers():
    d = NBAData(cache=TTLCache(None)); calls = {"cdn": 0, "stats": 0}

    def cdn():
        calls["cdn"] += 1; raise RuntimeError("403")

    def stats():
        calls["stats"] += 1; return {"ok": True}
    assert d._cdn_or_stats(cdn, stats) == {"ok": True}
    assert d._cdn_or_stats(cdn, stats) == {"ok": True}
    assert calls == {"cdn": 1, "stats": 2}                # CDN is skipped while marked down
