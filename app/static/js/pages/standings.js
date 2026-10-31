import { api } from "../core/api.js";
import { html, raw } from "../core/dom.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, teamColor } from "../ui/charts.js";
import { pageHead, provenance, notices, teamLogo, sortableTable, skeletonPage, seg, bindSeg, stateEmpty } from "../ui/components.js";
import { setQuery } from "../core/router.js";

export default async function render(ctx) {
  const { root, season } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  let tab = ["standings", "power", "elo"].includes(ctx.query.tab) ? ctx.query.tab : "standings";
  root.innerHTML = skeletonPage(2).toString();
  const [st, tm] = await Promise.all([api("/standings", { season }, { signal: ctx.signal }), api("/teams", { season }, { signal: ctx.signal }).catch(() => null)]);
  root.innerHTML = pageHead({ title: "Standings & Rankings", sub: "Official standings, a blended power ranking, and Elo ratings.", right: provenance(st.meta) }).toString() + notices(st.meta).toString() + html`<div class="toolbar">${seg("tab", [["standings", "Standings"], ["power", "Power rankings"], ["elo", "Elo ratings"]], tab)}</div><div id="body"></div>`.toString();
  const body = root.querySelector("#body");
  const conf = (title, rows) => html`<section class="card s6"><div class="card-h"><h3>${title}</h3><span class="tiny muted">1–6 playoffs · 7–10 play-in</span></div><div class="card-b flush" id="c-${title}"></div></section>`;
  const draw = () => {
    disposeCharts(charts); setQuery({ tab });
    if (tab === "standings") {
      body.innerHTML = html`<div class="grid">${conf("East")}${conf("West")}</div>`.toString();
      [["East", st.data.east], ["West", st.data.west]].forEach(([n, rows]) => sortableTable(body.querySelector(`[id="c-${n}"]`), { sortKey: "conf_rank", sortDir: "asc", rows, href: (t) => `#/teams/${t.abbr}`,
        onDraw: (c) => c.querySelectorAll("tbody tr").forEach((tr, i) => { if (i === 5 || i === 9) tr.querySelectorAll("td").forEach((td) => (td.style.borderBottom = "2px dashed var(--border-strong)")); }),
        columns: [{ key: "conf_rank", label: "#", sort: (t) => +t.conf_rank, asc: true, render: (t) => html`<span class="muted">${t.conf_rank}</span>` }, { key: "name", label: "Team", asc: true, render: (t) => html`<div class="ent">${teamLogo(t, "sm")}<b>${t.abbr}</b></div>` },
          { key: "w", label: "W", n: true }, { key: "l", label: "L", n: true, asc: true }, { key: "w_pct", label: "PCT", n: true, render: (t) => fmt.num(t.w_pct, 3) }, { key: "conf_gb", label: "GB", n: true },
          { key: "l10", label: "L10", n: true }, { key: "streak", label: "Strk", n: true }, { key: "home", label: "Home", n: true }, { key: "road", label: "Road", n: true }, { key: "diff", label: "Diff", n: true, render: (t) => html`<span class="${t.diff > 0 ? "pos" : t.diff < 0 ? "neg" : ""}">${fmt.signed(t.diff)}</span>` }] }));
    } else if (!tm) { body.innerHTML = stateEmpty("Team ratings unavailable", "Power rankings and Elo need team statistics.").toString(); }
    else if (tab === "power") {
      const rows = tm.data.teams.slice().sort((a, b) => a.power_rank - b.power_rank);
      body.innerHTML = html`<div class="card"><div class="card-b flush"><div class="list">${rows.map((t) => html`<a href="#/teams/${t.abbr}"><div class="li"><span class="rankno" style="font-size:15px">${t.power_rank}</span>${teamLogo(t, "lg")}<div class="grow"><div class="t">${t.name} <span class="chip" style="margin-left:6px">${t.tier}</span></div><div class="s" style="white-space:normal">${t.blurb}</div></div><div style="width:160px"><div class="bar-cell"><div class="bar"><i style="width:${t.power_score}%;background:${t.primary}"></i></div><b class="num">${fmt.num(t.power_score, 0)}</b></div><div class="tiny muted" title="z-scores of net rating, Elo, last-10 margin, win%">NR ${fmt.signed(t.components.net_rating_z, 1)} · Elo ${fmt.signed(t.components.elo_z, 1)} · L10 ${fmt.signed(t.components.form_z, 1)}</div></div><span class="tiny muted" style="width:70px;text-align:right">Record #${t.record_rank}</span></div></a>`)}</div></div><div class="card-f">Power score = 40% net rating + 30% Elo + 20% last-10 margin + 10% win%, each standardised across the league. A derived metric, not an official ranking.</div></div>`.toString();
    } else {
      const rows = tm.data.teams.filter((t) => t.elo != null).sort((a, b) => b.elo - a.elo);
      body.innerHTML = html`<section class="card"><div class="card-h"><h3>Elo ratings</h3><span class="tiny muted">538 method: K=20, margin-of-victory multiplier, 75% season carry-over, 100-pt home edge</span></div><div class="card-b"><div class="chart h440" style="height:${Math.max(380, rows.length * 22)}px"><canvas id="elo"></canvas></div></div></section>`.toString();
      makeChart(body.querySelector("#elo"), (c) => ({ type: "bar", data: { labels: rows.map((t) => t.abbr), datasets: [{ data: rows.map((t) => t.elo), backgroundColor: rows.map(teamColor), borderRadius: 4 }] }, options: baseOptions(c, { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { title: (i) => rows[i[0].dataIndex].name, label: (i) => `Elo ${fmt.num(i.raw, 0)}` } } }, scales: { x: axis(c, { min: Math.floor(Math.min(...rows.map((t) => t.elo)) / 50) * 50 }), y: axis(c, { grid: { display: false } }) } }) }), charts);
    }
  };
  draw(); ctx.onCleanup(bindSeg(root, "tab", (v) => { tab = v; draw(); }));
}
