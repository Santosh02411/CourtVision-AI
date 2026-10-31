import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw, esc } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, teamColor } from "../ui/charts.js";
import { pageHead, provenance, notices, face, teamLogo, formChip, sortableTable, stateError, skeletonPage, card, badge, kpi, animateCounts } from "../ui/components.js";
import { setQuery } from "../core/router.js";

export default async function render(ctx) {
  const { root, season } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data, meta } = await api("/players", { season, limit: 600, qualified: 0 }, { signal: ctx.signal });
  const all = data.players, q = data.qualification;
  const teams = [...new Set(all.map((p) => p.team))].sort(), archetypes = [...new Set(all.map((p) => p.archetype).filter(Boolean))].sort();
  const st = { q: ctx.query.q || "", team: ctx.query.team || "", arche: ctx.query.arche || "", qualified: ctx.query.all !== "1", limit: 60 };
  root.innerHTML = pageHead({ title: "Player Intelligence", sub: "Per-game production, efficiency, recent form and AI-derived archetypes for every player. Click a row for the full profile.", right: provenance(meta) }).toString() + notices(meta).toString() + html`
    <div class="toolbar">
      <div class="field" style="min-width:220px"><label for="q">Search</label><input id="q" class="input" placeholder="Player name" value="${st.q}" autocomplete="off"></div>
      <div class="field"><label for="team">Team</label><select id="team" class="input"><option value="">All teams</option>${teams.map((t) => html`<option ${t === st.team ? "selected" : ""}>${t}</option>`)}</select></div>
      <div class="field"><label for="arche">Archetype</label><select id="arche" class="input"><option value="">All archetypes</option>${archetypes.map((a) => html`<option ${a === st.arche ? "selected" : ""}>${a}</option>`)}</select></div>
      <label class="row gap-6 small" style="padding-bottom:9px;cursor:pointer"><input type="checkbox" id="qual" class="range" ${st.qualified ? "checked" : ""}> Qualified only (${q.min_gp}+ GP, ${q.min_mpg}+ MPG)</label><div class="grow"></div><span class="muted small" id="count"></span></div>
    <div class="grid" style="margin-bottom:16px"><section class="card s12"><div class="card-h"><h3>Usage vs. efficiency</h3><span class="tiny muted">Each dot is a qualified player · size = points · click to open</span></div><div class="card-b"><div class="chart h320"><canvas id="scatter"></canvas></div></div></section></div>
    <section class="card"><div class="card-b flush" id="table"></div><div class="card-f row between"><span id="foot"></span><button class="btn sm" id="more">Show more</button></div></section>`.toString();
  const $ = (s) => root.querySelector(s);

  // scatter (qualified players)
  const qual = all.filter((p) => p.qualified && p.usg_pct != null && p.ts_pct != null).sort((a, b) => b.min - a.min).slice(0, 180);
  const avgU = qual.reduce((s, p) => s + p.usg_pct, 0) / (qual.length || 1), avgT = qual.reduce((s, p) => s + p.ts_pct, 0) / (qual.length || 1);
  if (qual.length) makeChart($("#scatter"), (c) => ({
    type: "scatter", data: { datasets: [{ data: qual.map((p) => ({ x: p.usg_pct, y: p.ts_pct, p })), backgroundColor: qual.map((p) => teamColor(store.team(p.team)) + "cc"), borderColor: qual.map((p) => teamColor(store.team(p.team))), pointRadius: qual.map((p) => 3 + Math.sqrt(Math.max(0, p.pts)) * 0.9), pointHoverRadius: qual.map((p) => 5 + Math.sqrt(Math.max(0, p.pts)) * 0.9) }] },
    options: baseOptions(c, { interaction: { mode: "nearest", intersect: true }, onClick: (e, els) => els.length && (location.hash = `#/players/${qual[els[0].index].id}`), onHover: (e, els) => { e.native.target.style.cursor = els.length ? "pointer" : "default"; },
      plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { title: (i) => `${i[0].raw.p.name} · ${i[0].raw.p.team}`, label: (i) => [`USG ${fmt.pct(i.raw.x)} · TS ${fmt.pct(i.raw.y)}`, `${fmt.num(i.raw.p.pts)} pts · ${fmt.num(i.raw.p.reb)} reb · ${fmt.num(i.raw.p.ast)} ast`] } } },
      scales: { x: axis(c, { title: { display: true, text: "Usage rate % →", color: c.text } }), y: axis(c, { title: { display: true, text: "True shooting % →", color: c.text } }) } }),
    plugins: [{ id: "avg", afterDatasetsDraw(ch) { const { ctx: g, chartArea: a, scales: { x, y } } = ch; g.save(); g.strokeStyle = c.grid; g.setLineDash([5, 5]); g.lineWidth = 1.5; g.beginPath(); g.moveTo(x.getPixelForValue(avgU), a.top); g.lineTo(x.getPixelForValue(avgU), a.bottom); g.moveTo(a.left, y.getPixelForValue(avgT)); g.lineTo(a.right, y.getPixelForValue(avgT)); g.stroke(); g.fillStyle = c.text; g.font = "600 10.5px Inter"; g.setLineDash([]); g.fillText("High usage · efficient", a.right - 128, a.top + 14); g.restore(); } }],
  }), charts); else $("#scatter").closest(".card").style.display = "none";

  const cols = [
    { key: "name", label: "Player", asc: true, render: (p) => html`<div class="ent">${face(p.id)}<div><b>${p.name}</b><small>${p.team}${p.age ? ` · ${p.age}y` : ""}</small></div></div>` },
    { key: "archetype", label: "Archetype", asc: true, sort: (p) => p.archetype || "", render: (p) => p.archetype ? html`<span class="chip">${p.archetype}</span>` : html`<span class="muted">—</span>` },
    { key: "gp", label: "GP", n: true }, { key: "min", label: "MIN", n: true, render: (p) => fmt.num(p.min) },
    { key: "pts", label: "PTS", n: true, render: (p) => html`<b>${fmt.num(p.pts)}</b>` }, { key: "reb", label: "REB", n: true, render: (p) => fmt.num(p.reb) }, { key: "ast", label: "AST", n: true, render: (p) => fmt.num(p.ast) },
    { key: "stl", label: "STL", n: true, render: (p) => fmt.num(p.stl) }, { key: "blk", label: "BLK", n: true, render: (p) => fmt.num(p.blk) },
    { key: "fg_pct", label: "FG%", n: true, render: (p) => fmt.num(p.fg_pct) }, { key: "fg3_pct", label: "3P%", n: true, render: (p) => fmt.num(p.fg3_pct) },
    { key: "ts_pct", label: "TS%", n: true, render: (p) => fmt.num(p.ts_pct) }, { key: "usg_pct", label: "USG%", n: true, render: (p) => fmt.num(p.usg_pct) },
    { key: "pie", label: "PIE", n: true, title: "Player Impact Estimate", render: (p) => html`<div class="bar-cell"><div class="bar"><i style="width:${Math.min(100, (p.pie || 0) * 4.5)}%"></i></div><b class="num">${fmt.num(p.pie)}</b></div>` },
    { key: "form_delta", label: "Form (L10)", n: true, title: "Last-10 PPG minus season PPG; label from z-score vs. league", render: (p) => p.form_label ? formChip(p.form_label, p.form_delta) : html`<span class="muted">—</span>` },
  ];
  const tbl = sortableTable($("#table"), { sortKey: "pie", rows: [], columns: cols, rank: true, href: (p) => `#/players/${p.id}`, maxHeight: 720 });
  const apply = () => {
    const needle = st.q.trim().toLowerCase();
    let rows = all.filter((p) => (!st.qualified || p.qualified) && (!st.team || p.team === st.team) && (!st.arche || p.archetype === st.arche) && (!needle || p.name.toLowerCase().includes(needle)));
    $("#count").textContent = `${rows.length} players`;
    tbl.setRows(rows.slice(0, st.limit)); $("#foot").textContent = `Showing ${Math.min(rows.length, st.limit)} of ${rows.length}`; $("#more").style.display = rows.length > st.limit ? "" : "none";
    $("#more").onclick = () => { st.limit += 60; apply(); };
    setQuery({ q: st.q, team: st.team, arche: st.arche, all: st.qualified ? "" : "1" });
  };
  $("#q").addEventListener("input", (e) => { st.q = e.target.value; st.limit = 60; apply(); });
  $("#team").addEventListener("change", (e) => { st.team = e.target.value; st.limit = 60; apply(); });
  $("#arche").addEventListener("change", (e) => { st.arche = e.target.value; st.limit = 60; apply(); });
  $("#qual").addEventListener("change", (e) => { st.qualified = e.target.checked; st.limit = 60; apply(); });
  apply();
}
