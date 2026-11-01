# CourtVision AI — NBA Live Intelligence & Predictive Analytics

A sports-analytics platform built on Flask + Socket.IO with a framework-free, dual-theme frontend. It combines live scores,
an in-game win-probability model, an explainable pre-game predictor, player/team intelligence, shot analysis and an AI analyst.
(Formerly *NBA-AI / NBA Live Predictor*.)

## Data honesty

Every API response carries a `meta` block, and the UI shows it:

| Label | Meaning |
| --- | --- |
| **Live** | Real-time feed (NBA CDN scoreboard / play-by-play). |
| **Historical** | Official statistics (NBA Stats). |
| **Prediction** | Model output - never a statistic. |
| **Derived** | Computed by this app from real data (Elo, form, power score, archetypes). |
| **Stale** | Upstream failed; the last good copy is shown with its age. |
| **Synthetic** | Only ever used to *train* a model, and always labelled as such. |

If a source is down and nothing is cached the API returns `503 data_unavailable` - **nothing is fabricated or back-filled**.
The 2026-27 season is derived from the calendar (new season label every October); before a season has games the app shows the previous
season's final data with a notice.

## Models

| Model | Trained on | Real-world check |
| --- | --- | --- |
| Pre-game win probability (logistic regression: Elo gap, point differential, last-10 form, rest) | **Real** games, walk-forward | `scripts/train_pregame.py` scores it out-of-sample on the latest full season vs. baselines. Until you run it the UI says *uncalibrated prior*. |
| In-game win probability (PyTorch MLP) | **Synthetic** game states | `scripts/evaluate_real.py` scores it on real play-by-play and fits a held-out Platt recalibration. |
| Shot quality / xFG (XGBoost) | **Synthetic** shots (shipped) or **real** shots (after `evaluate_real.py`) | Time-split evaluation; real-trained model replaces the synthetic one when present. |
| Archetypes / similarity (k-means, cosine) | Real league stats, unsupervised | No labels, so no accuracy metric. |

Explainability: exact Shapley values for the PyTorch model, TreeSHAP (XGBoost `pred_contribs`) for shots, exact linear SHAP for the pre-game model.
The shipped repo previously contained a 2-game backtest in which the win-probability model scored worse than a coin flip; it is kept in
`data/real/sample_backtest_2_games.json` and shown on the Models page with that caveat until a real evaluation exists.

## Troubleshooting NBA data

Run `python scripts/check_sources.py` to see which sources your network can reach. `stats.nba.com` and `cdn.nba.com` are unofficial and are often slow or blocked on some ISPs, campus networks and cloud hosts; try a mobile hotspot or VPN, raise `COURTVISION_HTTP_TIMEOUT`, or set `NBA_PROXY`. If `cdn.nba.com` answers 403 (some networks are blocked), the scoreboard, schedule, box score and play-by-play automatically fall back to the equivalent `stats.nba.com` endpoints for 5 minutes at a time. Failing sources are retried with back-off and the UI shows stale/unavailable states instead of inventing data.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                   # optional
python app.py                                          # http://127.0.0.1:5000
```

Recommended first run (needs internet; takes a few minutes):

```bash
python scripts/train_pregame.py          # fit + validate the pre-game model on real games
python scripts/evaluate_real.py          # score win-prob + shot models on real data, fit recalibration / real shot model
```

### Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask secret. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. Required when `COURTVISION_ENV=production`; a random one is generated per run otherwise. |
| `COURTVISION_DEBUG` | `false` by default. |
| `COURTVISION_HOST` / `COURTVISION_PORT` | Bind address (default `127.0.0.1:5000`). |
| `CORS_ORIGINS` | Comma-separated Socket.IO origins; empty = same-origin only. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional. Enables Gemini-written AI briefings (written strictly from computed facts; key from https://aistudio.google.com/apikey). Without a key a labelled rule-based summary is shown. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Optional alternative provider (Gemini is used first when both are set). |
| `NBA_PROXY`, `COURTVISION_HTTP_TIMEOUT` | Optional outbound proxy and request timeout (default 30 s) for NBA data. |

## Pages

Overview · Live Games · Game Analytics (win-probability timeline, swing plays, runs, turning point, shot map) · Predictions Center
(slate, matchup builder, factor attribution, reliability chart) · Player Intelligence · Player profile · Player Comparison ·
Shot Analysis (zones / heatmap / shots, filters) · Team Analytics · Team profile · Standings & Rankings · Schedule · Models & Evaluation.
Dark and light themes persist in `localStorage`; `Ctrl K` (or `/`) opens global search.

## API (`/api/v1`)

`health`, `meta`, `overview`, `scoreboard?date=`, `schedule?from=&to=&team=&status=`, `games/<id>`, `standings`, `teams`, `teams/<abbr>`,
`players?team=&q=&sort=&order=&limit=&qualified=`, `players/<id>`, `players/compare?a=&b=`, `players/<id>/shots?period=&type=&result=&zone=&dmin=&dmax=&last_n=`,
`predictions/slate?date=`, `predictions/matchup?home=&away=`, `models`, `ai/brief?type=matchup|player|team|game`, `search?q=`, `news`.
All accept `?season=2026-27` where relevant. Socket.IO emits `scoreboard` while clients are connected.
Old `/api/*` paths return a `307` redirect to the matching `/api/v1/*` path (response shape changed to the `{ok, data, meta}` envelope; the hardcoded 2026 playoff-bracket endpoint was removed).

## Project layout

```text
app/
  config.py  main.py                 # env config, app factory, security headers, live loop
  api/routes.py  responses.py        # v1 API, envelope, validation, rate limiting
  models/                            # PyTorch win-prob + XGBoost shot models (+ explainability)
  services/                          # nba_data (all external I/O), cache, team_intel, player_intel, predictor, live (impact analyzer),
                                     # shot_analysis, ai_analyst, evaluation, *_training / *_eval pipelines
  static/ css/ js/ vendor/ fonts/    # design system, router, pages (ES modules, no build step)
data/ synthetic/  real/  models/     # training data | real evaluation data + reports | model artifacts
scripts/                             # train_models, train_pregame, evaluate_real
tests/                               # pytest suite + TEST-ONLY fixtures (never imported by the app)
```

## Demo & screenshots

* `demo/CourtVision-AI-Demo.html` - one self-contained file (open it in a browser, click **Try demo**). Same UI and the same model/analytics code, running on generated demo data (fictional players) with a simulated live game; every screen carries a DEMO banner. Rebuild with `python demo/build_demo.py` (needs Node.js).
* `python scripts/capture_screenshots.py` - with the app running, saves numbered screenshots of every page of **your** instance (`pip install playwright && playwright install chromium`; options `--theme both`, `--url`, `--out`).

## Tests

```bash
pytest -q      # 35 tests, fully offline (uses tests/fakes.py, never real or fabricated data in the app)
python -m tests.serve_fixture   # run the UI against fixtures at :5057 (for development only)
```

## Known limitations

* Live endpoints (`stats.nba.com`, `cdn.nba.com`, ESPN) are unofficial and can throttle or block cloud IPs; the app degrades to cached/stale data and says so.
* Player headshots/logos load from `cdn.nba.com`; offline they are hidden.
* Public data has no defender distance or shot clock, so the synthetic shot model holds them neutral (labelled in the UI).
* Injury impact is an estimate from PIE and minutes, capped at 7 pts.
* Not deployed. Use a production WSGI server and set `COURTVISION_ENV=production` plus a real `SECRET_KEY` before exposing it.
