import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw, debounce } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions } from "../ui/charts.js";
import { pageHead, provenance, notices, face, teamLogo, skeletonPage, skel, stateEmpty, stateError, badge, seg, bindSeg, kpi, animateCounts, bindTips, notice } from "../ui/components.js";
import { courtSvg } from "../ui/court.js";
import { picker } from "./compare.js";
import { setQuery } from "../core/router.js";

const ZONES = ["Restricted Area", "In The Paint (Non-RA)", "Mid-Range", "Left Corner 3", "Right Corner 3", "Above the Break 3"];
export default async function render(ctx) {
  const { root, season } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data: list, meta: lmeta } = await api("/players", { season, limit: 600, qualified: 1, sort: "pts" }, { signal: ctx.signal });
  const players = list.players;
  if (!players.length) { root.innerHTML = stateEmpty("No players available", "Shot data needs players with games this season.", "crosshair").toString(); return; }
  const f = { player: +ctx.query.player || players[0].id, periods: new Set((ctx.query.period || "").split(",").filter(Boolean)), type: ctx.query.type || "", result: "", last_n: "", zone: "", dmin: "", dmax: "", view: "zones" };
  root.innerHTML = pageHead({ title: "Shot Analysis", sub: "Where a player shoots, how well, and how that compares with the league and with the shot-quality model.", right: provenance(lmeta) }).toString() + html`
    <div class="toolbar"><div style="min-width:280px;max-width:380px;flex:1" id="pp"></div>
      <div class="field"><label>Period</label><div class="seg" id="periods">${[1, 2, 3, 4].map((p) => html`<button type="button" data-p="${p}" class="${f.periods.has(String(p)) ? "on" : ""}">Q${p}</button>`)}</div></div>
      <div class="field"><label>Shot type</label>${seg("type", [["", "All"], ["2", "2PT"], ["3", "3PT"]], f.type)}</div>
      <div class="field"><label>Result</label>${seg("result", [["", "All"], ["made", "Made"], ["missed", "Missed"]], "")}</div>
      <div class="field"><label for="zone">Zone</label><select class="input" id="zone"><option value="">All zones</option>${ZONES.map((z) => html`<option>${z}</option>`)}</select></div>
      <div class="field"><label for="lastn">Games</label><select class="input" id="lastn"><option value="">Full season</option><option value="5">Last 5</option><option value="10">Last 10</option><option value="20">Last 20</option></select></div>
      <div class="field"><label>Distance (ft)</label><div class="row gap-6"><input class="input" id="dmin" type="number" min="0" max="90" placeholder="min" style="width:72px"><input class="input" id="dmax" type="number" min="0" max="90" placeholder="max" style="width:72px"></div></div></div>
    <div id="notes"></div><div id="out">${skeletonPage(1)}</div>`.toString();
  const $ = (s) => root.querySelector(s); let data = null, meta = null;
  const pk = picker($("#pp"), players, f.player, (id) => { f.player = id; load(); }, "Player");

  const draw = () => {
    const d = data, out = $("#out"); disposeCharts(charts);
    if (!d || d.empty) { out.innerHTML = html`<div class="card">${stateEmpty("No shots match these filters", `${d?.total_unfiltered ?? 0} shots are recorded for this player and season. Loosen a filter to see more.`, "crosshair")}</div>`.toString(); return; }
    const t = d.totals, p = players.find((x) => x.id === f.player);
    out.innerHTML = html`<div class="grid"><section class="card s7"><div class="card-h"><h3>${p ? p.name : "Player"} · ${meta.season}</h3>${seg("view", [["zones", "Zones"], ["heat", "Heatmap"], ["shots", "Shots"]], f.view)}</div><div class="card-b" id="court"></div>
        <div class="card-f">${f.view === "zones" ? "Zone colour = FG% minus league average (green above, red below)." : f.view === "heat" ? "Cell colour = FG% (blue low → orange high); opacity = shot volume." : `${d.shots_sampled ? "Showing a sample of shots. " : ""}● made · ✕ missed. Hover for the model's expected FG%.`}</div></section>
      <section class="col s5" style="gap:16px"><div class="kpis" style="grid-template-columns:repeat(2,1fr);margin:0">${kpi({ label: "Attempts", count: t.fga, dec: 0, sub: `${t.fgm} made` })}${kpi({ label: "FG%", count: t.fg_pct, dec: 1, suffix: "%", sub: `eFG ${t.efg_pct}%` })}${kpi({ label: "Model xFG%", count: t.xfg_pct, dec: 1, suffix: "%", sub: "Expected from locations", tip: "Model estimate" })}${kpi({ label: "Shot making", value: fmt.signed(t.shot_making), sub: "Makes minus expected", tip: "Actual makes − model-expected makes" })}</div>
        <div class="notice info">${raw(icon("info"))}<div><b>${d.model.model}.</b> ${d.model.caveat || ""} ${d.model.trained_on === "synthetic" ? "Trained on synthetic data, so treat xFG as indicative." : ""}</div></div>
        <section class="card"><div class="card-h"><h3>Zones</h3></div><div class="card-b flush"><table class="tbl"><thead><tr><th>Zone</th><th class="n">FGA</th><th class="n">FG%</th><th class="n">Lg</th><th class="n">Diff</th></tr></thead><tbody>${d.zones.map((z) => html`<tr><td>${z.zone}</td><td class="n">${z.fga}</td><td class="n"><b>${z.fg_pct}</b></td><td class="n muted">${z.league_fg_pct ?? "—"}</td><td class="n ${z.diff > 0 ? "pos" : z.diff < 0 ? "neg" : ""}">${fmt.signed(z.diff)}</td></tr>`)}</tbody></table></div></section></section>
      <section class="card s6"><div class="card-h"><h3>Accuracy by distance</h3><div class="legend"><span><i style="background:var(--accent)"></i>Actual FG%</span><span><i style="background:var(--info)"></i>Model xFG%</span></div></div><div class="card-b"><div class="chart h260"><canvas id="dist"></canvas></div></div></section>
      <section class="card s6"><div class="card-h"><h3>By quarter</h3></div><div class="card-b"><div class="chart h260"><canvas id="per"></canvas></div></div></section></div>`.toString();
    $("#court").innerHTML = courtSvg({ mode: f.view, zones: d.zones, bins: d.bins, shots: d.shots }).toString(); bindTips(root); animateCounts(root);
    makeChart($("#dist"), (c) => ({ type: "bar", data: { labels: d.distance_buckets.map((b) => b.label), datasets: [{ label: "Actual", data: d.distance_buckets.map((b) => b.fg_pct), backgroundColor: c.accent, borderRadius: 4 }, { label: "Model xFG", data: d.distance_buckets.map((b) => b.xfg_pct), backgroundColor: c.info, borderRadius: 4 }] }, options: baseOptions(c, { plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { afterBody: (i) => `${d.distance_buckets[i[0].dataIndex].fga} attempts` } } }, scales: { x: axis(c, { grid: { display: false } }), y: axis(c, { beginAtZero: true, ticks: { callback: (v) => `${v}%` } }) } }) }), charts);
    makeChart($("#per"), (c) => ({ type: "bar", data: { labels: d.by_period.map((b) => `Q${b.period}`), datasets: [{ data: d.by_period.map((b) => b.fg_pct), backgroundColor: c.accent, borderRadius: 5 }] }, options: baseOptions(c, { plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { label: (i) => `${i.raw}% on ${d.by_period[i.dataIndex].fga} FGA` } } }, scales: { x: axis(c, { grid: { display: false } }), y: axis(c, { beginAtZero: true, ticks: { callback: (v) => `${v}%` } }) } }) }), charts);
  };
  async function load() {
    setQuery({ player: f.player, type: f.type, period: [...f.periods].join(",") });
    $("#out").innerHTML = `<div class="card"><div class="card-b">${skel(300)}</div></div>`;
    try { const r = await api(`/players/${f.player}/shots`, { season, type: f.type, result: f.result, zone: f.zone, last_n: f.last_n, dmin: f.dmin, dmax: f.dmax, period: [...f.periods].join(",") }, { signal: ctx.signal }); data = r.data; meta = r.meta; $("#notes").innerHTML = notices(meta).toString(); draw(); }
    catch (e) { if (e.name !== "AbortError") { $("#out").innerHTML = stateError(e, true).toString(); $("#out [data-retry]")?.addEventListener("click", load); } }
  }
  root.addEventListener("click", (e) => { const b = e.target.closest("#periods button"); if (!b) return; b.classList.toggle("on"); b.classList.contains("on") ? f.periods.add(b.dataset.p) : f.periods.delete(b.dataset.p); load(); });
  ctx.onCleanup(bindSeg(root, "type", (v) => { f.type = v; load(); })); ctx.onCleanup(bindSeg(root, "result", (v) => { f.result = v; load(); }));
  ctx.onCleanup(bindSeg(root, "view", (v) => { f.view = v; draw(); }));
  $("#zone").addEventListener("change", (e) => { f.zone = e.target.value; load(); }); $("#lastn").addEventListener("change", (e) => { f.last_n = e.target.value; load(); });
  const dl = debounce(() => { f.dmin = $("#dmin").value; f.dmax = $("#dmax").value; load(); }, 400); $("#dmin").addEventListener("input", dl); $("#dmax").addEventListener("input", dl);
  load();
}
