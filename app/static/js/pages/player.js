import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt, hexA } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, colors } from "../ui/charts.js";
import { pageHead, provenance, notices, face, teamLogo, formChip, sortableTable, stateError, skeletonPage, badge, aiBriefCard, loadBrief, seg, bindSeg, stateEmpty, kpi, animateCounts } from "../ui/components.js";

const roll = (a, n) => a.map((_, i) => { const w = a.slice(Math.max(0, i - n + 1), i + 1); return +(w.reduce((s, x) => s + (x ?? 0), 0) / w.length).toFixed(2); });

export default async function render(ctx) {
  const { root, season } = ctx, charts = [], id = ctx.params.id;
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data: d, meta } = await api(`/players/${id}`, { season }, { signal: ctx.signal });
  const p = d.player, team = d.team_info || store.team(p.team) || {}, f = d.form, s = f?.summary, games = f?.games || [];
  const axes = store.state.meta.radar;
  root.innerHTML = html`<div class="crumbs"><a href="#/players">Player Intelligence</a> ${raw(icon("chevron"))} <span>${p.name}</span></div>
    <section class="hero" style="--team:${team.primary || "var(--accent)"}">${face(p.id, "xl")}
      <div><h1>${p.name}</h1><div class="meta">${teamLogo(team, "sm")}<a class="chip" href="#/teams/${p.team}">${team.name || p.team}</a>${d.bio?.POSITION ? html`<span class="chip">${d.bio.POSITION}</span>` : ""}${d.bio?.HEIGHT ? html`<span class="chip">${d.bio.HEIGHT} · ${d.bio.WEIGHT} lb</span>` : ""}${p.age ? html`<span class="chip">${p.age} yrs</span>` : ""}${p.archetype ? html`<span class="chip accent">${raw(icon("sparkles"))} ${p.archetype}</span>` : ""}${s?.form_label ? formChip(s.form_label) : ""}</div>
        <div class="row" style="margin-top:12px">${provenance(meta)}</div></div>
      <div class="hero-stats">${[["PTS", p.pts], ["REB", p.reb], ["AST", p.ast], ["TS%", p.ts_pct], ["PIE", p.pie]].map(([l, v]) => html`<div class="hero-stat"><b>${fmt.num(v)}</b><span>${l}</span></div>`)}</div></section>
    ${notices(meta)}
    <div class="row wrap" style="margin-bottom:16px"><a class="btn" href="#/compare?a=${p.id}">${raw(icon("users"))} Compare</a><a class="btn" href="#/shots?player=${p.id}">${raw(icon("crosshair"))} Shot analysis</a></div>
    <div class="grid">
      <section class="card s8"><div class="card-h"><h3>Recent form</h3>${seg("metric", [["pts", "Points"], ["reb", "Rebounds"], ["ast", "Assists"]], "pts")}</div><div class="card-b">${games.length >= 3 ? html`<div class="chart h320"><canvas id="form"></canvas></div><div class="legend" style="margin-top:8px"><span><i style="background:${hexA(colors().accent, 0.5)}"></i>Game</span><span><i style="background:${colors().info}"></i>5-game average</span><span><i style="background:${colors().pos}"></i>Exp. weighted avg</span></div>` : stateEmpty("Not enough games yet", "Form analysis needs at least 3 games this season.", "activity")}</div></section>
      <section class="card s4"><div class="card-h"><h3>League percentiles</h3><span class="tiny muted">${p.qualified ? "vs qualified players" : "not qualified"}</span></div><div class="card-b">${p.qualified ? html`<div class="chart h260"><canvas id="radar"></canvas></div>` : stateEmpty("Too few games / minutes", "Percentiles are computed against qualified players only.")}
        ${(p.strengths?.length || p.weaknesses?.length) ? html`<div class="col" style="margin-top:6px">${p.strengths?.length ? html`<div><div class="lbl" style="margin-bottom:6px">Strengths</div><div class="pill-list">${p.strengths.map((x) => html`<span class="chip pos">${x}</span>`)}</div></div>` : ""}${p.weaknesses?.length ? html`<div><div class="lbl" style="margin-bottom:6px">Weaknesses</div><div class="pill-list">${p.weaknesses.map((x) => html`<span class="chip cold">${x}</span>`)}</div></div>` : ""}</div>` : ""}</div></section>
      <section class="card s4"><div class="card-h"><h3>Form analysis</h3>${badge("derived")}</div><div class="card-b">${s ? html`
        <div class="metric"><span>Season avg</span><b>${s.season_avg_pts} pts</b></div><div class="metric"><span>Last 5</span><b>${s.last5_avg_pts} pts</b></div><div class="metric"><span>Last 10</span><b>${s.last10_avg_pts} pts</b></div>
        <div class="metric"><span>Form z-score</span><b>${s.form_z ?? "—"}</b></div><div class="metric"><span>Trend (last 10)</span><b class="${s.trend_slope_pts_per_game > 0 ? "pos" : s.trend_slope_pts_per_game < 0 ? "neg" : ""}">${fmt.signed(s.trend_slope_pts_per_game, 2)} pts/game</b></div>
        <div class="metric"><span>Consistency</span><b>${s.consistency != null ? Math.round(s.consistency * 100) : "—"}/100</b></div><div class="metric"><span>Best game</span><b>${s.best_game.pts} · ${fmt.date(s.best_game.date, { month: "short", day: "numeric" })}</b></div>
        <p class="tiny muted" style="margin:10px 0 0">${s.method}</p>` : stateEmpty("Game log unavailable", "")}</div></section>
      <section class="card s4"><div class="card-h"><h3>Similar players</h3><span class="tiny muted">Cosine similarity · 11 stats</span></div><div class="card-b flush">${d.similar.length ? html`<div class="list">${d.similar.map((x) => html`<a href="#/players/${x.id}"><div class="li">${face(x.id)}<div class="grow"><div class="t">${x.name}</div><div class="s">${x.team} · ${fmt.num(x.pts)}/${fmt.num(x.reb)}/${fmt.num(x.ast)}</div></div><b class="num accent">${fmt.num(x.similarity, 0)}%</b></div></a>`)}</div>` : stateEmpty("Not available", "Similarity needs a qualified player.")}</div></section>
      <section class="s4">${aiBriefCard()}</section>
      <section class="card s12"><div class="card-h"><h3>Game log</h3><span class="tiny muted">${games.length} games this season</span></div><div class="card-b flush" id="log"></div></section></div>`.toString();
  loadBrief(root, api, { type: "player", id, season });
  animateCounts(root);

  // form chart with metric toggle
  const draw = (metric) => {
    const canvas = root.querySelector("#form"); if (!canvas) return;
    const old = charts.find((e) => e.canvas === canvas); if (old) disposeCharts([old]);
    const vals = games.map((g) => g[metric] ?? 0), avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    const ew = []; vals.forEach((v, i) => ew.push(i ? 0.3 * v + 0.7 * ew[i - 1] : v));
    makeChart(canvas, (c) => ({ type: "bar", data: { labels: games.map((g) => fmt.date(g.date, { month: "short", day: "numeric" })), datasets: [
      { type: "line", label: "EWMA", data: ew.map((x) => +x.toFixed(2)), borderColor: c.pos, borderWidth: 2, pointRadius: 0, tension: 0.3, order: 1 },
      { type: "line", label: "5-game avg", data: roll(vals, 5), borderColor: c.info, borderWidth: 2.5, pointRadius: 0, tension: 0.3, order: 2 },
      { label: metric.toUpperCase(), data: vals, backgroundColor: games.map((g) => hexA(c.accent, g.wl === "W" ? 0.55 : 0.28)), borderRadius: 5, order: 3, borderSkipped: false }] },
      options: baseOptions(c, { plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { title: (i) => `${games[i[0].dataIndex].matchup} · ${games[i[0].dataIndex].wl || ""}` } } }, scales: { x: axis(c, { grid: { display: false } }), y: axis(c, { beginAtZero: true }) } }),
      plugins: [{ id: "avgline", afterDatasetsDraw(ch) { const { ctx: g, chartArea: a, scales: { y } } = ch, py = y.getPixelForValue(avg); g.save(); g.strokeStyle = c.text; g.globalAlpha = .5; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(a.left, py); g.lineTo(a.right, py); g.stroke(); g.fillStyle = c.text; g.font = "600 10.5px Inter"; g.fillText(`season avg ${avg.toFixed(1)}`, a.left + 6, py - 6); g.restore(); } }] }), charts);
  };
  if (games.length >= 3) { draw("pts"); ctx.onCleanup(bindSeg(root, "metric", draw)); }

  if (p.qualified) makeChart(root.querySelector("#radar"), (c) => ({ type: "radar", data: { labels: axes.map((a) => a.label.replace(/ \(.*\)/, "")), datasets: [{ data: axes.map((a) => p.percentiles?.[a.key] ?? 0), backgroundColor: hexA(c.accent, 0.22), borderColor: c.accent, borderWidth: 2, pointBackgroundColor: c.accent, pointRadius: 3 }] },
    options: baseOptions(c, { plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { label: (i) => `${fmt.ord(Math.round(i.raw))} percentile` } } }, scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: c.grid }, angleLines: { color: c.grid }, pointLabels: { color: c.text, font: { family: "Inter", size: 10.5 } } } } }) }), charts);

  sortableTable(root.querySelector("#log"), { sortKey: "date", rows: games, maxHeight: 460, columns: [
    { key: "date", label: "Date", render: (g) => fmt.date(g.date) }, { key: "matchup", label: "Matchup", asc: true }, { key: "wl", label: "", render: (g) => html`<span class="chip ${g.wl === "W" ? "pos" : ""}">${g.wl}</span>` },
    { key: "min", label: "MIN", n: true }, { key: "pts", label: "PTS", n: true, render: (g) => html`<b>${g.pts}</b>` }, { key: "reb", label: "REB", n: true }, { key: "ast", label: "AST", n: true }, { key: "stl", label: "STL", n: true }, { key: "blk", label: "BLK", n: true }, { key: "tov", label: "TOV", n: true },
    { key: "fg_pct", label: "FG%", n: true }, { key: "ts_pct", label: "TS%", n: true }, { key: "plus_minus", label: "+/−", n: true, render: (g) => html`<span class="${g.plus_minus > 0 ? "pos" : g.plus_minus < 0 ? "neg" : ""}">${fmt.signed(g.plus_minus, 0)}</span>` }] });
}
