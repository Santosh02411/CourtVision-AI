import { api } from "../core/api.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, plugins, teamColor } from "../ui/charts.js";
import { pageHead, provenance, notices, teamLogo, sortableTable, skeletonPage, seg, bindSeg, trendArrow } from "../ui/components.js";

export default async function render(ctx) {
  const { root, season } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data, meta } = await api("/teams", { season }, { signal: ctx.signal });
  const all = data.teams; let conf = "all";
  root.innerHTML = pageHead({ title: "Team Analytics", sub: "Offensive, defensive and net rating, pace, Elo and recent trend for all 30 teams.", right: provenance(meta) }).toString() + notices(meta).toString() + html`
    <div class="toolbar"><div class="field"><label>Conference</label>${seg("conf", [["all", "League"], ["East", "East"], ["West", "West"]], "all")}</div></div>
    <div class="grid" style="margin-bottom:16px">
      <section class="card s6"><div class="card-h"><h3>Net rating</h3><span class="tiny muted">Points per 100 possessions</span></div><div class="card-b"><div class="chart h440"><canvas id="net"></canvas></div></div></section>
      <section class="card s6"><div class="card-h"><h3>Elo vs. net rating</h3><span class="tiny muted">Teams above the line are rated higher by Elo than by margin</span></div><div class="card-b"><div class="chart h440"><canvas id="elo"></canvas></div></div></section></div>
    <section class="card"><div class="card-b flush" id="table"></div></section>`.toString();
  const rows = () => all.filter((t) => conf === "all" || t.conference === conf);
  const tbl = sortableTable(root.querySelector("#table"), { sortKey: "net_rating", rows: rows(), rank: true, href: (t) => `#/teams/${t.abbr}`, columns: [
    { key: "name", label: "Team", asc: true, render: (t) => html`<div class="ent">${teamLogo(t)}<div><b>${t.name}</b><small>${t.conference} · ${t.division}</small></div></div>` },
    { key: "w", label: "W-L", n: true, sort: (t) => t.w_pct, render: (t) => `${t.w}-${t.l}` },
    { key: "off_rating", label: "ORtg", n: true }, { key: "def_rating", label: "DRtg", n: true, asc: true },
    { key: "net_rating", label: "Net", n: true, render: (t) => html`<b class="${t.net_rating >= 0 ? "pos" : "neg"}">${fmt.signed(t.net_rating)}</b>` },
    { key: "pace", label: "Pace", n: true }, { key: "efg_pct", label: "eFG%", n: true }, { key: "ts_pct", label: "TS%", n: true }, { key: "tov_pct", label: "TOV%", n: true, asc: true }, { key: "oreb_pct", label: "OREB%", n: true },
    { key: "elo", label: "Elo", n: true, render: (t) => fmt.num(t.elo, 0) }, { key: "l10_margin", label: "L10 margin", n: true, render: (t) => fmt.signed(t.l10_margin) },
    { key: "net_trend", label: "Trend", n: true, title: "Last-10 net rating minus season", render: (t) => t.net_trend == null ? "—" : html`${trendArrow(t.net_trend)} ${fmt.signed(t.net_trend)}` },
    { key: "power_score", label: "Power", n: true, render: (t) => fmt.num(t.power_score, 0) }] });
  const draw = () => {
    disposeCharts(charts); const r = rows().slice().sort((a, b) => (b.net_rating ?? 0) - (a.net_rating ?? 0));
    makeChart(root.querySelector("#net"), (c) => ({ type: "bar", data: { labels: r.map((t) => t.abbr), datasets: [{ data: r.map((t) => t.net_rating), backgroundColor: r.map(teamColor), borderRadius: 4 }] },
      options: baseOptions(c, { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { title: (i) => r[i[0].dataIndex].name, label: (i) => `Net ${fmt.signed(i.raw)}` } } }, scales: { x: axis(c), y: axis(c, { grid: { display: false }, ticks: { font: { family: "Inter", size: 10.5, weight: "600" } } }) }, onClick: (e, els) => els.length && (location.hash = `#/teams/${r[els[0].index].abbr}`) }) }), charts);
    const pts = r.filter((t) => t.elo != null);
    makeChart(root.querySelector("#elo"), (c) => ({ type: "scatter", data: { datasets: [{ data: pts.map((t) => ({ x: t.net_rating, y: t.elo, t })), backgroundColor: pts.map(teamColor), borderColor: c.surface, borderWidth: 2, pointRadius: 7, pointHoverRadius: 10, pointLabels: pts.map((t) => t.abbr), labelColors: pts.map(() => c.text) }] },
      options: baseOptions(c, { interaction: { mode: "nearest", intersect: true }, onClick: (e, els) => els.length && (location.hash = `#/teams/${pts[els[0].index].abbr}`), plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { title: (i) => i[0].raw.t.name, label: (i) => `Net ${fmt.signed(i.raw.x)} · Elo ${fmt.num(i.raw.y, 0)}` } } }, scales: { x: axis(c, { title: { display: true, text: "Net rating →", color: c.text } }), y: axis(c, { title: { display: true, text: "Elo →", color: c.text } }) } }), plugins: [plugins.pointLabels] }), charts);
  };
  draw();
  ctx.onCleanup(bindSeg(root, "conf", (v) => { conf = v; tbl.setRows(rows()); draw(); }));
}
