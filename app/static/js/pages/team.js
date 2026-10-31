import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt, hexA } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, colors } from "../ui/charts.js";
import { pageHead, provenance, notices, teamLogo, face, sortableTable, skeletonPage, stateEmpty, aiBriefCard, loadBrief, badge, gameCard, formChip } from "../ui/components.js";

export default async function render(ctx) {
  const { root, season } = ctx, charts = [], abbr = ctx.params.abbr;
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data: d, meta } = await api(`/teams/${abbr}`, { season }, { signal: ctx.signal });
  const t = d.team, avg = d.league_avg;
  const factors = [["efg_pct", "eFG%", false], ["tov_pct", "Turnover %", true], ["oreb_pct", "Off. rebound %", false], ["ts_pct", "True shooting %", false], ["pace", "Pace", false]];
  root.innerHTML = html`<div class="crumbs"><a href="#/teams">Team Analytics</a> ${raw(icon("chevron"))} <span>${t.name}</span></div>
    <section class="hero" style="--team:${t.primary}">${teamLogo(t, "xl")}<div><h1>${t.name}</h1><div class="meta"><span class="chip">${t.conference}ern · ${t.division}</span><span class="chip accent">Power #${t.power_rank} · ${t.tier}</span><span class="chip">Conf. rank ${t.conf_rank ?? "—"}</span>${t.streak ? html`<span class="chip">${t.streak}</span>` : ""}${t.last10 ? html`<span class="chip">L10 ${t.last10}</span>` : ""}</div><div class="row" style="margin-top:12px">${provenance(meta)}</div></div>
      <div class="hero-stats">${[["Record", `${t.w}-${t.l}`], ["ORtg", fmt.num(t.off_rating)], ["DRtg", fmt.num(t.def_rating)], ["Net", fmt.signed(t.net_rating)], ["Elo", fmt.num(t.elo, 0)]].map(([l, v]) => html`<div class="hero-stat"><b>${v}</b><span>${l}</span></div>`)}</div></section>
    ${notices(meta)}
    <div class="grid">
      <section class="card s6"><div class="card-h"><h3>Elo rating</h3><span class="tiny muted">538 method · carries over from prior seasons</span></div><div class="card-b">${d.elo_history.length > 1 ? html`<div class="chart h260"><canvas id="elo"></canvas></div>` : stateEmpty("No games yet", "Elo path appears after the first games.", "trend")}</div></section>
      <section class="card s6"><div class="card-h"><h3>Rolling 10-game margin</h3></div><div class="card-b">${d.rolling_margin.length > 1 ? html`<div class="chart h260"><canvas id="margin"></canvas></div>` : stateEmpty("No games yet", "")}</div></section>
      <section class="card s5"><div class="card-h"><h3>Four factors vs. league</h3><span class="tiny muted">Green = better than average</span></div><div class="card-b">${factors.map(([k, l, low]) => { const v = t[k], a = avg[k], diff = v - a, good = low ? diff < 0 : diff > 0; return html`<div class="metric"><span>${l}</span><span><b class="num">${fmt.num(v)}</b> <span class="tiny ${good ? "pos" : "neg"}">${fmt.signed(diff)} vs ${fmt.num(a)}</span></span></div>`; })}</div></section>
      <section class="card s7"><div class="card-h"><h3>Recent results</h3></div><div class="card-b flush">${d.recent_results.length ? html`<div class="list">${d.recent_results.map((g) => html`<a href="#/games/${g.game_id}"><div class="li"><span class="chip ${g.win ? "pos" : ""}" style="width:30px;justify-content:center">${g.win ? "W" : "L"}</span><div class="grow"><div class="t">${g.home ? "vs" : "@"} ${g.opp}</div><div class="s">${fmt.date(g.date)}</div></div><b class="num">${g.pts}–${g.opp_pts}</b></div></a>`)}</div>` : stateEmpty("No results yet", "")}</div></section>
      <section class="card s12"><div class="card-h"><h3>Upcoming games</h3></div><div class="card-b">${d.upcoming?.length ? html`<div class="games">${d.upcoming.map((g) => gameCard(g))}</div>` : stateEmpty("No upcoming games found", "Only the current season's schedule is available.", "calendar")}</div></section>
      <section class="card s8"><div class="card-h"><h3>Roster</h3><span class="tiny muted">Top ${d.roster.length} by PIE</span></div><div class="card-b flush" id="roster"></div></section>
      <section class="col s4" style="gap:16px">${aiBriefCard()}<div class="card"><div class="card-h"><h3>Injury report</h3>${badge("live", "ESPN context")}</div><div class="card-b">${d.injuries === null ? html`<span class="small muted">Injury report unavailable.</span>` : d.injuries.length ? d.injuries.map((i) => html`<div class="row between small" style="padding:4px 0"><span>${i.player}</span><span class="chip">${i.status}</span></div>`) : html`<span class="small muted">No reported absences.</span>`}</div></div></section></div>`.toString();
  loadBrief(root, api, { type: "team", id: abbr, season });
  if (d.elo_history.length > 1) makeChart(root.querySelector("#elo"), (c) => ({ type: "line", data: { labels: d.elo_history.map((x) => fmt.date(x.date, { month: "short", day: "numeric" })), datasets: [{ data: d.elo_history.map((x) => x.elo), borderColor: t.primary, backgroundColor: hexA(t.primary, 0.15), fill: true, tension: 0.25, borderWidth: 2.4, pointRadius: 0, pointHoverRadius: 5 }] }, options: baseOptions(c, { scales: { x: axis(c, { grid: { display: false }, ticks: { maxTicksLimit: 8 } }), y: axis(c) } }) }), charts);
  if (d.rolling_margin.length > 1) makeChart(root.querySelector("#margin"), (c) => ({ type: "bar", data: { labels: d.rolling_margin.map((x) => fmt.date(x.date, { month: "short", day: "numeric" })), datasets: [{ type: "line", label: "10-game avg", data: d.rolling_margin.map((x) => x.rolling_margin), borderColor: c.accent, borderWidth: 2.5, pointRadius: 0, tension: 0.3, order: 1 }, { label: "Margin", data: d.rolling_margin.map((x) => x.margin), backgroundColor: d.rolling_margin.map((x) => (x.margin >= 0 ? hexA(c.pos, 0.5) : hexA(c.neg, 0.5))), borderRadius: 3, order: 2 }] }, options: baseOptions(c, { scales: { x: axis(c, { grid: { display: false }, ticks: { maxTicksLimit: 8 } }), y: axis(c) } }) }), charts);
  sortableTable(root.querySelector("#roster"), { sortKey: "pie", rows: d.roster, href: (p) => `#/players/${p.id}`, columns: [
    { key: "name", label: "Player", asc: true, render: (p) => html`<div class="ent">${face(p.id)}<div><b>${p.name}</b><small>${p.archetype || ""}</small></div></div>` }, { key: "gp", label: "GP", n: true }, { key: "min", label: "MIN", n: true },
    { key: "pts", label: "PTS", n: true, render: (p) => html`<b>${fmt.num(p.pts)}</b>` }, { key: "reb", label: "REB", n: true }, { key: "ast", label: "AST", n: true }, { key: "ts_pct", label: "TS%", n: true }, { key: "pie", label: "PIE", n: true },
    { key: "form_delta", label: "Form", n: true, render: (p) => p.form_label ? formChip(p.form_label, p.form_delta) : "—" }] });
}
