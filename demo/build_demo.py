"""Build demo/CourtVision-AI-Demo.html - ONE self-contained file with the full UI and demo data.

    python demo/build_demo.py          # needs Node.js (npm installs esbuild locally into demo/.build)

The data is a snapshot of this app's real backend (models, analytics, explainability) run on the TEST fixtures in tests/fakes.py:
fictional players, generated numbers. The demo says so on its landing page and in a banner on every screen.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ["COURTVISION_DISK_CACHE"] = "false"

import numpy as np  # noqa: E402

import app.api.routes as routes  # noqa: E402
import app.main as main  # noqa: E402
from app.services import teams as T  # noqa: E402
from app.services.shot_analysis import ZONE_ORDER, shot_frame  # noqa: E402
from tests.fakes import TODAY, FakeNBAData  # noqa: E402

routes.today_et = lambda: TODAY
main.today_et = lambda: TODAY


def snapshot() -> dict:
    svc = routes.Services(data=FakeNBAData())
    svc.ai_limiter.per_minute = 10**9
    c = main.create_app(services=svc).test_client()

    def get(path: str):
        r = c.get(path)
        j = r.get_json()
        assert j and j.get("ok"), (path, j)
        return j["data"]

    season = T.current_season(TODAY)
    D: dict = {"season": season, "today": TODAY.isoformat()}
    D["meta"] = get("/api/v1/meta") | {"seasons": [season], "ai_analyst": {"enabled": False, "mode": "rule-based"}}
    D["teamsByAbbr"] = {t["abbr"]: t for t in D["meta"]["teams"]}
    abbrs = sorted(D["teamsByAbbr"])
    dates = [(TODAY + timedelta(days=k)).isoformat() for k in range(-6, 8)]

    D["overview"] = get("/api/v1/overview")
    D["teams"], D["standings"], D["models"] = get("/api/v1/teams"), get("/api/v1/standings"), get("/api/v1/models")
    D["news"] = {"articles": [{"headline": h, "description": "", "published": TODAY.isoformat(), "url": None, "image": None, "source": "Demo"} for h in
                              ("Demo headline: headlines are optional context in the real app and never feed a model", "Demo headline: live news comes from ESPN's public feed when you run the real app")]}
    D["schedule"] = get("/api/v1/schedule?from=2026-10-20&to=2026-12-01")["games"]
    D["scoreboard"] = {d: get(f"/api/v1/scoreboard?date={d}") for d in dates}
    D["slates"] = {d: get(f"/api/v1/predictions/slate?date={d}") for d in dates}
    D["liveGame"] = next((g for g in D["schedule"] if g["status"] == "live"), None)

    D["games"] = {g["game_id"]: get(f"/api/v1/games/{g['game_id']}") for g in D["schedule"]}
    D["teamDetail"] = {a: get(f"/api/v1/teams/{a}") for a in abbrs}

    pl = get("/api/v1/players?limit=600&qualified=0")
    D["playerRows"], D["qualification"] = pl["players"], pl["qualification"]
    D["profiles"] = {str(p["id"]): get(f"/api/v1/players/{p['id']}") for p in pl["players"]}

    # raw shots with model xFG (filtered/aggregated in the browser exactly like the server does)
    D["zones"] = ZONE_ORDER
    D["shots"] = {}
    for p in pl["players"]:
        f = svc.data.shot_chart(p["id"], season)
        df = shot_frame(f.data["shots"])
        df["xfg"] = svc.scorer.score(df)
        order = df[["game_id", "game_date"]].drop_duplicates().sort_values("game_date", ascending=False)["game_id"].tolist()
        rank = {g: i for i, g in enumerate(order)}
        D["shots"][str(p["id"])] = {"s": [[int(r.loc_x), int(r.loc_y), int(r.made), round(float(r.distance), 1), int(r.period), round(float(r.xfg), 3), int(r.is_three),
                                           ZONE_ORDER.index(r.zone) if r.zone in ZONE_ORDER else 6, rank[r.game_id]] for r in df.itertuples()]}
    D["leagueAvg"] = svc.data.shot_chart(pl["players"][0]["id"], season).data["league_avg"]
    D["shotModel"] = get(f"/api/v1/players/{pl['players'][0]['id']}/shots")["model"]

    # all 870 ordered matchups + briefs
    D["matchups"], D["briefs"] = {}, {}
    for h in abbrs:
        for a in abbrs:
            if h == a:
                continue
            m = get(f"/api/v1/predictions/matchup?home={h}&away={a}&date={TODAY}")
            D["matchModel"] = m.pop("model")
            m["home"], m["away"] = h, a
            D["matchups"][f"{h}-{a}"] = m
            D["briefs"][f"m:{h}-{a}"] = get(f"/api/v1/ai/brief?type=matchup&home={h}&away={a}")
    for p in pl["players"]:
        D["briefs"][f"p:{p['id']}"] = get(f"/api/v1/ai/brief?type=player&id={p['id']}")
    for a in abbrs:
        D["briefs"][f"t:{a}"] = get(f"/api/v1/ai/brief?type=team&id={a}")
    for g in D["schedule"]:
        if g["status"] != "scheduled":
            D["briefs"][f"g:{g['game_id']}"] = get(f"/api/v1/ai/brief?type=game&id={g['game_id']}")

    # real model's live win-probability surface, used by the simulated live game
    diffs, trs = list(range(-40, 41, 2)), list(range(0, 2881, 120))
    rows = [{"score_diff": d, "time_remaining": t, "home_possession": 0.5, "home_fouls": 3, "away_fouls": 3, "shot_quality": 0.45} for d in diffs for t in trs]
    flat = svc.win.predict_batch(rows)
    D["wpGrid"] = {"diffs": diffs, "dstep": 2, "trs": trs, "tstep": 120, "values": [flat[i * len(trs):(i + 1) * len(trs)] for i in range(len(diffs))]}
    return D


def esbuild_bundle(tmp: Path) -> str:
    build = HERE / ".build"
    build.mkdir(exist_ok=True)
    env = os.environ.copy()
    if os.environ.get("NPM_HOME"):
        env["HOME"] = os.environ["NPM_HOME"]
    if not (build / "node_modules" / "esbuild").exists():
        subprocess.run(["npm", "install", "--prefix", str(build), "esbuild", "--silent", "--no-audit", "--no-fund"], check=True, env=env, shell=(os.name == "nt"))
    src = tmp / "src"
    shutil.copytree(ROOT / "app" / "static" / "js", src)
    shutil.copy(HERE / "demo_api.js", src / "core" / "api.js")        # swap the real API client for the demo one
    out = tmp / "bundle.js"
    exe = build / "node_modules" / ".bin" / ("esbuild.cmd" if os.name == "nt" else "esbuild")
    subprocess.run([str(exe), str(src / "main.js"), "--bundle", "--format=iife", "--minify", "--target=es2020", f"--outfile={out}", "--log-level=warning"], check=True, env=env)
    return out.read_text(encoding="utf-8")


def assemble(D: dict, js: str) -> str:
    static = ROOT / "app" / "static"
    font = base64.b64encode((static / "fonts" / "inter-latin.woff2").read_bytes()).decode()
    css = (static / "css" / "tokens.css").read_text().replace('url("../fonts/inter-latin.woff2")', f'url("data:font/woff2;base64,{font}")')
    css += (static / "css" / "app.css").read_text() + (HERE / "demo.css").read_text()
    chart = (static / "vendor" / "chart.umd.js").read_text(encoding="utf-8")
    icon = (static / "favicon.svg").read_text()
    theme_init = (static / "js" / "theme-init.js").read_text()

    tpl = (ROOT / "app" / "templates" / "index.html").read_text()
    shell = re.search(r"<body>(.*?)<script src", tpl, re.S).group(1)
    for k, v in {"app_name": "CourtVision AI", "tagline": "NBA Live Intelligence & Predictive Analytics", "version": "demo", "season": D["season"]}.items():
        shell = shell.replace("{{ %s }}" % k, v)
    shell = shell.replace('<div class="app" id="app">', '<div class="app" id="app" hidden>')
    shell = shell.replace('<div class="main-col">', '<div class="main-col"><div class="demo-banner"><span><b>DEMO MODE</b> · fictional players &amp; generated numbers · simulated live game · not real NBA data</span><button id="exit-demo">Exit demo</button></div>', 1)

    features = [("Overview", "Scores, power rankings, league landscape, hot players"), ("Live Games", "Scoreboard with a simulated live game updating in real time"), ("Game Analytics", "Win-probability timeline, swing plays, runs, turning point"),
                ("Predictions", "Explainable pre-game odds for all 870 matchups"), ("Player Intelligence", "Sortable tables, form, archetypes, usage vs efficiency"), ("Compare", "Radar and metric comparison for any two players"),
                ("Shot Analysis", "Zones, heatmap, shots; filters by period, type, distance"), ("Team Analytics", "Ratings, pace, Elo, trends and team profiles"), ("Standings & Rankings", "Standings, power ranking, Elo"),
                ("Schedule", "Weekly schedule with model picks"), ("Models & Evaluation", "What each model is and how it was tested"), ("AI Analyst", "Briefings written from verified facts"),
                ("Dark & light themes", "Plus global search with Ctrl K")]
    landing = f"""<div id="landing"><div class="land">
      <svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="var(--accent)"/><path d="M5.5 16C9 9.8 23 9.8 26.5 16 23 22.2 9 22.2 5.5 16Z" fill="none" stroke="#0b0b0c" stroke-width="2" stroke-linejoin="round"/><circle cx="16" cy="16" r="4.3" fill="#0b0b0c"/><path d="M16 11.7v8.6M11.7 16h8.6" stroke="var(--accent)" stroke-width="1.2"/></svg>
      <h1>CourtVision <i>AI</i></h1><p class="sub">NBA live intelligence &amp; predictive analytics. Explore every feature with built-in demo data - no server, no account, no internet needed.</p>
      <button class="try" id="try-demo">Try demo <span aria-hidden="true">→</span></button>
      <div class="feat">{''.join(f'<div><b>{a}</b><span>{b}</span></div>' for a, b in features)}</div>
      <p class="disclaimer">Demo data is generated for illustration: players are fictional and the numbers are not real NBA statistics. Predictions, explanations and charts are produced by the app's real models and analytics code running on that data. Team logos load from the NBA CDN when online and fall back to badges offline.</p>
    </div></div>"""

    boot = """
document.getElementById('try-demo').addEventListener('click', async function () {
  var btn = this; btn.disabled = true; btn.firstChild.textContent = 'Loading demo data… ';
  try {
    if (typeof DecompressionStream === 'undefined') throw new Error('This browser is too old for the demo (needs a 2023+ Chrome, Edge, Firefox or Safari).');
    var b64 = document.getElementById('cv-data').textContent.trim(), bin = Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); });
    var text = await new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
    window.__CV_DATA = JSON.parse(text);
    document.getElementById('landing').hidden = true; document.getElementById('app').hidden = false; document.body.classList.add('demo');
    location.hash = '#/overview'; window.__cvStart();
  } catch (e) { btn.disabled = false; btn.firstChild.textContent = 'Try demo '; alert(e.message || e); }
});
document.addEventListener('click', function (e) { if (e.target && e.target.id === 'exit-demo') { location.hash = ''; location.reload(); } });
"""
    blob = base64.b64encode(gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 9)).decode()
    safe = lambda s: s.replace("</script", "<\\/script")
    return f"""<!doctype html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>CourtVision AI - Demo</title><meta name="theme-color" content="#07080a" id="meta-theme">
<link rel="icon" href="data:image/svg+xml;base64,{base64.b64encode(icon.encode()).decode()}">
<style>{css}</style><script>{theme_init}</script></head>
<body>{landing}{shell}
<script type="text/plain" id="cv-data">{blob}</script>
<script>{safe(chart)}</script>
<script>window.__CV_MANUAL_BOOT = true; window.__CV_POLL_MS = 6000;</script>
<script>{safe(js)}</script>
<script>{boot}</script>
</body></html>"""


def main_() -> None:
    cache = HERE / ".build" / "snapshot.json"
    if "--reuse" in sys.argv and cache.exists():
        D = json.loads(cache.read_text())
    else:
        print("snapshotting backend output ...")
        D = snapshot()
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(D, separators=(",", ":")))
    with tempfile.TemporaryDirectory() as t:
        print("bundling frontend ...")
        js = esbuild_bundle(Path(t))
    html = assemble(D, js)
    out = HERE / "CourtVision-AI-Demo.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB; {len(D['matchups'])} matchups, {len(D['profiles'])} players, {len(D['games'])} games)")


if __name__ == "__main__":
    main_()
