import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions } from "../ui/charts.js";
import { pageHead, provenance, notices, teamLogo, skeletonPage, skel, stateEmpty, stateError, badge, aiBriefCard, loadBrief, confidenceMeter, bindTips, notice } from "../ui/components.js";
import { predictionPanel, animateGauges } from "../ui/predviz.js";
import { setQuery } from "../core/router.js";

export default async function render(ctx) {
  const { root } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  let date = ctx.query.date || store.state.today, home = ctx.query.home || "", away = ctx.query.away || "";
  const teams = store.state.teams;
  const opts = (sel) => teams.map((t) => html`<option value="${t.abbr}" ${t.abbr === sel ? "selected" : ""}>${t.name}</option>`);
  root.innerHTML = pageHead({ title: "Predictions Center", sub: "Pre-game win probabilities with factor-by-factor explanations. Everything on this page is a model prediction, not a live or historical statistic.", right: badge("prediction") }).toString() + html`
    <div class="toolbar"><div class="field"><label>Slate date</label><div class="row gap-6"><button class="btn sm" id="prev" aria-label="Previous day">${raw(icon("left"))}</button><input type="date" class="input" id="date" value="${date}"><button class="btn sm" id="next" aria-label="Next day">${raw(icon("chevron"))}</button></div></div>
      <div class="grow"></div><div class="field"><label for="away">Matchup builder · away</label><select id="away" class="input"><option value="">Select team</option>${opts(away)}</select></div><div class="field"><label for="home">home</label><select id="home" class="input"><option value="">Select team</option>${opts(home)}</select></div><button class="btn primary" id="go">${raw(icon("target"))} Predict</button></div>
    <div id="notes"></div>
    <div class="grid" style="align-items:start"><section class="card s4"><div class="card-h"><h3>Slate</h3><span id="prov"></span></div><div class="card-b flush" id="slate">${skel(260, "100%", 0)}</div></section>
      <div class="s8" id="detail"></div></div>
    <section class="card" style="margin-top:16px"><div class="card-h"><h3>Model reliability</h3><a class="btn sm" href="#/models">All models</a></div><div class="card-b" id="rel">${skel(160)}</div></section>`.toString();
  const $ = (s) => root.querySelector(s), detail = $("#detail");

  async function show(h, a) {
    home = h; away = a; $("#home").value = h; $("#away").value = a; setQuery({ home: h, away: a, date });
    if (!h || !a) { detail.innerHTML = html`<div class="card">${stateEmpty("Pick a game", "Choose a game from the slate or build a matchup with the selectors above.", "target")}</div>`.toString(); return; }
    if (h === a) { detail.innerHTML = notice("Pick two different teams.", "err").toString(); return; }
    detail.innerHTML = `<div class="card"><div class="card-b">${skel(240)}</div></div>`; disposeCharts(charts);
    try {
      const { data: pr, meta } = await api("/predictions/matchup", { home: h, away: a, date }, { signal: ctx.signal });
      detail.innerHTML = html`<div class="row between wrap" style="margin-bottom:12px"><div class="row" style="gap:14px"><div class="row gap-6">${teamLogo(pr.away, "lg")}<b style="font-size:18px">${pr.away.name}</b></div><span class="muted">at</span><div class="row gap-6">${teamLogo(pr.home, "lg")}<b style="font-size:18px">${pr.home.name}</b></div></div>${provenance(meta)}</div>${notices(meta)}${predictionPanel(pr)}<div style="margin-top:16px">${aiBriefCard()}</div>`.toString();
      animateGauges(detail); bindTips(detail); loadBrief(detail, api, { type: "matchup", home: h, away: a, date });
    } catch (e) { if (e.name !== "AbortError") detail.innerHTML = stateError(e).toString(); }
  }
  const loadSlate = async () => {
    try {
      const { data, meta } = await api("/predictions/slate", { date }, { signal: ctx.signal });
      $("#notes").innerHTML = notices(meta).toString();
      $("#slate").innerHTML = data.games.length ? `<div class="list">${data.games.map(({ game: g, prediction: p }) => { const h = store.team(g.home.id), a = store.team(g.away.id);
        return html`<a href="javascript:void 0" data-h="${g.home.abbr}" data-a="${g.away.abbr}"><div class="li">${teamLogo(a, "sm")}<div class="grow"><div class="t">${g.away.abbr} @ ${g.home.abbr}</div><div class="s">${p ? `${p.pick} ${fmt.prob(p.pick_probability)} · ${p.confidence.label}` : `Final ${g.away.score}–${g.home.score}`}</div></div>${p ? html`<div style="width:80px">${(() => { const wp = p.probabilities.home; return html`<div class="wpbar" style="margin:0"><i style="width:${(1 - wp) * 100}%;background:${a.primary}"></i><i style="width:${wp * 100}%;background:${h.primary}"></i></div>`; })()}</div>` : badge("final")}</div></a>`; }).join("")}</div>` : stateEmpty("No games this day", "Pick another date or use the matchup builder.", "calendar").toString();
      $("#prov").innerHTML = provenance(meta).toString();
      $("#slate").querySelectorAll("a[data-h]").forEach((el) => el.addEventListener("click", (e) => { e.preventDefault(); show(el.dataset.h, el.dataset.a); }));
      if (!home && data.games.find((x) => x.prediction)) { const g = data.games.find((x) => x.prediction).game; show(g.home.abbr, g.away.abbr); }
    } catch (e) { if (e.name !== "AbortError") $("#slate").innerHTML = stateError(e).toString(); }
  };
  $("#date").addEventListener("change", (e) => { if (e.target.value) { date = e.target.value; loadSlate(); } });
  $("#prev").addEventListener("click", () => { date = fmt.addDays(date, -1); $("#date").value = date; loadSlate(); }); $("#next").addEventListener("click", () => { date = fmt.addDays(date, 1); $("#date").value = date; loadSlate(); });
  $("#go").addEventListener("click", () => show($("#home").value, $("#away").value));
  if (home && away) show(home, away); else show("", "");
  loadSlate();

  try {
    const { data } = await api("/models", {}, { signal: ctx.signal }); const c = data.cards.find((x) => x.id === "pregame"), ev = c.real_evaluation;
    if (!ev) { $("#rel").innerHTML = notice(raw("The pre-game model has not been fitted and validated on real results yet, so no reliability numbers exist. Run <code>python scripts/train_pregame.py</code> to fit and score it on real games."), "warn").toString(); return; }
    $("#rel").innerHTML = html`<div class="grid"><div class="s4"><div class="metric"><span>Test season</span><b>${ev.test_season} (${ev.test_games} games)</b></div><div class="metric"><span>Accuracy</span><b>${fmt.pct(ev.accuracy * 100)}</b></div><div class="metric"><span>Always pick home</span><b>${fmt.pct(ev.baselines.always_home_accuracy * 100)}</b></div><div class="metric"><span>Elo only</span><b>${fmt.pct(ev.baselines.elo_only_accuracy * 100)}</b></div><div class="metric"><span>Log loss / Brier</span><b>${ev.log_loss} / ${ev.brier}</b></div><p class="tiny muted">${c.note}</p></div><div class="s8"><div class="chart h220"><canvas id="cal"></canvas></div><div class="tiny muted center">When the model said X% for the home team, how often did the home team win? Closer to the diagonal = better calibrated.</div></div></div>`.toString();
    makeChart($("#cal"), (cl) => ({ type: "scatter", data: { datasets: [{ type: "line", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: cl.border, borderDash: [5, 5], pointRadius: 0 }, { data: ev.calibration.map((b) => ({ x: b.predicted, y: b.actual, n: b.n })), backgroundColor: cl.accent, pointRadius: ev.calibration.map((b) => 4 + Math.sqrt(b.n) / 3), showLine: true, borderColor: cl.accent, borderWidth: 2 }] }, options: baseOptions(cl, { plugins: { legend: { display: false }, tooltip: { ...baseOptions(cl).plugins.tooltip, callbacks: { label: (i) => `Predicted ${fmt.prob(i.raw.x)} → actual ${fmt.prob(i.raw.y)} (${i.raw.n ?? ""} games)` } } }, scales: { x: axis(cl, { min: 0, max: 1, title: { display: true, text: "Predicted home win %", color: cl.text }, ticks: { callback: (v) => `${v * 100}%` } }), y: axis(cl, { min: 0, max: 1, title: { display: true, text: "Actual home win %", color: cl.text }, ticks: { callback: (v) => `${v * 100}%` } }) } }) }), charts);
  } catch (e) { if (e.name !== "AbortError") $("#rel").innerHTML = stateError(e).toString(); }
}
