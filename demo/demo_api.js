// Demo-mode replacement for core/api.js: serves snapshots of the real backend's output (generated from test fixtures).
// Filtering/aggregation that the server normally does for interactive controls (shots, compare, search, schedule) is ported here.
import { store } from "./store.js";

export class ApiFailure extends Error {
  constructor(message, code = "error", status = 0, meta = {}) { super(message); this.code = code; this.status = status; this.meta = meta; }
}
export const clearApiCache = () => {};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let D = null, live = null;
const r1 = (v) => Math.round(v * 10) / 10;

// ---------------------------------------------------------------- simulated live game (win prob from the real model's grid)
function wpFromGrid(diff, tr) {
  const g = D.wpGrid, di = Math.max(0, Math.min(g.diffs.length - 1, Math.round((diff - g.diffs[0]) / g.dstep))), ti = Math.max(0, Math.min(g.trs.length - 1, Math.round(tr / g.tstep)));
  return g.values[di][ti];
}
function initLive() {
  const g = D.liveGame; if (!g) return;
  live = { id: g.game_id, home: g.home.score, away: g.away.score, period: g.period || 3, sec: 312, final: false };
  setInterval(() => {
    if (live.final) return;
    live.sec -= 15 + Math.random() * 30;
    if (Math.random() < 0.75) { const pts = Math.random() < 0.3 ? 3 : 2; if (Math.random() < 0.5) live.home += pts; else live.away += pts; }
    if (live.sec <= 0) { if (live.period >= 4 && live.home !== live.away) { live.final = true; live.sec = 0; } else { live.period++; live.sec = live.period > 4 ? 300 : 720; } }
  }, 5000);
}
const clockIso = (s) => `PT${String(Math.floor(s / 60)).padStart(2, "0")}M${(s % 60).toFixed(2).padStart(5, "0")}S`;
function overlay(g) {
  if (!live || !g || g.game_id !== live.id) return g;
  const tr = live.period <= 4 ? (4 - live.period) * 720 + live.sec : live.sec, m = Math.floor(live.sec / 60), s = String(Math.floor(live.sec % 60)).padStart(2, "0");
  if (live.final) return { ...g, status: "final", status_text: "Final", home: { ...g.home, score: live.home }, away: { ...g.away, score: live.away }, live_wp: null };
  return { ...g, status: "live", status_text: `Q${live.period} ${m}:${s}`, period: live.period, clock: clockIso(live.sec), home: { ...g.home, score: live.home }, away: { ...g.away, score: live.away }, live_wp: wpFromGrid(live.home - live.away, tr) };
}

// ---------------------------------------------------------------- ports of server-side helpers
const METRICS = [["pts", "PTS", 1], ["reb", "REB", 1], ["ast", "AST", 1], ["stl", "STL", 1], ["blk", "BLK", 1], ["tov", "TOV", 0], ["fg_pct", "FG%", 1], ["fg3_pct", "3P%", 1], ["ft_pct", "FT%", 1], ["ts_pct", "TS%", 1], ["usg_pct", "USG%", 1], ["pie", "PIE", 1], ["net_rating", "Net Rtg", 1], ["min", "MIN", 1]];
function compare(a, b) {
  const pa = D.profiles[a]?.player, pb = D.profiles[b]?.player;
  if (!pa || !pb) throw new ApiFailure("Player not found for this season.", "player_not_found", 404);
  const metrics = METRICS.map(([k, label, hi]) => { const va = pa[k], vb = pb[k]; const edge = va == null || vb == null || va === vb ? null : ((va > vb) === !!hi ? "a" : "b"); return { key: k, label, a: va, b: vb, edge }; });
  const recent = (id) => { const f = D.profiles[id].form; return f ? { games: f.games.slice(-15).map((g) => ({ date: g.date, pts: g.pts, reb: g.reb, ast: g.ast })), summary: f.summary } : null; };
  return { a: pa, b: pb, radar_axes: D.meta.radar, metrics, edges: { a: metrics.filter((m) => m.edge === "a").length, b: metrics.filter((m) => m.edge === "b").length }, recent: { a: recent(a), b: recent(b) } };
}
const ZONE_ORDER = ["Restricted Area", "In The Paint (Non-RA)", "Mid-Range", "Left Corner 3", "Right Corner 3", "Above the Break 3", "Backcourt"];
const BUCKETS = [[0, 3, "0-3 ft"], [4, 9, "4-9 ft"], [10, 15, "10-15 ft"], [16, 21, "16-21 ft"], [22, 23, "22-23 ft"], [24, 99, "24+ ft"]];
function shots(pid, p) {
  const raw = D.shots[pid]; if (!raw) throw new ApiFailure("No shot chart for this player in the demo.", "no_shots", 404);
  const periods = (p.period || "").split(",").filter(Boolean).map(Number).filter(Boolean), num = (v) => (v === "" || v == null || Number.isNaN(+v) ? null : +v);
  const dmin = num(p.dmin), dmax = num(p.dmax), lastN = num(p.last_n) || 0;
  if (p.type && !["2", "3"].includes(p.type)) throw new ApiFailure("type must be 2 or 3.", "invalid_filter", 400);
  if (p.result && !["made", "missed"].includes(p.result)) throw new ApiFailure("result must be made or missed.", "invalid_filter", 400);
  const Z = D.zones;
  // shot = [x, y, made, dist, period, xfg, three, zoneIdx, gameRank]
  let rows = raw.s.filter((s) => (!lastN || s[8] < lastN) && (!periods.length || periods.includes(s[4])) && (!p.type || s[6] === (p.type === "3" ? 1 : 0)) && (!p.result || s[2] === (p.result === "made" ? 1 : 0)) && (dmin == null || s[3] >= dmin) && (dmax == null || s[3] <= dmax) && (!p.zone || Z[s[7]] === p.zone));
  const out = { total_unfiltered: raw.s.length };
  if (!rows.length) return { ...out, empty: true, totals: { fga: 0, fgm: 0 } };
  const fga = rows.length, fgm = rows.reduce((a, s) => a + s[2], 0), th = rows.filter((s) => s[6] === 1), thM = th.reduce((a, s) => a + s[2], 0);
  const xs = rows.reduce((a, s) => a + s[5], 0), efg = (fgm + 0.5 * thM) / fga;
  const totals = { fga, fgm, fg_pct: r1((100 * fgm) / fga), efg_pct: r1(100 * efg), fg3a: th.length, fg3_pct: th.length ? r1((100 * thM) / th.length) : null, avg_distance: r1(rows.reduce((a, s) => a + s[3], 0) / fga), xfg_pct: r1((100 * xs) / fga), shot_making: r1(fgm - xs) };
  const lg = {}; D.leagueAvg.forEach((r) => { const k = r.shot_zone_basic; (lg[k] ||= [0, 0]); lg[k][0] += r.fga || 0; lg[k][1] += r.fgm || 0; });
  const by = {}; rows.forEach((s) => (by[Z[s[7]]] ||= []).push(s));
  const zones = Object.entries(by).map(([z, g]) => { const a = g.length, m = g.reduce((t, s) => t + s[2], 0), lp = lg[z] && lg[z][0] ? (100 * lg[z][1]) / lg[z][0] : null;
    return { zone: z, fga: a, fgm: m, fg_pct: r1((100 * m) / a), freq_pct: r1((100 * a) / fga), league_fg_pct: lp == null ? null : r1(lp), diff: lp == null ? null : r1((100 * m) / a - lp), xfg_pct: r1((100 * g.reduce((t, s) => t + s[5], 0)) / a) }; })
    .sort((a, b) => (ZONE_ORDER.indexOf(a.zone) + 1 || 99) - (ZONE_ORDER.indexOf(b.zone) + 1 || 99));
  const buckets = BUCKETS.map(([lo, hi, label]) => { const g = rows.filter((s) => s[3] >= lo && s[3] < hi + 1); return g.length ? { label, fga: g.length, fg_pct: r1((100 * g.reduce((t, s) => t + s[2], 0)) / g.length), xfg_pct: r1((100 * g.reduce((t, s) => t + s[5], 0)) / g.length) } : null; }).filter(Boolean);
  const cells = {}; rows.forEach((s) => { const cx = Math.floor(s[0] / 30), cy = Math.floor(s[1] / 30), k = cx + "," + cy; (cells[k] ||= { x: cx * 30 + 15, y: cy * 30 + 15, fga: 0, fgm: 0 }); cells[k].fga++; cells[k].fgm += s[2]; });
  const per = {}; rows.forEach((s) => (per[s[4]] ||= []).push(s));
  return { ...out, empty: false, totals, zones, distance_buckets: buckets, bins: Object.values(cells), shots: rows.map((s) => [s[0], s[1], s[2], s[3], s[4], s[5]]), shots_sampled: false,
    by_period: Object.keys(per).map(Number).sort((a, b) => a - b).map((k) => ({ period: k, fga: per[k].length, fg_pct: r1((100 * per[k].reduce((t, s) => t + s[2], 0)) / per[k].length) })), model: D.shotModel };
}
function playersList(p) {
  let rows = D.playerRows.slice();
  if (p.team) rows = rows.filter((r) => r.team === p.team);
  const q = (p.q || "").toLowerCase(); if (q) rows = rows.filter((r) => (r.name || "").toLowerCase().includes(q));
  if (p.qualified !== "0") rows = rows.filter((r) => r.qualified);
  const sort = p.sort || "pie", desc = p.order !== "asc";
  rows.sort((a, b) => sort === "name" ? (desc ? -1 : 1) * (a.name || "").localeCompare(b.name || "") : (a[sort] == null) - (b[sort] == null) || (desc ? -1 : 1) * ((a[sort] ?? 0) - (b[sort] ?? 0)));
  const limit = Math.max(1, Math.min(600, +p.limit || 60));
  return { players: rows.slice(0, limit), total: rows.length, qualification: D.qualification };
}
const hydrate = (m) => ({ ...m, home: D.teamsByAbbr[m.home], away: D.teamsByAbbr[m.away], model: D.matchModel });
function schedule(p) {
  let g = D.schedule; const team = p.team;
  if (team) g = g.filter((x) => x.home.abbr === team || x.away.abbr === team);
  const from = p.from || "0000", to = p.to || "9999";
  g = g.filter((x) => x.date >= from && x.date <= to && (!p.status || x.status === p.status));
  return { games: g.slice(0, 400).map(overlay), from, to, season: D.season };
}
function brief(p) {
  let key;
  if (p.type === "matchup") key = `m:${p.home}-${p.away}`; else if (p.type === "player") key = `p:${p.id}`; else if (p.type === "team") key = `t:${p.id}`; else if (p.type === "game") key = `g:${p.id}`;
  else throw new ApiFailure("type must be one of matchup, player, team, game.", "invalid_type", 400);
  const b = D.briefs[key]; if (!b) throw new ApiFailure("No briefing available for this selection in the demo.", "not_found", 404);
  return { ...b, note: "Demo data - rule-based summary of computed facts." };
}
function search(q) {
  q = (q || "").trim().toLowerCase(); if (q.length < 2) return { teams: [], players: [] };
  return { teams: D.meta.teams.filter((t) => t.name.toLowerCase().includes(q) || t.abbr.toLowerCase() === q).slice(0, 5),
    players: D.playerRows.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8).map((p) => ({ id: p.id, name: p.name, team: p.team, pts: p.pts, headshot: p.headshot })) };
}

function route(path, p) {
  const nf = (m) => new ApiFailure(m, "not_found", 404);
  if (path === "/meta") return D.meta;
  if (path === "/health") return { status: "ok", demo: true };
  if (path === "/overview") { const o = JSON.parse(JSON.stringify(D.overview)); o.today = (D.scoreboard[D.today]?.games || []).map(overlay); o.activity = o.activity.map((a) => { const g = o.today.find((x) => x.game_id === a.game_id); return a.type === "live" && g ? { ...a, text: g.status === "live" ? `${g.away.abbr} ${g.away.score} - ${g.home.abbr} ${g.home.score}  ·  ${g.status_text}` : `Final: ${g.away.abbr} ${g.away.score} - ${g.home.abbr} ${g.home.score}` } : a; }); return o; }
  if (path === "/scoreboard") { const d = p.date || D.today, s = D.scoreboard[d] || { date: d, games: [], live_count: 0 }; const games = s.games.map(overlay); return { ...s, games, live_count: games.filter((g) => g.status === "live").length }; }
  if (path === "/schedule") return schedule(p);
  let m;
  if ((m = /^\/games\/(\w+)$/.exec(path))) { const g = D.games[m[1]]; if (!g) throw nf("Game not found in the demo schedule."); return g.game ? { ...g, game: overlay(g.game), status: overlay(g.game).status === "live" ? "live" : g.status } : g; }
  if (path === "/standings") return D.standings;
  if (path === "/teams") return D.teams;
  if ((m = /^\/teams\/(\w+)$/.exec(path))) { const t = D.teamDetail[m[1].toUpperCase()]; if (!t) throw nf("Unknown team."); return t; }
  if (path === "/players") return playersList(p);
  if (path === "/players/compare") { const a = +p.a, b = +p.b; if (!a || !b || a === b) throw new ApiFailure("Provide two different player ids as ?a=&b=.", "invalid_players", 400); return compare(a, b); }
  if ((m = /^\/players\/(\d+)\/shots$/.exec(path))) return shots(m[1], p);
  if ((m = /^\/players\/(\d+)$/.exec(path))) { const pr = D.profiles[m[1]]; if (!pr) throw nf("Player has no recorded stats for this season."); return pr; }
  if (path === "/predictions/slate") { const s = D.slates[p.date || D.today] || { date: p.date || D.today, games: [] }; return { ...s, games: s.games.map((e) => ({ ...e, game: overlay(e.game) })) }; }
  if (path === "/predictions/matchup") { if (p.home === p.away) throw new ApiFailure("Pick two different teams.", "invalid_matchup", 400); const x = D.matchups[`${p.home}-${p.away}`]; if (!x) throw new ApiFailure("Unknown or missing team.", "invalid_team", 400); return hydrate(x); }
  if (path === "/models") return D.models;
  if (path === "/ai/brief") return brief(p);
  if (path === "/search") return search(p.q);
  if (path === "/news") return D.news;
  throw nf("Endpoint not available in the demo.");
}

export async function api(path, params = {}, { signal } = {}) {
  D ||= window.__CV_DATA; if (!live && D.liveGame) initLive();
  await sleep(70 + Math.random() * 130);
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const p = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)]));
  const data = route(path, p);
  store.set("dataStatus", { status: "cached", text: "Demo data" });
  const kind = path.startsWith("/predictions") ? "prediction" : /^\/(scoreboard|schedule|overview|games)/.test(path) ? "live" : path === "/models" ? "model" : /ai\/|search/.test(path) ? "derived" : "historical";
  return { ok: true, data, meta: { kind, season: D.season, status: "fresh", generated_at: new Date().toISOString(), notes: [], sources: [{ source: "Demo fixture data", status: "fresh", age_seconds: 0 }] } };
}
