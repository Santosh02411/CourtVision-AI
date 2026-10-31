import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw, esc } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt, hexA, pairColors } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions, plugins } from "../ui/charts.js";
import { pageHead, provenance, notices, gameCard, teamLogo, face, wpBar, statusBadge, sortableTable, seg, bindSeg, stateEmpty, stateError, skeletonPage, skeletonCards, aiBriefCard, loadBrief, kpi, animateCounts, badge, notice, bindTips } from "../ui/components.js";
import { gameShotMap } from "../ui/court.js";
import { predictionPanel, animateGauges } from "../ui/predviz.js";
import { setQuery } from "../core/router.js";

export default async function render(ctx) { return ctx.params.id ? detail(ctx, ctx.params.id) : picker(ctx); }

async function picker(ctx) {
  const { root } = ctx; let date = ctx.query.date || store.state.today;
  root.innerHTML = pageHead({ title: "Game Analytics", sub: "Pick any game to see win-probability swings, scoring runs, turning points, shot quality and an AI briefing." }).toString() + html`
    <div class="toolbar"><div class="field"><label>Date</label><div class="row gap-6"><button class="btn sm" id="prev" aria-label="Previous day">${raw(icon("left"))}</button><input type="date" class="input" id="date" value="${date}"><button class="btn sm" id="next" aria-label="Next day">${raw(icon("chevron"))}</button></div></div></div>
    <div id="notes"></div><div id="games">${skeletonCards(3)}</div><h3 style="margin:26px 0 12px">Recent completed games</h3><div id="recent">${skeletonCards(3)}</div>`.toString();
  const $ = (s) => root.querySelector(s);
  const load = async () => {
    try { const { data, meta } = await api("/scoreboard", { date }, { signal: ctx.signal }); $("#notes").innerHTML = notices(meta).toString();
      $("#games").innerHTML = data.games.length ? `<div class="games stagger">${data.games.map((g) => gameCard(g)).join("")}</div>` : stateEmpty("No games on this date", "Try another day or choose from the recent games below.", "calendar").toString();
    } catch (e) { if (e.name !== "AbortError") $("#games").innerHTML = stateError(e).toString(); }
  };
  const go = (d) => { date = d; $("#date").value = d; setQuery({ date: d }); load(); };
  $("#date").addEventListener("change", (e) => e.target.value && go(e.target.value)); $("#prev").addEventListener("click", () => go(fmt.addDays(date, -1))); $("#next").addEventListener("click", () => go(fmt.addDays(date, 1)));
  load();
  try { const today = store.state.today; const { data } = await api("/schedule", { status: "final", from: fmt.addDays(today, -10), to: today }, { signal: ctx.signal });
    const g = data.games.slice(-9).reverse(); $("#recent").innerHTML = g.length ? `<div class="games">${g.map((x) => gameCard(x)).join("")}</div>` : stateEmpty("No completed games found", "Games appear here once the season is underway.").toString();
  } catch (e) { if (e.name !== "AbortError") $("#recent").innerHTML = stateError(e).toString(); }
}

const tLabel = (t) => { if (t <= 2880) { const q = Math.min(3, Math.floor(t / 720)); const left = 720 - (t - q * 720); return `Q${q + 1} · ${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, "0")} left`; } const o = Math.floor((t - 2880) / 300), left = 300 - (t - 2880 - o * 300); return `OT${o + 1} · ${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, "0")} left`; };

async function detail(ctx, id) {
  const { root } = ctx, charts = []; let timer = null, first = true, shotTeam = "all", boxSide = "away";
  ctx.onCleanup(() => { disposeCharts(charts); clearInterval(timer); });
  root.innerHTML = skeletonPage(2).toString();
  const paint = (d, meta) => {
    disposeCharts(charts);
    const { home, away, boxscore: bx, impact: imp } = d, g = d.game || {}, live = d.status === "live", scheduled = d.status === "scheduled";
    const hs = bx?.home.score ?? g.home?.score, as = bx?.away.score ?? g.away?.score;
    const finalWp = imp?.summary?.final_home_win_prob;
    const hp = imp ? finalWp : null;
    root.innerHTML = html`<div class="crumbs"><a href="#/games">Game Analytics</a> ${raw(icon("chevron"))} <span>${away.abbr} @ ${home.abbr}</span></div>
      <div class="row between wrap" style="margin-bottom:14px"><div>${provenance(meta)}</div><div class="row">${live ? html`<span class="tiny muted">Auto-refreshing every 12 s</span>` : ""}<button class="btn sm" id="refresh">${raw(icon("refresh"))} Refresh</button></div></div>
      ${notices(meta)}
      <section class="card" style="margin-bottom:16px"><div class="scorebox">
        <div class="side">${teamLogo(away, "xl")}<b>${away.name}</b><span class="muted small">${g.away?.wins != null ? `${g.away.wins}-${g.away.losses}` : ""}</span></div>
        <div class="mid">${statusBadge({ ...g, status: d.status })}<div class="row gap-14" style="align-items:baseline"><span class="big" style="${as < hs ? "color:var(--text-3)" : ""}">${as ?? "–"}</span><span class="muted">–</span><span class="big" style="${hs < as ? "color:var(--text-3)" : ""}">${hs ?? "–"}</span></div>
          <span class="tiny muted">${g.arena || ""} ${g.date ? "· " + fmt.date(g.date) : ""}</span></div>
        <div class="side">${teamLogo(home, "xl")}<b>${home.name}</b><span class="muted small">${g.home?.wins != null ? `${g.home.wins}-${g.home.losses}` : ""}</span></div></div>
        ${hp != null ? html`<div style="padding:0 22px 18px">${wpBar(home, away, hp)}<div class="tiny muted center" style="margin-top:4px">${live ? "Current win probability (play-by-play model)" : "Win probability at the final play"} · model estimate</div></div>` : ""}</section>
      ${scheduled ? html`<div class="notice info">${raw(icon("info"))}<div>This game hasn't started. Below is the pre-game prediction; live analysis appears at tip-off.</div></div>${d.prediction ? predictionPanel(d.prediction) : stateEmpty("Prediction unavailable", "Team history couldn't be loaded.")}`
      : html`<div class="grid">
        <section class="card s8"><div class="card-h"><h3>${raw(icon("activity"))} Win probability timeline</h3><div class="legend"><span><i style="background:${pairColors(home, away)[0]}"></i>${home.abbr} win prob.</span><span><i style="background:${pairColors(home, away)[1]}"></i>${away.abbr}</span><span>◆ swing play</span></div></div><div class="card-b">${imp?.timeline?.length ? html`<div class="chart h380"><canvas id="wp"></canvas></div>` : stateEmpty("No play-by-play yet", "The timeline appears once the feed publishes events.")}</div>
          <div class="card-f">${badge("prediction", "Model estimate")} ${d.win_model?.trained_on === "synthetic" ? "Win-probability network is trained on synthetic game states" + (d.win_model.recalibrated_on_real ? " and recalibrated on real play-by-play." : " — see Models & Evaluation for real-world scores.") : ""}</div></section>
        <section class="col s4" style="gap:16px">${impactSummary(d)}</section>
        <section class="card s6"><div class="card-h"><h3>Game impact: biggest swings</h3><span class="tiny muted">Change in ${home.abbr} win prob.</span></div><div class="card-b flush">${swings(d)}</div></section>
        <section class="card s6"><div class="card-h"><h3>Scoring runs</h3></div><div class="card-b flush">${runs(d)}</div></section>
        <section class="card s6"><div class="card-h"><h3>Line score</h3></div><div class="card-b flush">${lineScore(d)}</div></section>
        <section class="card s6"><div class="card-h"><h3>Team comparison</h3></div><div class="card-b">${teamStats(d)}</div></section>
        <section class="card s12"><div class="card-h"><h3>Box score</h3>${seg("box", [["away", away.abbr], ["home", home.abbr]], boxSide)}</div><div class="card-b flush" id="box"></div></section>
        <section class="card s7"><div class="card-h"><h3>Shot map</h3>${seg("shotteam", [["all", "Both"], ["away", away.abbr], ["home", home.abbr]], shotTeam)}</div><div class="card-b" id="shotmap"></div><div class="card-f">${d.shot_model?.model || ""} · marker size = model xFG · ✕ miss · ● make</div></section>
        <section class="card s5"><div class="card-h"><h3>Shot making vs. expectation</h3></div><div class="card-b flush" id="shotsum"></div></section>
        <section class="s12">${aiBriefCard()}</section></div>`}`.toString();
    root.querySelector("#refresh")?.addEventListener("click", () => load(true));
    bindTips(root);
    if (scheduled) { animateGauges(root); return; }
    // chart
    if (imp?.timeline?.length) {
      const tl = imp.timeline, lastT = tl[tl.length - 1].t, maxT = Math.max(2880, Math.ceil(lastT / 300) * 300);
      makeChart(root.querySelector("#wp"), (c) => {
        const [hc, ac] = pairColors(home, away);
        return { type: "line", data: { datasets: [
          { label: "wp", data: tl.map((p) => ({ x: p.t, y: p.wp, p })), parsing: false, borderColor: hc, borderWidth: 2.2, pointRadius: 0, tension: 0.12, fill: { target: { value: 0.5 }, above: hexA(hc, 0.2), below: hexA(ac, 0.22) }, order: 2 },
          { type: "scatter", label: "swing", data: imp.swings.map((s) => ({ x: s.t, y: s.wp_after, s })), pointStyle: "rectRot", pointRadius: imp.swings.map((s) => (s.big ? 8 : 5)), pointHoverRadius: 10, backgroundColor: imp.swings.map((s) => (s.favors === home.abbr ? hc : ac)), borderColor: c.surface, borderWidth: 2, order: 1 }] },
          options: baseOptions(c, { animation: first ? undefined : false, interaction: { mode: "nearest", axis: "x", intersect: false },
            plugins: { legend: { display: false }, tooltip: { ...baseOptions(c).plugins.tooltip, filter: (i) => true, callbacks: { title: (i) => tLabel(i[0].raw.x), label: (i) => i.raw.s ? [`◆ ${i.raw.s.desc}`, `${fmt.signed(i.raw.s.delta_pp)} pp for ${home.abbr} (${i.raw.s.favors} swing)`] : [`${home.abbr} win prob. ${fmt.prob(i.raw.y, 1)}`, `Score ${away.abbr} ${i.raw.p.a} – ${i.raw.p.h} ${home.abbr}`] } } },
            scales: { x: axis(c, { type: "linear", min: 0, max: maxT, ticks: { stepSize: 720, callback: (v) => ({ 0: "Tip", 720: "Q2", 1440: "Q3", 2160: "Q4", 2880: "End Q4" }[v] || (v > 2880 && (v - 2880) % 300 === 0 ? `OT${(v - 2880) / 300}` : "")) }, grid: { display: false } }),
              y: axis(c, { min: 0, max: 1, ticks: { stepSize: 0.25, callback: (v) => (v === 1 ? `${home.abbr} 100%` : v === 0 ? `${away.abbr} 100%` : `${v * 100}%`) } }) } }),
          plugins: [plugins.quarterLines(false), plugins.midLine(0.5, c.border)] };
      }, charts);
    }
    // box score
    const drawBox = () => { const side = bx[boxSide]; sortableTable(root.querySelector("#box"), { sortKey: "pts", rows: side.players, columns: [
      { key: "name", label: "Player", asc: true, render: (p) => html`<div class="ent">${face(p.id)}<div><b>${p.name}</b><small>${p.position || ""} ${p.starter ? "· Starter" : ""} ${p.oncourt ? "· On court" : ""}</small></div></div>` },
      { key: "min", label: "MIN", n: true, render: (p) => fmt.num(p.min, 0) }, { key: "pts", label: "PTS", n: true, render: (p) => html`<b>${p.pts}</b>` }, { key: "reb", label: "REB", n: true }, { key: "ast", label: "AST", n: true }, { key: "stl", label: "STL", n: true }, { key: "blk", label: "BLK", n: true }, { key: "tov", label: "TOV", n: true },
      { key: "fga", label: "FG", n: true, render: (p) => `${p.fgm}-${p.fga}` }, { key: "fg3a", label: "3P", n: true, render: (p) => `${p.fg3m}-${p.fg3a}` }, { key: "fta", label: "FT", n: true, render: (p) => `${p.ftm}-${p.fta}` },
      { key: "plus_minus", label: "+/−", n: true, render: (p) => html`<span class="${p.plus_minus > 0 ? "pos" : p.plus_minus < 0 ? "neg" : ""}">${fmt.signed(p.plus_minus, 0)}</span>` }], href: (p) => `#/players/${p.id}` }); };
    if (bx) { drawBox(); ctx.onCleanup(bindSeg(root, "box", (v) => { boxSide = v; drawBox(); })); }
    // shots
    const [pc0, pc1] = pairColors(home, away); const teamsById = { [home.id]: { ...home, primary: pc0 }, [away.id]: { ...away, primary: pc1 } };
    const drawShots = () => { const list = d.shots.filter((s) => shotTeam === "all" || s.team_id === (shotTeam === "home" ? home.id : away.id)); root.querySelector("#shotmap").innerHTML = list.length ? gameShotMap(list, teamsById).toString() : stateEmpty("No located shots yet", "").toString(); };
    drawShots(); ctx.onCleanup(bindSeg(root, "shotteam", (v) => { shotTeam = v; drawShots(); }));
    root.querySelector("#shotsum").innerHTML = shotSummary(d);
    if (first) loadBrief(root, api, { type: "game", id }); first = false;
    animateCounts(root);
  };
  const load = async (force = false) => {
    try { const { data, meta } = await api(`/games/${id}`, {}, { signal: ctx.signal, ttl: 8000, force }); paint(data, meta);
      clearInterval(timer); if (data.status === "live") timer = setInterval(() => load(true), 12000);
    } catch (e) { if (e.name === "AbortError") return; root.innerHTML = stateError(e, true).toString(); root.querySelector("[data-retry]")?.addEventListener("click", () => load(true)); }
  };
  await load();
}

function impactSummary(d) {
  const imp = d.impact; if (!imp?.summary) return html`<section class="card"><div class="card-b">${stateEmpty("Impact analysis unavailable", "Play-by-play wasn't available.")}</div></section>`;
  const s = imp.summary, tp = imp.turning_point, h = d.home, a = d.away;
  return html`<section class="card"><div class="card-h"><h3>${raw(icon("flame"))} Turning point</h3>${badge("prediction", "Model estimate")}</div><div class="card-b">${tp ? html`<div style="font-size:24px;font-weight:750;letter-spacing:-.02em">${tp.swing_pp} pp swing <span class="muted" style="font-size:14px;font-weight:500">toward</span> ${tp.favors}</div><p class="small t2" style="margin:6px 0 0">Q${tp.start.period} ${tp.start.clock} (${tp.start.score}) → Q${tp.end.period} ${tp.end.clock} (${tp.end.score}). The strongest 5-minute shift in win probability.</p>` : html`<p class="small muted" style="margin:0">No decisive 5-minute swing (≥5 pp) — the game stayed balanced or one-sided throughout.</p>`}</div></section>
    <section class="card"><div class="card-h"><h3>Game flow</h3></div><div class="card-b"><div class="metric"><span>Lead changes</span><b>${s.lead_changes}</b></div><div class="metric"><span>Largest lead</span><b>${a.abbr} ${s.largest_away_lead} · ${h.abbr} ${s.largest_home_lead}</b></div>
      <div class="metric"><span>${h.abbr} win prob. range</span><b>${fmt.prob(s.min_home_win_prob)} – ${fmt.prob(s.max_home_win_prob)}</b></div>
      ${s.winner_lowest_win_prob != null ? html`<div class="metric"><span>Winner's lowest win prob.</span><b>${s.winner} · ${fmt.prob(s.winner_lowest_win_prob)}</b></div>` : ""}
      ${s.clutch_leverage != null ? html`<div class="metric"><span title="Average absolute win-prob change per play">Clutch leverage</span><b>${s.clutch_leverage} pp/play <span class="muted tiny">vs ${s.avg_leverage ?? "—"}</span></b></div>` : ""}</div></section>`;
}
const swings = (d) => { const s = d.impact?.swings || []; if (!s.length) return stateEmpty("No swing plays yet", "").toString(); return `<div>${s.slice().sort((x, y) => Math.abs(y.delta_pp) - Math.abs(x.delta_pp)).map((x) => html`<div class="swing"><span class="tm">Q${x.period} ${x.clock}</span><div><div style="font-weight:550;white-space:normal">${x.desc}</div><div class="tiny muted">${x.score} · ${x.wp_before != null ? `${fmt.prob(x.wp_before)} → ${fmt.prob(x.wp_after)}` : ""}</div></div><span class="d" style="color:${x.favors === d.home.abbr ? d.home.primary : d.away.primary}">${fmt.signed(x.delta_pp)}</span></div>`).join("")}</div>`; };
const runs = (d) => { const r = d.impact?.runs || []; if (!r.length) return stateEmpty("No runs of 7+ points", "").toString(); return `<div>${r.map((x) => html`<div class="swing"><span class="tm">${x.team}</span><div><b>${x.points}-0 run</b><div class="tiny muted">Q${x.period_start} ${x.clock_start} → Q${x.period_end} ${x.clock_end}</div></div><span class="d">${fmt.signed(x.wp_swing_pp)} pp</span></div>`).join("")}</div>`; };
function lineScore(d) { const bx = d.boxscore, n = Math.max(bx.home.periods.length, bx.away.periods.length, 4); const hd = Array.from({ length: n }, (_, i) => (i < 4 ? `Q${i + 1}` : `OT${i - 3}`));
  const row = (t, side) => html`<tr><td><div class="ent">${teamLogo(t, "sm")}<b>${t.abbr}</b></div></td>${Array.from({ length: n }, (_, i) => html`<td class="num">${side.periods[i] ?? "–"}</td>`)}<td class="num"><b>${side.score}</b></td></tr>`;
  return html`<table class="tbl qtbl"><thead><tr><th></th>${hd.map((h) => html`<th>${h}</th>`)}<th>T</th></tr></thead><tbody>${row(d.away, bx.away)}${row(d.home, bx.home)}</tbody></table>`.toString(); }
function teamStats(d) { const h = d.boxscore.home.stats, a = d.boxscore.away.stats; const rows = [["fg_pct", "FG%", 1], ["fg3_pct", "3P%", 1], ["ft_pct", "FT%", 1], ["reb", "Rebounds"], ["ast", "Assists"], ["tov", "Turnovers"], ["stl", "Steals"], ["blk", "Blocks"], ["paint", "Points in paint"], ["fast_break", "Fast-break pts"], ["second_chance", "2nd-chance pts"], ["bench", "Bench pts"], ["biggest_lead", "Biggest lead"]];
  return rows.filter(([k]) => h[k] != null || a[k] != null).map(([k, l, p]) => { const hv = h[k] ?? 0, av = a[k] ?? 0, tot = hv + av || 1; return html`<div class="statline"><span class="v">${p ? fmt.pct(av) : av}</span><span class="lab">${l}</span><span class="v">${p ? fmt.pct(hv) : hv}</span><div class="sb"><i style="width:${(av / tot) * 100}%;background:${pairColors(d.home, d.away)[1]}"></i><i style="width:${(hv / tot) * 100}%;background:${pairColors(d.home, d.away)[0]}"></i></div></div>`; }).join(""); }
function shotSummary(d) { const rows = [d.away, d.home].map((t) => { const s = d.shots.filter((x) => x.team_id === t.id); const fga = s.length, fgm = s.filter((x) => x.made).length, x = s.reduce((a, b) => a + b.quality, 0); return { t, fga, fgm, pct: fga ? (100 * fgm) / fga : null, xfg: fga ? (100 * x) / fga : null, diff: fgm - x }; });
  if (!rows.some((r) => r.fga)) return stateEmpty("No shot locations yet", "").toString();
  return html`<table class="tbl"><thead><tr><th>Team</th><th class="n">FGA</th><th class="n">FG%</th><th class="n">xFG%</th><th class="n" title="Makes minus model-expected makes">Shot making</th></tr></thead><tbody>${rows.map((r) => html`<tr><td><div class="ent">${teamLogo(r.t, "sm")}<b>${r.t.abbr}</b></div></td><td class="n">${r.fga}</td><td class="n">${fmt.pct(r.pct)}</td><td class="n">${fmt.pct(r.xfg)}</td><td class="n ${r.diff >= 0 ? "pos" : "neg"}"><b>${fmt.signed(r.diff)}</b></td></tr>`)}</tbody></table><div class="tiny muted" style="padding:10px 16px">Compares actual makes with the shot-quality model's expectation for the same attempts. Positive = shot-making above what the locations predict.</div>`.toString(); }
