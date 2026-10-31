import pytest

from app.services.cache import DataUnavailable


def get(client, path):
    r = client.get(path)
    return r.status_code, r.get_json()


def test_envelope_and_meta(client):
    code, j = get(client, "/api/v1/meta")
    assert code == 200 and j["ok"] and j["meta"]["kind"] == "derived"
    assert j["data"]["current_season"] == "2026-27" and len(j["data"]["teams"]) == 30 and j["data"]["today"]


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/teams", "/api/v1/teams/LAL", "/api/v1/players?limit=5", "/api/v1/standings", "/api/v1/scoreboard",
                                  "/api/v1/schedule", "/api/v1/models", "/api/v1/overview", "/api/v1/predictions/slate", "/api/v1/news", "/api/v1/search?q=ja"])
def test_endpoints_ok(client, path):
    code, j = get(client, path)
    assert code == 200 and j["ok"], j


def test_validation_and_errors(client):
    assert get(client, "/api/v1/teams/XXX")[0] == 404
    assert get(client, "/api/v1/players?season=1999-00")[1]["error"]["code"] == "invalid_season"
    assert get(client, "/api/v1/players?sort=hax")[0] == 400
    assert get(client, "/api/v1/predictions/matchup?home=LAL&away=LAL")[0] == 400
    assert get(client, "/api/v1/scoreboard?date=nope")[0] == 400
    assert get(client, "/api/v1/games/..%2f")[0] in (400, 404)
    assert get(client, "/api/v1/ai/brief?type=nope")[0] == 400
    assert get(client, "/api/v1/players/1630143/shots?type=9")[0] == 400


def test_player_flow(client):
    pid = get(client, "/api/v1/players?limit=2")[1]["data"]["players"]
    a, b = pid[0]["id"], pid[1]["id"]
    d = get(client, f"/api/v1/players/{a}")[1]["data"]
    assert d["player"]["percentiles"] and d["similar"] and d["form"]["summary"]
    cmp = get(client, f"/api/v1/players/compare?a={a}&b={b}")[1]["data"]
    assert cmp["metrics"] and cmp["radar_axes"]
    sh = get(client, f"/api/v1/players/{a}/shots?type=3&period=1,2")[1]["data"]
    assert not sh["empty"] and all(z["zone"] for z in sh["zones"]) and sh["model"]["trained_on"] in ("synthetic", "real")


def test_game_impact_and_prediction(client):
    games = get(client, "/api/v1/schedule")[1]["data"]["games"]
    fin = next(g for g in games if g["status"] == "final")
    d = get(client, f"/api/v1/games/{fin['game_id']}")[1]["data"]
    assert d["impact"]["timeline"] and d["impact"]["swings"] and "turning_point" in d["impact"]
    assert all(0 <= p["wp"] <= 1 for p in d["impact"]["timeline"])
    pr = get(client, "/api/v1/predictions/matchup?home=LAL&away=BOS")[1]["data"]
    assert pr["probabilities"]["home"] + pr["probabilities"]["away"] == pytest.approx(1, abs=1e-3)
    assert {f["key"] for f in pr["factors"]} >= {"elo_diff", "margin_diff", "form_diff", "availability"}
    assert pr["model"]["fitted"] is False and pr["model"]["warning"]          # un-fitted model must be flagged
    assert pr["confidence"]["label"] in ("Low", "Medium", "High")


def test_models_endpoint_separates_synthetic_from_real(client):
    cards = {c["id"]: c for c in get(client, "/api/v1/models")[1]["data"]["cards"]}
    assert cards["winprob"]["trained_on"] == "synthetic" and cards["winprob"]["synthetic_evaluation"]
    assert cards["shot"]["trained_on"] in ("synthetic", "real")


def test_ai_brief_is_labelled_rule_based_without_key(client):
    j = get(client, "/api/v1/ai/brief?type=matchup&home=LAL&away=BOS")[1]["data"]
    assert j["generated_by"] == "rule-based" and j["facts"]


def test_legacy_redirects(client):
    r = client.get("/api/standings?season=2026-27")
    assert r.status_code == 307 and "/api/v1/standings" in r.headers["Location"] and r.headers["Deprecation"] == "true"


def test_security_headers_and_spa(client):
    r = client.get("/")
    assert r.status_code == 200 and b"CourtVision AI" in r.data and b"NBA-AI" not in r.data
    assert "script-src 'self'" in r.headers["Content-Security-Policy"] and r.headers["X-Frame-Options"] == "DENY"


def test_upstream_failure_is_reported_never_fabricated(app):
    from app.api.routes import Services
    from app.main import create_app
    from tests.fakes import FakeNBAData

    class Down(FakeNBAData):
        def standings(self, season):
            raise DataUnavailable("NBA Stats", "boom")
        def schedule(self):
            raise DataUnavailable("NBA CDN", "boom")
        def scoreboard_today(self):
            raise DataUnavailable("NBA CDN", "boom")

    c = create_app(services=Services(data=Down())).test_client()
    code, j = get(c, "/api/v1/standings")
    assert code == 503 and not j["ok"] and j["error"]["code"] == "data_unavailable"
    code, j = get(c, "/api/v1/scoreboard")
    assert code == 503 and "data" not in j
    code, j = get(c, "/api/v1/overview")          # composite endpoint degrades per section instead of inventing values
    assert code in (200, 503)
    if code == 200:
        assert j["data"]["today"] is None and j["data"]["missing"]


def test_cache_serves_stale_then_fails_clean():
    from app.services.cache import TTLCache
    c = TTLCache(None)
    assert c.get("k", 0, lambda: 1, "s").status == "fresh"
    def boom():
        raise RuntimeError("down")
    f = c.get("k", 0, boom, "s")
    assert f.status == "stale" and f.data == 1 and "down" in f.error
    with pytest.raises(DataUnavailable):
        c.get("never", 0, boom, "s")
