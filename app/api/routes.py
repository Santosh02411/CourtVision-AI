"""HTTP API (v1). Every response uses the envelope from responses.py; legacy /api/* paths redirect here."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable

from flask import Blueprint, current_app, redirect, request

from app.api.responses import ApiError, RateLimiter, clamp_int, fail, merge_meta, ok
from app.config import Config
from app.models.shot_quality import RealShotModel, ShotQualityModel
from app.models.win_probability import WinProbabilityModel
from app.services import ai_analyst as AI
from app.services import teams as T
from app.services.cache import DataUnavailable, Fetched
from app.services.evaluation import model_cards
from app.services.live import LiveService
from app.services.nba_data import NBAData
from app.services.player_intel import PlayerIntel, RADAR
from app.services.predictor import Predictor
from app.services.shot_analysis import ShotScorer, apply_filters, shot_frame, summarize
from app.services.team_intel import TeamIntel
from app.services.util import num, today_et

logger = logging.getLogger("courtvision.api")
bp = Blueprint("api", __name__, url_prefix="/api/v1")
legacy = Blueprint("legacy", __name__, url_prefix="/api")


class Services:
    """Holds every long-lived service; created once per app."""

    def __init__(self, data: NBAData | None = None) -> None:
        self.data = data or NBAData()
        self.win = WinProbabilityModel()
        self.shot_model = ShotQualityModel()
        self.scorer = ShotScorer(self.shot_model, RealShotModel())
        self.teams = TeamIntel(self.data)
        self.players = PlayerIntel(self.data)
        self.predictor = Predictor()
        self.live = LiveService(self.data, self.win, self.scorer)
        self.analyst = AI.AIAnalyst()
        self.ai_limiter = RateLimiter(per_minute=12)

    # derived data, memoised briefly so page loads don't recompute k-means / Elo replays
    def memo(self, key: str, ttl: int, fn: Callable[[], tuple[Any, list[Fetched]]]) -> tuple[Any, dict]:
        def go() -> dict:
            result, prov = fn()
            return {"result": result, "prov": [p.meta() for p in prov]}
        f = self.data.cache.get(f"memo:{key}", ttl, go, "derived", persist=False)
        return f.data["result"], merge_meta(*f.data["prov"])


def svc() -> Services:
    return current_app.config["SERVICES"]


# ------------------------------------------------------------------ helpers
def _season(s: Services) -> tuple[str, list[str], dict]:
    raw = request.args.get("season")
    if raw:
        season = T.valid_season(raw)
        if not season:
            raise ApiError(f"Invalid season '{raw}'. Use the form 2026-27 (2015-16 or later).", 400, "invalid_season")
        notes: list[str] = []
        if season == T.current_season():
            season, notes, prov = s.teams.resolve_season(season)
        else:
            prov = []
        return season, notes, merge_meta(*prov)
    season, notes, prov = s.teams.resolve_season(None)
    return season, notes, merge_meta(*prov)


def _team_arg(name: str, required: bool = True) -> dict | None:
    team = T.resolve_team(request.args.get(name))
    if not team and (required or request.args.get(name)):
        raise ApiError(f"Unknown or missing team for '{name}'.", 400, "invalid_team")
    return team


def _date_arg(name: str = "date", default: date | None = None) -> date:
    raw = request.args.get(name)
    if not raw:
        return default or today_et()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(f"Invalid {name}. Use YYYY-MM-DD.", 400, "invalid_date")


def _player_id(pid: int) -> int:
    if pid < 1:
        raise ApiError("Invalid player id.", 400, "invalid_player")
    return pid


def _public(p: dict, keep_percentiles: bool = True) -> dict:
    out = {k: v for k, v in p.items() if not k.startswith("_")}
    if not keep_percentiles:
        out.pop("percentiles", None); out.pop("metric_pct", None)
    return out


def team_table(s: Services, season: str) -> tuple[dict, dict]:
    def build():
        table, prov, state = s.teams.table(season)
        ranked = s.teams.power_rankings(table["teams"])
        return {"teams": ranked, "league_avg": table["league_avg"], "_state": None}, prov
    return s.memo(f"teams:{season}", 90, build)


def player_table(s: Services, season: str) -> tuple[dict, dict]:
    return s.memo(f"players:{season}", 120, lambda: s.players.table(season))


def _state(s: Services):
    """Elo / rest / form state as of right now, for the CURRENT season (carries over prior seasons)."""
    cache = s.data.cache
    f = cache.get("memo-state", 120, lambda: s.teams.state(T.current_season())[0], "derived", persist=False)
    return f.data


def _slim_game(g: dict) -> dict:
    return {k: g.get(k) for k in ("game_id", "date", "start_utc", "status", "status_text", "period", "clock", "home", "away",
                                  "arena", "label", "series", "stage", "leaders", "periods", "live_wp", "prediction")}


def _predict_games(s: Services, games: list[dict]) -> list[str]:
    notes = []
    try:
        state = _state(s)
    except DataUnavailable:
        return ["Pre-game predictions unavailable (team history could not be loaded)."]
    for g in games:
        if g["status"] == "final":
            continue
        h, a = T.team_by_id(g["home"]["id"]), T.team_by_id(g["away"]["id"])
        if not h or not a:
            continue
        pr = s.predictor.predict(state, h, a, datetime.strptime(g["date"], "%Y-%m-%d").date() if g["date"] else today_et())
        g["prediction"] = {"home": pr["probabilities"]["home"], "pick": pr["pick"], "confidence": pr["confidence"]["label"],
                           "kind": "prediction", "fitted": pr["model"]["fitted"]}
    return notes


# ------------------------------------------------------------------ meta / health
@bp.get("/health")
def health():
    s = svc()
    return ok({"status": "ok", "version": Config.VERSION, "season": T.current_season(), "ai_analyst": s.analyst.enabled,
               "models": {"win_probability": s.win.metadata(), "shot": s.scorer.label,
                          "pregame": {"fitted": s.predictor.is_fitted}},
               "cache": s.data.probe()}, kind="derived")


@bp.get("/meta")
def meta():
    s = svc()
    return ok({
        "app": {"name": Config.APP_NAME, "tagline": Config.APP_TAGLINE, "version": Config.VERSION},
        "current_season": T.current_season(), "seasons": T.season_options(), "today": today_et().isoformat(),
        "teams": sorted(T.TEAMS.values(), key=lambda t: t["name"]),
        "ai_analyst": {"enabled": s.analyst.enabled, "mode": s.analyst.provider or "rule-based"},
        "labels": {"live": "Live feed", "historical": "Historical statistics", "prediction": "Model prediction",
                   "derived": "Derived analytics", "model": "Model information"},
        "radar": [{"key": k, "label": l} for k, l, _, _ in RADAR],
    }, kind="derived")


# ------------------------------------------------------------------ teams
@bp.get("/teams")
def teams_list():
    s = svc(); season, notes, p0 = _season(s)
    data, prov = team_table(s, season)
    return ok({"teams": data["teams"], "league_avg": data["league_avg"]}, kind="historical", season=season,
              provenance=prov, notes=notes)


@bp.get("/teams/<abbr>")
def team_detail(abbr: str):
    s = svc(); season, notes, _ = _season(s)
    team = T.resolve_team(abbr)
    if not team:
        raise ApiError("Unknown team.", 404, "team_not_found")
    table, prov = team_table(s, season)
    state, _ = s.memo(f"state:{season}", 120, lambda: (lambda st_p: (st_p[0], st_p[1]))(s.teams.state(season)))
    sched = None
    try:
        sched = s.data.schedule().data if season == T.current_season() else None
    except DataUnavailable:
        notes.append("Upcoming schedule unavailable right now.")
    prof = s.teams.profile(table["teams"], state, team, sched)
    players, _ = player_table(s, season)
    prof["roster"] = [_public(p, False) for p in players["players"] if p["team"] == team["abbr"]][:12]
    prof["league_avg"] = table["league_avg"]
    try:
        inj = s.data.injuries()
        prof["injuries"] = [i for i in inj.data if i["team"] == team["abbr"]]
        prof["injuries_meta"] = inj.meta()
    except DataUnavailable:
        prof["injuries"] = None
    return ok(prof, kind="historical", season=season, provenance=prov, notes=notes)


# ------------------------------------------------------------------ players
@bp.get("/players")
def players_list():
    s = svc(); season, notes, _ = _season(s)
    data, prov = player_table(s, season)
    rows = data["players"]
    team = _team_arg("team", required=False)
    if team:
        rows = [r for r in rows if r["team"] == team["abbr"]]
    q = (request.args.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows if q in (r["name"] or "").lower()]
    if request.args.get("qualified", "1") != "0":
        rows = [r for r in rows if r["qualified"]]
    sort = request.args.get("sort", "pie")
    if sort not in {"pts", "reb", "ast", "stl", "blk", "tov", "fg3m", "fg_pct", "fg3_pct", "ft_pct", "ts_pct", "usg_pct", "pie",
                    "net_rating", "min", "gp", "plus_minus", "form_delta", "age", "name"}:
        raise ApiError("Unsupported sort key.", 400, "invalid_sort")
    desc = request.args.get("order", "desc") != "asc"
    rows = sorted(rows, key=lambda r: (r.get(sort) is None, -(r.get(sort) or 0) if desc and sort != "name" else (r.get(sort) or 0)))
    if sort == "name":
        rows = sorted(rows, key=lambda r: r["name"] or "", reverse=desc)
    limit = clamp_int(request.args.get("limit"), 60, 1, 600)
    return ok({"players": [_public(r, False) for r in rows[:limit]], "total": len(rows), "qualification": data["qualification"]},
              kind="historical", season=season, provenance=prov, notes=notes)


@bp.get("/players/compare")
def players_compare():
    s = svc(); season, notes, _ = _season(s)
    ids = [clamp_int(request.args.get(k), 0, 0, 10**9) for k in ("a", "b")]
    if not all(ids) or ids[0] == ids[1]:
        raise ApiError("Provide two different player ids as ?a=&b=.", 400, "invalid_players")
    data, prov = player_table(s, season)
    by_id = {p["id"]: p for p in data["players"]}
    if not all(i in by_id for i in ids):
        raise ApiError("Player not found for this season.", 404, "player_not_found")
    a, b = by_id[ids[0]], by_id[ids[1]]
    cols = [("pts", "PTS", True), ("reb", "REB", True), ("ast", "AST", True), ("stl", "STL", True), ("blk", "BLK", True),
            ("tov", "TOV", False), ("fg_pct", "FG%", True), ("fg3_pct", "3P%", True), ("ft_pct", "FT%", True), ("ts_pct", "TS%", True),
            ("usg_pct", "USG%", True), ("pie", "PIE", True), ("net_rating", "Net Rtg", True), ("min", "MIN", True)]
    metrics = []
    for k, label, hi in cols:
        va, vb = a.get(k), b.get(k)
        edge = None if va is None or vb is None or va == vb else ("a" if (va > vb) == hi else "b")
        metrics.append({"key": k, "label": label, "a": va, "b": vb, "edge": edge})
    logs = {}
    for key, p in (("a", a), ("b", b)):
        try:
            f = s.players.form_analysis(s.data.player_game_log(p["id"], season).data)
            logs[key] = {"games": [{"date": g["date"], "pts": g["pts"], "reb": g["reb"], "ast": g["ast"]} for g in f["games"][-15:]],
                         "summary": f["summary"]}
        except DataUnavailable:
            logs[key] = None
    wins = {"a": sum(1 for m in metrics if m["edge"] == "a"), "b": sum(1 for m in metrics if m["edge"] == "b")}
    return ok({"a": {**_public(a), **s.players.strengths(a)}, "b": {**_public(b), **s.players.strengths(b)},
               "radar_axes": [{"key": k, "label": l} for k, l, _, _ in RADAR], "metrics": metrics, "edges": wins, "recent": logs},
              kind="historical", season=season, provenance=prov, notes=notes)


@bp.get("/players/<int:player_id>")
def player_detail(player_id: int):
    s = svc(); season, notes, _ = _season(s); _player_id(player_id)
    data, prov = player_table(s, season)
    row = next((p for p in data["players"] if p["id"] == player_id), None)
    if not row:
        raise ApiError("Player has no recorded stats for this season.", 404, "player_not_found")
    prof: dict[str, Any] = {"player": {**_public(row), **s.players.strengths(row)},
                            "similar": s.players.similar(data["players"], player_id)}
    provs = [prov]
    try:
        lf = s.data.player_game_log(player_id, season); provs.append(merge_meta(lf))
        prof["form"] = s.players.form_analysis(lf.data)
    except DataUnavailable:
        prof["form"] = None; notes.append("Game log unavailable - form analysis skipped.")
    try:
        info = s.data.player_info(player_id).data
        prof["bio"] = {k: info.get(k.lower()) for k in ("POSITION", "HEIGHT", "WEIGHT", "JERSEY", "COUNTRY", "SCHOOL", "DRAFT_YEAR", "DRAFT_NUMBER", "FROM_YEAR")} if info else None
    except DataUnavailable:
        prof["bio"] = None
    team = T.team_by_abbr(row["team"])
    prof["team_info"] = team
    return ok(prof, kind="historical", season=season, provenance=merge_meta(*[{"sources": [], "status": "fresh"}] + [{"status": p["status"], **(p["sources"][0] if p["sources"] else {})} for p in provs]), notes=notes)


@bp.get("/players/<int:player_id>/shots")
def player_shots(player_id: int):
    s = svc(); _player_id(player_id)
    raw = request.args.get("season")
    season = T.valid_season(raw) if raw else s.teams.resolve_season(None)[0]
    if not season:
        raise ApiError("Invalid season.", 400, "invalid_season")
    periods = [p for p in (clamp_int(x, 0, 0, 10) for x in request.args.get("period", "").split(",") if x) if p]
    shot_type = request.args.get("type")
    if shot_type not in (None, "", "2", "3"):
        raise ApiError("type must be 2 or 3.", 400, "invalid_filter")
    result = request.args.get("result")
    if result not in (None, "", "made", "missed"):
        raise ApiError("result must be made or missed.", 400, "invalid_filter")
    f = s.data.shot_chart(player_id, season)
    df = shot_frame(f.data["shots"])
    df = apply_filters(df, periods=periods or None, shot_type=shot_type, result=result, dmin=num(request.args.get("dmin")),
                       dmax=num(request.args.get("dmax")), zone=request.args.get("zone") or None,
                       last_n=clamp_int(request.args.get("last_n"), 0, 0, 82) or None)
    out = summarize(df, f.data["league_avg"], s.scorer)
    out["total_unfiltered"] = len(f.data["shots"])
    return ok(out, kind="historical", season=season, provenance=merge_meta(f),
              notes=["Expected FG% is a model estimate (see Models page)."] if not out.get("empty") else ["No shots match these filters."])


# ------------------------------------------------------------------ standings / schedule / scoreboard
@bp.get("/standings")
def standings():
    s = svc(); season, notes, _ = _season(s)
    f = s.data.standings(season)
    rows = []
    for r in f.data:
        t = T.team_by_id(r.get("teamid"))
        if not t:
            continue
        rows.append({**{k: t[k] for k in ("id", "abbr", "name", "conference", "division", "primary", "logo")},
                     "w": r.get("wins"), "l": r.get("losses"), "w_pct": r.get("winpct"), "conf_rank": r.get("playoffrank"),
                     "conf_gb": r.get("conferencegamesback"), "home": r.get("home"), "road": r.get("road"), "l10": r.get("l10"),
                     "streak": (r.get("strcurrentstreak") or "").strip(), "conf_record": r.get("conferencerecord"),
                     "ppg": r.get("pointspg"), "opp_ppg": r.get("opppointspg"), "diff": r.get("diffpointspg"),
                     "clinch": (r.get("clinchindicator") or "").strip()})
    east = sorted([r for r in rows if r["conference"] == "East"], key=lambda r: num(r["conf_rank"], 99))
    west = sorted([r for r in rows if r["conference"] == "West"], key=lambda r: num(r["conf_rank"], 99))
    return ok({"east": east, "west": west}, kind="historical", season=season, provenance=merge_meta(f), notes=notes)


@bp.get("/scoreboard")
def scoreboard():
    s = svc(); d = _date_arg()
    games, prov, notes = s.live.games_for_date(d)
    notes += _predict_games(s, games)
    live = sum(1 for g in games if g["status"] == "live")
    return ok({"date": d.isoformat(), "games": [_slim_game(g) for g in games], "live_count": live},
              kind="live" if d == today_et() else "historical", provenance=merge_meta(*prov), notes=notes)


@bp.get("/schedule")
def schedule():
    s = svc()
    f = s.data.schedule()
    team = _team_arg("team", required=False)
    games = f.data
    if team:
        games = [g for g in games if team["abbr"] in (g["home"]["abbr"], g["away"]["abbr"])]
    start = _date_arg("from", today_et() - timedelta(days=7)).isoformat()
    end = _date_arg("to", today_et() + timedelta(days=14)).isoformat()
    status = request.args.get("status")
    games = [g for g in games if start <= g["date"] <= end and (not status or g["status"] == status)]
    games = sorted(games, key=lambda g: (g["date"], g["start_utc"] or ""))[:400]
    notes = _predict_games(s, games)
    return ok({"games": [_slim_game(g) for g in games], "from": start, "to": end, "season": T.current_season()},
              kind="live", season=T.current_season(), provenance=merge_meta(f), notes=notes)


@bp.get("/games/<game_id>")
def game_detail(game_id: str):
    s = svc()
    if not game_id.isalnum() or len(game_id) > 12:
        raise ApiError("Invalid game id.", 400, "invalid_game")
    detail, prov, notes = s.live.game_detail(game_id)
    if detail["status"] == "scheduled":
        try:
            pr = s.predictor.predict(_state(s), detail["home"], detail["away"],
                                     datetime.strptime(detail["game"]["date"], "%Y-%m-%d").date())
            detail["prediction"] = pr
        except (DataUnavailable, TypeError, ValueError):
            detail["prediction"] = None
    return ok(detail, kind="live" if detail["status"] != "final" else "historical", provenance=merge_meta(*prov), notes=notes)


# ------------------------------------------------------------------ predictions
def _matchup(s: Services, home: dict, away: dict, d: date) -> tuple[dict, list[Fetched]]:
    state = _state(s)
    prov = []
    players = injuries = None
    try:
        players = player_table(s, s.teams.resolve_season(None)[0])[0]["players"]
    except DataUnavailable:
        pass
    try:
        inj = s.data.injuries(); prov.append(inj); injuries = inj.data
    except DataUnavailable:
        pass
    h_av = s.predictor.availability(home["abbr"], injuries, players) if injuries is not None else None
    a_av = s.predictor.availability(away["abbr"], injuries, players) if injuries is not None else None
    pr = s.predictor.predict(state, home, away, d, h_av, a_av)
    pr["head_to_head"] = s.predictor.head_to_head(state, home, away)
    return pr, prov


@bp.get("/predictions/matchup")
def prediction_matchup():
    s = svc()
    home, away = _team_arg("home"), _team_arg("away")
    if home["id"] == away["id"]:
        raise ApiError("Pick two different teams.", 400, "invalid_matchup")
    d = _date_arg(default=today_et())
    pr, prov = _matchup(s, home, away, d)
    return ok(pr, kind="prediction", provenance=merge_meta(*prov),
              notes=[] if pr["model"]["fitted"] else ["Pre-game model weights are uncalibrated priors until scripts/train_pregame.py is run."])


@bp.get("/predictions/slate")
def prediction_slate():
    s = svc(); d = _date_arg()
    games, prov, notes = s.live.games_for_date(d)
    out = []
    for g in games:
        h, a = T.team_by_id(g["home"]["id"]), T.team_by_id(g["away"]["id"])
        if not h or not a:
            continue
        entry = {"game": _slim_game(g)}
        if g["status"] != "final":
            pr, p2 = _matchup(s, h, a, d)
            prov += p2
            entry["prediction"] = {k: pr[k] for k in ("probabilities", "pick", "pick_probability", "implied_spread", "confidence", "baseline_probability")}
            entry["prediction"]["top_factors"] = pr["factors"][:3]
        out.append(entry)
    return ok({"date": d.isoformat(), "games": out}, kind="prediction", provenance=merge_meta(*prov), notes=notes)


@bp.get("/models")
def models():
    s = svc()
    return ok(model_cards(s.predictor, s.win, s.shot_model, s.scorer), kind="model")


# ------------------------------------------------------------------ AI analyst
@bp.get("/ai/brief")
def ai_brief():
    s = svc()
    if not s.ai_limiter.allow(request.remote_addr or "anon"):
        raise ApiError("Too many AI briefings - try again in a minute.", 429, "rate_limited")
    kind = request.args.get("type")
    if kind == "matchup":
        home, away = _team_arg("home"), _team_arg("away")
        pr, _ = _matchup(s, home, away, _date_arg(default=today_et()))
        facts = AI.facts_matchup(pr)
    elif kind == "player":
        season, _, _ = _season(s)
        pid = clamp_int(request.args.get("id"), 0, 0, 10**9)
        data, _ = player_table(s, season)
        row = next((p for p in data["players"] if p["id"] == pid), None)
        if not row:
            raise ApiError("Player not found.", 404, "player_not_found")
        try:
            form = s.players.form_analysis(s.data.player_game_log(pid, season).data)
        except DataUnavailable:
            form = None
        facts = AI.facts_player({"player": row, "form": form, "similar": s.players.similar(data["players"], pid)})
    elif kind == "team":
        season, _, _ = _season(s)
        team = _team_arg("id")
        table, _ = team_table(s, season)
        state, _ = s.memo(f"state:{season}", 120, lambda: (lambda st_p: (st_p[0], st_p[1]))(s.teams.state(season)))
        facts = AI.facts_team(s.teams.profile(table["teams"], state, team, None) | {})
    elif kind == "game":
        gid = request.args.get("id", "")
        if not gid.isalnum():
            raise ApiError("Invalid game id.", 400, "invalid_game")
        detail, _, _ = s.live.game_detail(gid)
        facts = AI.facts_game(detail)
    else:
        raise ApiError("type must be one of matchup, player, team, game.", 400, "invalid_type")
    return ok(s.analyst.brief(kind, facts), kind="derived")


# ------------------------------------------------------------------ search / news / overview
@bp.get("/search")
def search():
    s = svc()
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return ok({"teams": [], "players": []}, kind="derived")
    teams_ = [t for t in T.TEAMS.values() if q in t["name"].lower() or q == t["abbr"].lower()][:5]
    players_: list[dict] = []
    try:
        season, _, _ = _season(s)
        data, _ = player_table(s, season)
        players_ = [{"id": p["id"], "name": p["name"], "team": p["team"], "pts": p["pts"], "headshot": p["headshot"]}
                    for p in data["players"] if q in (p["name"] or "").lower()][:8]
    except (DataUnavailable, ApiError):
        pass
    return ok({"teams": teams_, "players": players_}, kind="derived")


@bp.get("/news")
def news():
    s = svc()
    f = s.data.news()
    return ok({"articles": f.data}, kind="live", provenance=merge_meta(f), notes=["Headlines are context only and are not used in predictions."])


@bp.get("/overview")
def overview():
    s = svc(); season, notes, _ = _season(s)
    out: dict[str, Any] = {}
    missing: list[str] = []
    provs: list[dict] = []

    def section(name: str, fn: Callable[[], Any]) -> None:
        try:
            out[name] = fn()
        except DataUnavailable as exc:
            out[name] = None; missing.append(f"{name}: {exc.reason or 'unavailable'}")

    def todays():
        games, prov, n = s.live.games_for_date(today_et())
        notes.extend(n); _predict_games(s, games); provs.extend(p.meta() for p in prov)
        return [_slim_game(g) for g in games]

    def teams_():
        data, prov = team_table(s, season); provs.extend(prov["sources"])
        return {"power_rankings": data["teams"][:12], "all": data["teams"], "league_avg": data["league_avg"]}

    def players_():
        data, prov = player_table(s, season); provs.extend(prov["sources"])
        qual = [p for p in data["players"] if p["qualified"]]
        leaders = {k: [_public(p, False) for p in sorted(qual, key=lambda p: -(p[k] or 0))[:5]] for k in ("pts", "reb", "ast", "stl", "blk")}
        hot = [_public(p, False) for p in sorted([p for p in qual if p.get("form_delta") is not None], key=lambda p: -p["form_delta"])[:5]]
        return {"featured": [_public(p, False) for p in qual[:6]], "leaders": leaders, "hot": hot, "qualification": data["qualification"]}

    def sched():
        f = s.data.schedule(); provs.append(f.meta())
        today = today_et().isoformat()
        done = sorted([g for g in f.data if g["status"] == "final"], key=lambda g: (g["date"], g["start_utc"] or ""), reverse=True)[:8]
        nxt = sorted([g for g in f.data if g["status"] == "scheduled" and g["date"] >= today], key=lambda g: (g["date"], g["start_utc"] or ""))[:8]
        _predict_games(s, nxt)
        return {"recent": [_slim_game(g) for g in done], "upcoming": [_slim_game(g) for g in nxt]}

    section("today", todays); section("teams", teams_); section("players", players_); section("schedule", sched)

    feed = []
    for g in (out.get("today") or []):
        if g["status"] == "live":
            feed.append({"type": "live", "kind": "live", "text": f"{g['away']['abbr']} {g['away']['score']} - {g['home']['abbr']} {g['home']['score']}  ·  {g['status_text']}", "game_id": g["game_id"]})
    for g in ((out.get("schedule") or {}).get("recent") or [])[:4]:
        feed.append({"type": "final", "kind": "historical", "text": f"Final: {g['away']['abbr']} {g['away']['score']} - {g['home']['abbr']} {g['home']['score']}", "game_id": g["game_id"]})
    for p in ((out.get("players") or {}).get("hot") or [])[:3]:
        feed.append({"type": "form", "kind": "derived", "text": f"{p['name']} scoring {p['form_delta']:+.1f} pts vs season average over the last 10 games", "player_id": p["id"]})
    movers = sorted([t for t in ((out.get("teams") or {}).get("all") or []) if t.get("net_trend") is not None], key=lambda t: -abs(t["net_trend"]))[:2]
    for t in movers:
        feed.append({"type": "trend", "kind": "derived", "text": f"{t['name']} last-10 net rating {t['net_trend']:+.1f} vs season", "team": t["abbr"]})
    out["activity"] = feed
    out["missing"] = missing
    status = "stale" if any(p.get("status") == "stale" for p in provs) else "fresh"
    return ok(out, kind="live", season=season, provenance={"sources": provs, "status": status}, notes=notes + missing)


# ------------------------------------------------------------------ errors + legacy aliases
@bp.errorhandler(ApiError)
def _api_error(e: ApiError):
    return fail(e.message, e.status, e.code, e.meta)


@bp.errorhandler(DataUnavailable)
def _unavailable(e: DataUnavailable):
    return fail(f"{e.source} is unavailable and no cached copy exists yet. {e.reason}".strip(), 503, "data_unavailable",
                {"status": "unavailable", "source": e.source})


@bp.errorhandler(Exception)
def _unexpected(e: Exception):
    logger.exception("unhandled API error")
    return fail("Unexpected server error.", 500, "internal_error")


_LEGACY = {
    "standings": "standings", "schedule": "schedule", "scoreboard": "scoreboard", "power-rankings": "teams", "players": "players",
    "teams": "teams", "game-prediction": "predictions/matchup", "model-performance": "models", "shot-quality": "models",
    "prediction": "scoreboard", "news": "news", "analytics": "overview", "head-to-head": "predictions/matchup", "table": "standings",
}


@legacy.get("/<name>")
def legacy_redirect(name: str):
    target = _LEGACY.get(name)
    if not target:
        return fail("Unknown endpoint. See /api/v1.", 404, "not_found")
    qs = request.query_string.decode()
    resp = redirect(f"/api/v1/{target}" + (f"?{qs}" if qs else ""), code=307)
    resp.headers["Deprecation"] = "true"
    return resp


@legacy.get("/players/<int:pid>/game-log")
def legacy_gamelog(pid: int):
    return redirect(f"/api/v1/players/{pid}", code=307)


@legacy.get("/players/<int:pid>/shot-chart")
def legacy_shotchart(pid: int):
    qs = request.query_string.decode()
    return redirect(f"/api/v1/players/{pid}/shots" + (f"?{qs}" if qs else ""), code=307)
