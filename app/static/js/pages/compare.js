import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw, delegate, esc } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt, hexA } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, colors } from "../ui/charts.js";
import { pageHead, provenance, notices, face, teamLogo, skeletonPage, stateEmpty, formChip, badge, bar } from "../ui/components.js";
import { setQuery } from "../core/router.js";

export function picker(host, players, selected, onPick, label) {
  let open = false, list = players;
  const cur = () => players.find((p) => p.id === selected);
  host.innerHTML = html`<div class="field"><label>${label}</label><div class="picker"><button class="input row between" type="button" style="width:100%;text-align:left;cursor:pointer" aria-haspopup="listbox"><span class="row gap-6" data-cur></span>${raw(icon("down"))}</button><div class="picker-list" hidden><input class="input" placeholder="Search players…" style="width:100%;margin-bottom:4px"><div data-opts></div></div></div></div>`.toString();
  const btn = host.querySelector("button"), box = host.querySelector(".picker-list"), inp = box.querySelector("input"), opts = box.querySelector("[data-opts]");
  const paintCur = () => { const p = cur(); host.querySelector("[data-cur]").innerHTML = p ? `${face(p.id, "").toString()}<b>${esc(p.name)}</b><span class="muted small">${esc(p.team)}</span>` : "Select a player"; };
  const paint = () => { opts.innerHTML = list.slice(0, 40).map((p) => `<div class="opt" role="option" data-id="${p.id}">${face(p.id).toString()}<div class="grow"><b>${esc(p.name)}</b><div class="tiny muted">${esc(p.team)} · ${fmt.num(p.pts)} pts</div></div></div>`).join("") || `<div class="state"><p>No players match</p></div>`; };
  const toggle = (v) => { open = v; box.hidden = !v; if (v) { inp.value = ""; list = players; paint(); inp.focus(); } };
  btn.addEventListener("click", () => toggle(!open));
  inp.addEventListener("input", () => { const q = inp.value.toLowerCase(); list = players.filter((p) => p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q); paint(); });
  opts.addEventListener("click", (e) => { const o = e.target.closest(".opt"); if (o) { selected = +o.dataset.id; paintCur(); toggle(false); onPick(selected); } });
  document.addEventListener("click", (e) => { if (open && !host.contains(e.target)) toggle(false); });
  paintCur();
  return { set(id) { selected = id; paintCur(); } };
}

export default async function render(ctx) {
  const { root, season } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data: list, meta } = await api("/players", { season, limit: 600, qualified: 1, sort: "pie" }, { signal: ctx.signal });
  const players = list.players;
  if (players.length < 2) { root.innerHTML = stateEmpty("Not enough qualified players yet", "Comparison unlocks once players have enough games this season.", "users").toString(); return; }
  let a = +ctx.query.a || players[0].id, b = +ctx.query.b || players.find((p) => p.id !== a).id;
  root.innerHTML = pageHead({ title: "Player Comparison", sub: "Side-by-side production, efficiency and form, with percentile radars against every qualified player.", right: provenance(meta) }).toString() + notices(meta).toString() + html`
    <div class="toolbar" style="align-items:flex-end"><div style="min-width:260px;flex:1;max-width:380px" id="pa"></div><button class="btn" id="swap" title="Swap players" aria-label="Swap players">${raw(icon("refresh"))}</button><div style="min-width:260px;flex:1;max-width:380px" id="pb"></div></div><div id="out"></div>`.toString();
  const pa = picker(root.querySelector("#pa"), players, a, (id) => { a = id; run(); }, "Player A");
  const pb = picker(root.querySelector("#pb"), players, b, (id) => { b = id; run(); }, "Player B");
  root.querySelector("#swap").addEventListener("click", () => { [a, b] = [b, a]; pa.set(a); pb.set(b); run(); });
  const out = root.querySelector("#out");
  const COL_A = () => colors().accent, COL_B = () => colors().info;

  async function run() {
    if (a === b) { out.innerHTML = stateEmpty("Pick two different players", "", "users").toString(); return; }
    setQuery({ a, b }); disposeCharts(charts); out.innerHTML = skeletonPage(1).toString();
    try {
      const { data: d } = await api("/players/compare", { a, b, season }, { signal: ctx.signal });
      const pA = d.a, pB = d.b, axes = d.radar_axes, ca = COL_A(), cb = COL_B();
      const head = (p, col) => html`<div class="card hover s6" style="border-top:3px solid ${col}"><div class="card-b row">${face(p.id, "lg")}<div class="grow"><a href="#/players/${p.id}" style="font-size:20px;font-weight:700;letter-spacing:-.02em">${p.name}</a><div class="row gap-6 wrap" style="margin-top:6px">${teamLogo(store.team(p.team), "sm")}<span class="chip">${p.team}</span>${p.archetype ? html`<span class="chip accent">${p.archetype}</span>` : ""}${p.form_label ? formChip(p.form_label, p.form_delta) : ""}</div></div><div class="right"><b class="num" style="font-size:30px">${fmt.num(p.pts)}</b><div class="tiny muted">PPG</div></div></div></div>`;
      out.innerHTML = html`<div class="grid">${head(pA, ca)}${head(pB, cb)}
        <section class="card s5"><div class="card-h"><h3>Percentile radar</h3><div class="legend"><span><i style="background:${ca}"></i>${pA.name.split(" ").slice(-1)}</span><span><i style="background:${cb}"></i>${pB.name.split(" ").slice(-1)}</span></div></div><div class="card-b"><div class="chart h380"><canvas id="radar"></canvas></div></div></section>
        <section class="card s7"><div class="card-h"><h3>Metric comparison</h3><span class="chip accent">${d.edges.a} – ${d.edges.b} categories</span></div><div class="card-b flush"><table class="tbl"><thead><tr><th class="n">${pA.name.split(" ").slice(-1)}</th><th class="center">Metric</th><th>${pB.name.split(" ").slice(-1)}</th></tr></thead><tbody>${d.metrics.map((m) => html`<tr><td class="n num ${m.edge === "a" ? "pos" : ""}">${m.edge === "a" ? html`<b>${fmt.num(m.a)}</b>` : fmt.num(m.a)}</td><td class="center muted small">${m.label}</td><td class="num ${m.edge === "b" ? "pos" : ""}">${m.edge === "b" ? html`<b>${fmt.num(m.b)}</b>` : fmt.num(m.b)}</td></tr>`)}</tbody></table></div></section>
        <section class="card s6"><div class="card-h"><h3>Recent scoring</h3><span class="tiny muted">Last 15 games</span></div><div class="card-b">${d.recent.a && d.recent.b ? html`<div class="chart h260"><canvas id="recent"></canvas></div>` : stateEmpty("Game logs unavailable", "")}</div></section>
        <section class="card s6"><div class="card-h"><h3>Strengths &amp; weaknesses</h3></div><div class="card-b"><div class="grid" style="gap:16px">${[[pA, ca], [pB, cb]].map(([p, col]) => html`<div class="s6"><b style="color:${col}">${p.name}</b><div class="lbl" style="margin:10px 0 6px">Strengths</div><div class="pill-list">${p.strengths.length ? p.strengths.map((x) => html`<span class="chip pos">${x}</span>`) : html`<span class="muted small">None stand out</span>`}</div><div class="lbl" style="margin:10px 0 6px">Weaknesses</div><div class="pill-list">${p.weaknesses.length ? p.weaknesses.map((x) => html`<span class="chip cold">${x}</span>`) : html`<span class="muted small">None stand out</span>`}</div></div>`)}</div></div></section></div>`.toString();
      makeChart(out.querySelector("#radar"), (c) => ({ type: "radar", data: { labels: axes.map((x) => x.label.replace(/ \(.*\)/, "")), datasets: [pA, pB].map((p, i) => ({ label: p.name, data: axes.map((x) => p.percentiles?.[x.key] ?? 0), backgroundColor: hexA(i ? COL_B() : COL_A(), 0.18), borderColor: i ? COL_B() : COL_A(), borderWidth: 2, pointRadius: 3, pointBackgroundColor: i ? COL_B() : COL_A() })) },
        options: baseOptions(c, { plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { label: (i) => `${i.dataset.label}: ${fmt.ord(Math.round(i.raw))} pct` } } }, scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: c.grid }, angleLines: { color: c.grid }, pointLabels: { color: c.text, font: { family: "Inter", size: 11 } } } } }) }), charts);
      if (d.recent.a && d.recent.b) { const ra = d.recent.a.games, rb = d.recent.b.games, n = Math.max(ra.length, rb.length);
        makeChart(out.querySelector("#recent"), (c) => ({ type: "line", data: { labels: Array.from({ length: n }, (_, i) => `G${i + 1}`), datasets: [[pA, ra, COL_A()], [pB, rb, COL_B()]].map(([p, g, col]) => ({ label: p.name, data: g.map((x) => x.pts), borderColor: col, backgroundColor: col, borderWidth: 2.4, tension: 0.3, pointRadius: 3 })) }, options: baseOptions(c, { plugins: { legend: { display: false } }, scales: { x: axis(c, { grid: { display: false } }), y: axis(c, { beginAtZero: true }) } }) }), charts); }
    } catch (e) { if (e.name !== "AbortError") out.innerHTML = html`<div class="card"><div class="state err">${raw(icon("alert"))}<h4>Couldn't compare these players</h4><p>${e.message}</p></div></div>`.toString(); }
  }
  run();
}
