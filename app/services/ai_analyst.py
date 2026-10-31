"""AI analyst: turns verified analytics into short briefings.

Facts are always computed from real data by deterministic code. If ANTHROPIC_API_KEY is configured, Claude writes the
narrative strictly from those facts; otherwise a rule-based summary is returned and clearly labelled as such.
The model is never asked for statistics, injuries or news - only to phrase the facts it is given.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import requests

from app.config import Config

logger = logging.getLogger("courtvision.ai")
API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SYSTEM = (
    "You are the analyst inside CourtVision AI, an NBA analytics product. Write a sharp briefing of at most 120 words "
    "using ONLY the facts provided. Never invent statistics, injuries, quotes or news. If a fact is marked as a prediction "
    "or estimate, say so. Plain prose, no headings, no bullet characters."
)


def _sign(v: float, nd: int = 1) -> str:
    return f"{v:+.{nd}f}"


# ------------------------------------------------------------------ fact builders (deterministic, real data only)
def facts_matchup(p: dict) -> dict:
    h, a = p["home"], p["away"]
    pick = h if p["pick"] == h["abbr"] else a
    top = [f for f in p["factors"] if f["favors"] != "neutral"][:3]
    bullets = [
        f"PREDICTION: {pick['name']} are favoured with a {p['pick_probability'] * 100:.0f}% win probability "
        f"({h['abbr']} home {p['probabilities']['home'] * 100:.0f}% / {a['abbr']} away {p['probabilities']['away'] * 100:.0f}%). "
        f"Model confidence: {p['confidence']['label']}.",
    ]
    for f in top:
        bullets.append(f"Driver: {f['label']} favours {f['favors']} ({f['contribution_pp']:+.1f} win-prob points).")
    c = p["context"]
    bullets.append(f"Elo: {h['abbr']} {c['elo']['home']:.0f} vs {a['abbr']} {c['elo']['away']:.0f}. "
                   f"Rest days: {h['abbr']} {c['rest_days']['home']}, {a['abbr']} {c['rest_days']['away']}.")
    bullets += p["confidence"]["reasons"][:2]
    if not p["model"]["fitted"]:
        bullets.append("Caveat: the pre-game model uses uncalibrated prior weights.")
    return {"title": f"{a['abbr']} @ {h['abbr']}", "bullets": bullets}


def facts_player(prof: dict) -> dict:
    p, f = prof["player"], prof.get("form") or {}
    s = f.get("summary") or {}
    b = [f"{p['name']} ({p['team']}) averages {p['pts']} pts, {p['reb']} reb, {p['ast']} ast in {p['min']} min over {int(p['gp'])} games "
         f"with {p['ts_pct']}% TS and {p['usg_pct']}% usage."]
    if p.get("archetype"):
        b.append(f"Statistical archetype (k-means cluster): {p['archetype']}.")
    if s.get("form_label"):
        b.append(f"Recent form is {s['form_label']}: last-5 average {s['last5_avg_pts']} pts vs {s['season_avg_pts']} on the season "
                 f"(z = {s['form_z']}).")
    pct = p.get("percentiles") or {}
    ranked = sorted(((v, k) for k, v in pct.items() if v is not None), reverse=True)
    if ranked and p.get("qualified"):
        b.append(f"League percentiles - best: {ranked[0][1]} ({ranked[0][0]:.0f}th); weakest: {ranked[-1][1]} ({ranked[-1][0]:.0f}th).")
    sim = prof.get("similar") or []
    if sim:
        b.append("Most statistically similar players: " + ", ".join(x["name"] for x in sim[:3]) + ".")
    return {"title": p["name"], "bullets": b}


def facts_team(prof: dict) -> dict:
    t = prof["team"]
    b = [f"{t['name']} are {t['w']}-{t['l']} with {t['off_rating']} ORtg, {t['def_rating']} DRtg ({_sign(t['net_rating'])} net) "
         f"and {t['pace']} pace. Elo {t['elo']}."]
    if t.get("net_trend") is not None:
        b.append(f"Last-10 net rating is {_sign(t['net_trend'])} versus their season mark.")
    rr = prof.get("recent_results") or []
    if rr:
        wins = sum(1 for r in rr if r["win"])
        b.append(f"Last {len(rr)} results: {wins}-{len(rr) - wins}.")
    if t.get("power_rank"):
        b.append(f"Power rank #{t['power_rank']} ({t['tier']}), record rank #{t['record_rank']}.")
    return {"title": t["name"], "bullets": b}


def facts_game(d: dict) -> dict:
    g, imp = d["game"] or {}, d.get("impact") or {}
    h, a = d["home"], d["away"]
    b = []
    if d.get("boxscore"):
        hs, as_ = d["boxscore"]["home"]["score"], d["boxscore"]["away"]["score"]
        b.append(f"{d['status'].upper()}: {a['abbr']} {as_}, {h['abbr']} {hs}.")
        for side in ("home", "away"):
            ps = d["boxscore"][side]["players"][:1]
            if ps:
                p = ps[0]
                b.append(f"Top scorer for {d['boxscore'][side]['abbr']}: {p['name']} with {p['pts']} pts, {p['reb']} reb, {p['ast']} ast.")
    s = imp.get("summary") or {}
    if s:
        b.append(f"{s['lead_changes']} lead changes; largest leads {h['abbr']} {s['largest_home_lead']}, {a['abbr']} {s['largest_away_lead']}.")
        if s.get("winner_lowest_win_prob") is not None:
            b.append(f"MODEL ESTIMATE: the winner ({s['winner']}) was as low as {s['winner_lowest_win_prob'] * 100:.0f}% to win at its worst moment.")
    tp = imp.get("turning_point")
    if tp:
        b.append(f"MODEL ESTIMATE: the turning point was a {tp['swing_pp']} point win-probability swing toward {tp['favors']} "
                 f"between Q{tp['start']['period']} {tp['start']['clock']} and Q{tp['end']['period']} {tp['end']['clock']}.")
    for r in (imp.get("runs") or [])[:2]:
        b.append(f"{r['team']} scoring run of {r['points']} points (Q{r['period_start']} {r['clock_start']} to Q{r['period_end']} {r['clock_end']}).")
    for sw in (imp.get("swings") or [])[:2]:
        b.append(f"Key play: {sw['desc']} (Q{sw['period']} {sw['clock']}, {sw['delta_pp']:+.1f} pp for {h['abbr']}).")
    return {"title": f"{a['abbr']} @ {h['abbr']}", "bullets": b}


# ------------------------------------------------------------------ analyst
class AIAnalyst:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict]] = {}

    @property
    def provider(self) -> str | None:
        """Gemini wins when both keys are set; None means rule-based."""
        return "gemini" if Config.GEMINI_API_KEY else "claude" if Config.ANTHROPIC_API_KEY else None

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def brief(self, kind: str, facts: dict) -> dict[str, Any]:
        key = hashlib.sha1(json.dumps([kind, facts], sort_keys=True, default=str).encode()).hexdigest()
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]
        result = None
        if self.provider:
            try:
                result = self._gemini(facts) if self.provider == "gemini" else self._claude(facts)
            except Exception as exc:
                logger.warning("%s brief failed, using rule-based summary: %s", self.provider, str(exc)[:200])
        if result is None:
            result = {"text": " ".join(facts["bullets"]), "generated_by": "rule-based",
                      "note": "Rule-based summary of computed facts. Set GEMINI_API_KEY in .env to enable the AI analyst." if not self.enabled
                      else "AI analyst unavailable right now; showing the rule-based summary."}
        result = {**result, "title": facts["title"], "facts": facts["bullets"]}
        self._cache[key] = (time.time(), result)
        return result

    @staticmethod
    def _gemini(facts: dict) -> dict:
        prompt = "Facts:\n- " + "\n- ".join(facts["bullets"]) + f"\n\nSubject: {facts['title']}"
        r = requests.post(GEMINI_URL.format(model=Config.GEMINI_MODEL), timeout=30,
                          headers={"x-goog-api-key": Config.GEMINI_API_KEY, "content-type": "application/json"},   # key in header, never in the URL/logs
                          json={"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.4}})
        r.raise_for_status()
        cands = r.json().get("candidates") or []
        text = "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])).strip() if cands else ""
        if not text:
            raise ValueError("empty response (blocked or no candidates)")
        return {"text": text, "generated_by": "gemini", "model": Config.GEMINI_MODEL}

    @staticmethod
    def _claude(facts: dict) -> dict:
        r = requests.post(API_URL, timeout=25, headers={
            "x-api-key": Config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": Config.ANTHROPIC_MODEL, "max_tokens": 400, "system": SYSTEM,
                  "messages": [{"role": "user", "content": "Facts:\n- " + "\n- ".join(facts["bullets"]) + f"\n\nSubject: {facts['title']}"}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
        if not text:
            raise ValueError("empty response")
        return {"text": text, "generated_by": "claude", "model": Config.ANTHROPIC_MODEL}
