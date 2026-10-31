const listeners = new Map();
const state = { season: null, currentSeason: null, theme: "dark", meta: null, teams: [], teamsById: {}, teamsByAbbr: {}, live: { games: [], status: "unknown", at: 0 }, dataStatus: { status: "unknown", text: "Connecting" } };
const safe = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable (private mode) */ } },
};
export const store = {
  state,
  get(k) { return state[k]; },
  set(k, v) { state[k] = v; (listeners.get(k) || []).forEach((fn) => fn(v)); },
  on(k, fn) { if (!listeners.has(k)) listeners.set(k, []); listeners.get(k).push(fn); return () => listeners.set(k, listeners.get(k).filter((f) => f !== fn)); },
  persisted: safe,
  initTheme() { state.theme = document.documentElement.getAttribute("data-theme") || "dark"; },
  setTheme(t) {
    state.theme = t; document.documentElement.setAttribute("data-theme", t); safe.set("cv.theme", t);
    const m = document.getElementById("meta-theme"); if (m) m.setAttribute("content", t === "light" ? "#f4f5f7" : "#07080a");
    (listeners.get("theme") || []).forEach((fn) => fn(t));
  },
  setMeta(meta) {
    state.meta = meta; state.teams = meta.teams; state.currentSeason = meta.current_season; state.today = meta.today;
    state.teamsById = Object.fromEntries(meta.teams.map((t) => [t.id, t])); state.teamsByAbbr = Object.fromEntries(meta.teams.map((t) => [t.abbr, t]));
    const saved = safe.get("cv.season");
    state.season = meta.seasons.includes(saved) ? saved : meta.current_season;
  },
  setSeason(s) { state.season = s; safe.set("cv.season", s); (listeners.get("season") || []).forEach((fn) => fn(s)); },
  team(x) { return state.teamsByAbbr[x] || state.teamsById[x] || null; },
};
