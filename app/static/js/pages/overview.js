import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw, delegate } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, plugins, teamColor } from "../ui/charts.js";
import { pageHead, provenance, notices, kpi, animateCounts, gameCard, teamLogo, face, formChip, seg, bindSeg, stateEmpty, stateError, skel, skeletonCards, badge, trendArrow, bar, sortableTable, bindTips } from "../ui/components.js";

const frame = () => html`
  <div class="kpis stagger" id="kpis">${[0, 1, 2, 3, 4].map((i) => html`<div class="kpi" style="--i:${i}">${skel(12, "50%")}${skel(28, "70%", 4)}${skel(10, "40%", 0)}</div>`)}</div>
  <div class="grid stagger">
    <section class="card s8" style="--i:1"><div class="card-h"><h3>${raw(icon("live"))} Today's games</h3><span id="today-meta"></span></div><div class="card-b" id="today">${skeletonCards(4, 150)}</div></section>
    <section class="card s4" style="--i:2"><div class="card-h"><h3>${raw(icon("activity"))} Live activity</h3><span class="tiny muted">Derived from real data</span></div><div class="card-b flush" id="feed">${skel(200, "100%", 0)}</div></section>
    <section class="card s7" style="--i:3"><div class="card-h"><h3>League landscape</h3><span class="tiny muted">Offensive vs defensive rating · top-left is best</span></div><div class="card-b"><div class="chart h380"><canvas id="landscape"></canvas></div></div></section>
    <section class="card s5" style="--i:4"><div class="card-h"><h3>${raw(icon("trend"))} Power rankings</h3><a class="btn sm" href="#/standings?tab=power">Full rankings</a></div><div class="card-b flush" id="power">${skel(300, "100%", 0)}</div></section>
    <section class="card s4" style="--i:5"><div class="card-h"><h3>Featured performers</h3><span class="tiny muted">Top PIE</span></div><div class="card-b flush" id="featured"></div></section>
    <section class="card s4" style="--i:6"><div class="card-h"><h3>League leaders</h3><div id="leader-seg"></div></div><div class="card-b flush" id="leaders"></div></section>
    <section class="card s4" style="--i:7"><div class="card-h"><h3>Games</h3><div id="sched-seg"></div></div><div class="card-b flush" id="sched"></div></section>
  </div>`;

export default async function render(ctx) {
  const { root, season } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = pageHead({ title: "Overview", sub: "Live scores, team strength, player form and model predictions in one place." }).toString() + `<div id="notes"></div>` + frame().toString();
  const { data: d, meta } = await api("/overview", { season }, { signal: ctx.signal, ttl: 20000 });
  root.querySelector(".page-head .row").innerHTML = provenance(meta).toString() + html`<button class="btn sm" id="refresh">${raw(icon("refresh"))} Refresh</button>`.toString();
  root.querySelector("#refresh").addEventListener("click", () => ctx.reload());
  root.querySelector("#notes").innerHTML = notices(meta).toString();
  root.querySelector("#today-meta").innerHTML = html`${badge("live", "Live feed")}`.toString();
  bindTips(root);

  // ---- KPIs
  const teams = d.teams, players = d.players, today = d.today || [];
  const top = teams?.power_rankings?.[0], hot = players?.hot?.[0], live = today.filter((g) => g.status === "live").length;
  const fitted = today.find((g) => g.prediction)?.prediction?.fitted;
  root.querySelector("#kpis").innerHTML = [
    kpi({ label: "Games today", count: today.length, dec: 0, sub: `${live} live · ${today.filter((g) => g.status === "final").length} final` }),
    top ? kpi({ label: "Top power-ranked", value: top.name, sub: `${top.w}-${top.l} · ${fmt.signed(top.net_rating)} net rating` }) : kpi({ label: "Top power-ranked", value: "—", sub: "Team data unavailable" }),
    teams ? kpi({ label: "League offense", count: teams.league_avg.off_rating, dec: 1, sub: `Avg ORtg · pace ${fmt.num(teams.league_avg.pace)}` }) : kpi({ label: "League offense", value: "—" }),
    hot ? kpi({ label: "Hottest scorer", value: hot.name, sub: `${fmt.signed(hot.form_delta)} PPG vs season (last 10)` }) : kpi({ label: "Hottest scorer", value: "—", sub: "Needs ≥4 recent games" }),
    kpi({ label: "Pre-game model", value: fitted === false ? "Prior" : fitted ? "Validated" : "—", sub: fitted === false ? "Uncalibrated · run train_pregame" : "Trained & tested on real games", tip: "See Models & Evaluation" }),
  ].join("");
  animateCounts(root);

  // ---- today's games (live-updating)
  const todayEl = root.querySelector("#today");
  let games = today;
  const drawToday = () => {
    if (d.today === null) { todayEl.innerHTML = stateError({ message: "Scoreboard unavailable right now." }).toString(); return; }
    if (!games.length) {
      const nxt = d.schedule?.upcoming?.slice(0, 3) || [];
      todayEl.innerHTML = stateEmpty("No games today", nxt.length ? `Next up: ${nxt[0].away.abbr} @ ${nxt[0].home.abbr} on ${fmt.date(nxt[0].date)}.` : "Check the schedule for upcoming games.", "calendar").toString() + (nxt.length ? `<div class="games">${nxt.map((g) => gameCard(g)).join("")}</div>` : "");
      return;
    }
    todayEl.innerHTML = `<div class="games">${games.map((g) => gameCard(g)).join("")}</div>`;
  };
  drawToday();
  const off = store.on("live", ({ games: lg }) => {
    if (!games.length || !lg.length) return;
    const by = Object.fromEntries(lg.map((g) => [g.game_id, g])); let changed = false;
    games = games.map((g) => { const n = by[g.game_id]; if (!n) return g; const m = { ...g, status: n.status, status_text: n.status_text, period: n.period, clock: n.clock, home: { ...g.home, ...n.home }, away: { ...g.away, ...n.away }, live_wp: n.live_wp ?? g.live_wp };
      if (JSON.stringify([m.status, m.home.score, m.away.score, m.clock]) !== JSON.stringify([g.status, g.home.score, g.away.score, g.clock])) changed = true; return m; });
    if (changed) drawToday();
  });
  ctx.onCleanup(off);

  // ---- feed
  root.querySelector("#feed").innerHTML = d.activity?.length ? `<div class="feed">${d.activity.map((a) => {
    const href = a.game_id ? `#/games/${a.game_id}` : a.player_id ? `#/players/${a.player_id}` : a.team ? `#/teams/${a.team}` : "#/overview";
    return `<a class="it" href="${href}"><span class="mk ${a.kind}"></span><div><div>${html`${a.text}`}</div><div class="tiny muted">${a.kind === "live" ? "Live" : a.kind === "historical" ? "Result" : "Derived analytics"}</div></div></a>`; }).join("")}</div>` : stateEmpty("Quiet right now", "Activity appears as games tip off and form shifts.").toString();

  // ---- landscape scatter
  if (teams) {
    const all = teams.all, avg = teams.league_avg;
    const cvs = root.querySelector("#landscape");
    makeChart(cvs, (c) => ({
      type: "scatter",
      data: { datasets: [{ data: all.map((t) => ({ x: t.off_rating, y: t.def_rating, t })), backgroundColor: all.map((t) => teamColor(t)), borderColor: c.surface, borderWidth: 2, pointRadius: 7, pointHoverRadius: 10, pointLabels: all.map((t) => t.abbr), labelColors: all.map(() => c.text) }] },
      options: baseOptions(c, { interaction: { mode: "nearest", intersect: true }, onClick: (e, els) => { if (els.length) location.hash = `#/teams/${all[els[0].index].abbr}`; }, onHover: (e, els) => { e.native.target.style.cursor = els.length ? "pointer" : "default"; },
        plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, callbacks: { title: (i) => i[0].raw.t.name, label: (i) => [`ORtg ${i.raw.x}  ·  DRtg ${i.raw.y}`, `Net ${fmt.signed(i.raw.t.net_rating)}  ·  ${i.raw.t.w}-${i.raw.t.l}`] } } },
        scales: { x: axis(c, { title: { display: true, text: "Offensive rating →", color: c.text }, min: Math.floor(avg.off_rating - 8), max: Math.ceil(avg.off_rating + 8) }), y: axis(c, { reverse: true, title: { display: true, text: "← Better defense (lower DRtg)", color: c.text }, min: Math.floor(avg.def_rating - 8), max: Math.ceil(avg.def_rating + 8) }) } }),
      plugins: [plugins.pointLabels, { id: "avg", afterDatasetsDraw(ch) { const { ctx: g, chartArea: a, scales: { x, y } } = ch; g.save(); g.strokeStyle = c.grid; g.setLineDash([5, 5]); g.lineWidth = 1.5; g.beginPath(); const ax = x.getPixelForValue(avg.off_rating), ay = y.getPixelForValue(avg.def_rating); g.moveTo(ax, a.top); g.lineTo(ax, a.bottom); g.moveTo(a.left, ay); g.lineTo(a.right, ay); g.stroke(); g.fillStyle = c.text; g.font = "600 10.5px Inter"; g.setLineDash([]); g.fillText("Elite two-way", a.left + 8, a.top + 14); g.textAlign = "right"; g.fillText("Rebuilding", a.right - 8, a.bottom - 8); g.restore(); } }],
    }), charts);
    // power rankings
    const pr = root.querySelector("#power");
    const maxNet = Math.max(...teams.power_rankings.map((t) => Math.abs(t.net_rating || 0)), 1);
    sortableTable(pr, { rank: true, sortKey: "power_score", rows: teams.power_rankings.slice(0, 10), href: (t) => `#/teams/${t.abbr}`, columns: [
      { key: "name", label: "Team", sort: (t) => t.name, asc: true, render: (t) => html`<div class="ent">${teamLogo(t)}<div><b>${t.abbr}</b><small>${t.w}-${t.l}</small></div></div>` },
      { key: "net_rating", label: "Net", n: true, render: (t) => html`<span class="${t.net_rating >= 0 ? "pos" : "neg"}">${fmt.signed(t.net_rating)}</span>` },
      { key: "power_score", label: "Power", n: true, render: (t) => html`<div class="bar-cell"><div class="bar"><i style="width:${t.power_score}%"></i></div><b class="num">${fmt.num(t.power_score, 0)}</b></div>` },
      { key: "net_trend", label: "L10", n: true, title: "Last-10 net rating vs season", render: (t) => t.net_trend == null ? "—" : html`${trendArrow(t.net_trend)}` },
    ] });
  } else root.querySelector("#power").innerHTML = stateError({ message: "Team data unavailable." }).toString();

  // ---- featured performers
  const fe = root.querySelector("#featured");
  fe.innerHTML = players ? `<div class="list">${players.featured.map((p) => html`<a href="#/players/${p.id}"><div class="li">${face(p.id)}<div class="grow"><div class="t">${p.name}</div><div class="s">${p.team} · ${fmt.num(p.pts)} pts · ${fmt.num(p.reb)} reb · ${fmt.num(p.ast)} ast</div></div><div class="right"><b class="num">${fmt.num(p.pie)}</b><div class="tiny muted">PIE</div></div></div></a>`).join("")}</div>` : stateError({ message: "Player data unavailable." }).toString();

  // ---- leaders
  const lead = root.querySelector("#leaders"), ls = root.querySelector("#leader-seg");
  if (players) {
    const labels = { pts: "PTS", reb: "REB", ast: "AST", stl: "STL", blk: "BLK" };
    const draw = (k) => { lead.innerHTML = `<div class="list">${players.leaders[k].map((p, i) => html`<a href="#/players/${p.id}"><div class="li"><span class="rankno">${i + 1}</span>${face(p.id)}<div class="grow"><div class="t">${p.name}</div><div class="s">${p.team} · ${p.gp} GP</div></div><b class="num" style="font-size:18px">${fmt.num(p[k])}</b></div></a>`).join("")}</div>`; };
    ls.innerHTML = seg("lead", Object.entries(labels), "pts").toString(); draw("pts"); ctx.onCleanup(bindSeg(root, "lead", draw));
  }

  // ---- results / upcoming
  const sc = root.querySelector("#sched"), ss = root.querySelector("#sched-seg");
  if (d.schedule) {
    const row = (g) => html`<a href="#/games/${g.game_id}"><div class="li">${teamLogo(store.team(g.away.id), "sm")}<div class="grow"><div class="t">${g.away.abbr} @ ${g.home.abbr}</div><div class="s">${g.status === "final" ? `${g.away.score}–${g.home.score} · ${fmt.date(g.date)}` : `${fmt.date(g.date)} · ${fmt.time(g.start_utc)}`}</div></div>${g.prediction ? html`<div class="right"><b class="num">${fmt.prob(g.prediction.pick === g.home.abbr ? g.prediction.home : 1 - g.prediction.home)}</b><div class="tiny muted">${g.prediction.pick} · pred.</div></div>` : badge(g.status)}</div></a>`;
    const draw = (k) => { const list = k === "recent" ? d.schedule.recent : d.schedule.upcoming; sc.innerHTML = list.length ? `<div class="list">${list.map((g) => row(g)).join("")}</div>` : stateEmpty("Nothing to show", "").toString(); };
    ss.innerHTML = seg("sched", [["recent", "Results"], ["upcoming", "Upcoming"]], "recent").toString(); draw("recent"); ctx.onCleanup(bindSeg(root, "sched", draw));
  } else sc.innerHTML = stateError({ message: "Schedule unavailable." }).toString();
}
