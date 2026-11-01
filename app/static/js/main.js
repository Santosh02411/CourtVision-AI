import { api } from "./core/api.js";
import { store } from "./core/store.js";
import { route, startRouter, navigate } from "./core/router.js";
import { html, raw, $, $$, delegate, esc, debounce } from "./core/dom.js";
import { NAV, icon } from "./ui/icons.js";
import { teamLogo, face, toast, stateError } from "./ui/components.js";
import { fmt } from "./ui/format.js";

const PAGES = {
  overview: () => import("./pages/overview.js"), live: () => import("./pages/live.js"), games: () => import("./pages/game.js"),
  predictions: () => import("./pages/predictions.js"), players: () => import("./pages/players.js"), player: () => import("./pages/player.js"),
  compare: () => import("./pages/compare.js"), shots: () => import("./pages/shots.js"), teams: () => import("./pages/teams.js"),
  team: () => import("./pages/team.js"), standings: () => import("./pages/standings.js"), schedule: () => import("./pages/schedule.js"), models: () => import("./pages/models.js"),
};
route("/", () => PAGES.overview(), "overview");
route("/overview", () => PAGES.overview(), "overview");
route("/live", () => PAGES.live(), "live");
route("/games", () => PAGES.games(), "games");
route("/games/:id", () => PAGES.games(), "games");
route("/predictions", () => PAGES.predictions(), "predictions");
route("/players", () => PAGES.players(), "players");
route("/players/:id", () => PAGES.player(), "players");
route("/compare", () => PAGES.compare(), "compare");
route("/shots", () => PAGES.shots(), "shots");
route("/teams", () => PAGES.teams(), "teams");
route("/teams/:abbr", () => PAGES.team(), "teams");
route("/standings", () => PAGES.standings(), "standings");
route("/schedule", () => PAGES.schedule(), "schedule");
route("/models", () => PAGES.models(), "models");
route("/:any", () => import("./pages/notfound.js"), "notfound");

function renderNav(active) {
  $("#nav").innerHTML = NAV.map((n) => n.group ? `<div class="nav-group">${esc(n.group)}</div>`
    : `<a href="${n.href}" data-id="${n.id}" class="${n.id === active ? "active" : ""}" ${n.id === active ? 'aria-current="page"' : ""} title="${esc(n.label)}">${icon(n.icon)}<span class="nav-lbl">${esc(n.label)}</span></a>`).join("");
}

function setupTopbar(meta) {
  $("#menu-btn").innerHTML = icon("menu");
  $("[data-icon=search]").outerHTML = icon("search");
  const themeBtn = $("#theme-btn");
  const paint = () => { themeBtn.innerHTML = icon(store.state.theme === "dark" ? "sun" : "moon"); themeBtn.title = `Switch to ${store.state.theme === "dark" ? "light" : "dark"} theme`; };
  paint(); themeBtn.addEventListener("click", () => { store.setTheme(store.state.theme === "dark" ? "light" : "dark"); paint(); });
  const sel = $("#season-select");
  sel.innerHTML = meta.seasons.map((s) => `<option value="${s}" ${s === store.state.season ? "selected" : ""}>${s}${s === meta.current_season ? " (current)" : ""}</option>`).join("");
  sel.addEventListener("change", () => { store.setSeason(sel.value); $("#season-foot").textContent = sel.value; });
  $("#season-foot").textContent = store.state.season;
  const ai = $("#ai-pill"); ai.innerHTML = `${icon("sparkles")}<span>AI analyst: ${{ gemini: "Gemini", claude: "Claude" }[meta.ai_analyst.mode] || "rule-based"}</span>`;
  const sb = $("#sidebar");
  $("#menu-btn").addEventListener("click", () => sb.classList.toggle("open"));
  $("#nav").addEventListener("click", () => sb.classList.remove("open"));
  store.on("dataStatus", ({ status, text }) => { const p = $("#data-pill"); p.className = `data-pill ${status}`; $("#data-pill-text").textContent = text; });
}

// ---- command palette ---------------------------------------------------------------
function openPalette() {
  const ov = $("#overlay"); ov.hidden = false;
  ov.innerHTML = `<div class="cmdk" role="dialog" aria-modal="true" aria-label="Search"><input id="cmdk-in" placeholder="Search players, teams, pages…" autocomplete="off" spellcheck="false"><div class="cmdk-list" id="cmdk-list"></div><div class="cmdk-foot"><span>↑↓ navigate</span><span>↵ open</span><span>esc close</span></div></div>`;
  const input = $("#cmdk-in"), list = $("#cmdk-list"); let items = [], sel = 0, seq = 0;
  const pages = NAV.filter((n) => !n.group).map((n) => ({ type: "Pages", label: n.label, href: n.href, ic: n.icon }));
  const draw = () => {
    let last = ""; list.innerHTML = items.length ? items.map((it, i) => `${it.type !== last ? `<div class="cmdk-sec">${last = it.type}</div>` : ""}<div class="cmdk-it ${i === sel ? "sel" : ""}" data-i="${i}">${it.html || icon(it.ic || "chevron")}<div class="grow"><b>${esc(it.label)}</b>${it.sub ? `<div class="tiny muted">${esc(it.sub)}</div>` : ""}</div></div>`).join("") : `<div class="state"><p>No matches. Try a player or team name.</p></div>`;
  };
  const compute = async (q) => {
    const me = ++seq, ql = q.trim().toLowerCase();
    items = pages.filter((p) => !ql || p.label.toLowerCase().includes(ql)).slice(0, ql ? 4 : 13);
    if (ql.length >= 2) {
      const teams = store.state.teams.filter((t) => t.name.toLowerCase().includes(ql) || t.abbr.toLowerCase() === ql).slice(0, 5).map((t) => ({ type: "Teams", label: t.name, sub: `${t.conference}ern Conference`, href: `#/teams/${t.abbr}`, html: teamLogo(t, "sm").toString() }));
      items = [...teams, ...items]; draw();
      try { const { data } = await api("/search", { q: ql, season: store.state.season }, { ttl: 60000 }); if (me !== seq) return;
        const players = data.players.map((p) => ({ type: "Players", label: p.name, sub: `${p.team} · ${fmt.num(p.pts)} PPG`, href: `#/players/${p.id}`, html: face(p.id).toString() }));
        items = [...teams, ...players, ...items.filter((i) => i.type === "Pages")]; } catch { /* palette still works for teams/pages */ }
    }
    sel = 0; draw();
  };
  const close = () => { ov.hidden = true; ov.innerHTML = ""; document.removeEventListener("keydown", onKey, true); };
  const go = (i) => { const it = items[i]; if (it) { close(); location.hash = it.href.slice(1); } };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); draw(); $(".cmdk-it.sel", list)?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); draw(); $(".cmdk-it.sel", list)?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); go(sel); }
  };
  document.addEventListener("keydown", onKey, true);
  input.addEventListener("input", debounce(() => compute(input.value), 140));
  list.addEventListener("click", (e) => { const it = e.target.closest(".cmdk-it"); if (it) go(+it.dataset.i); });
  ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); }, { once: true });
  compute(""); input.focus();
}

// ---- live scoreboard (socket + ticker) ---------------------------------------------
function renderTicker(games) {
  const t = $("#ticker"), track = $("#ticker-track");
  const live = games.filter((g) => g.status === "live").length;
  const lp = $("#live-pill"); lp.hidden = !live; $("#live-count").textContent = live;
  if (!games.length) { t.hidden = true; return; }
  const item = (g) => `<span class="tick"><b>${esc(g.away.abbr)}</b> ${g.away.score ?? ""} <span class="t2">@</span> <b>${esc(g.home.abbr)}</b> ${g.home.score ?? ""} <span class="st ${g.status}">${g.status === "live" ? esc(g.status_text || "LIVE") : g.status === "final" ? "FINAL" : esc(fmt.time(g.start_utc) || "UPCOMING")}</span></span>`;
  const row = games.map(item).join("");
  track.innerHTML = row + row; track.style.setProperty("--dur", `${Math.max(24, games.length * 7)}s`); t.hidden = false;
}
function startLive() {
  const apply = (games, status = "fresh") => { store.set("live", { games, status, at: Date.now() }); renderTicker(games); };
  const poll = async () => { try { const { data } = await api("/scoreboard", {}, { ttl: 4000, force: true }); apply(data.games); } catch { /* shown by data pill */ } };
  poll();
  let timer = setInterval(poll, window.__CV_POLL_MS || 20000);
  if (window.io) {
    const s = window.io({ transports: ["websocket", "polling"], reconnectionDelay: 2000 });
    s.on("scoreboard", (p) => { if (p.games?.length || p.status !== "unavailable") apply(p.games || [], p.status); });
    s.on("connect", () => { clearInterval(timer); timer = setInterval(poll, 60000); });
    s.on("disconnect", () => { clearInterval(timer); timer = setInterval(poll, 15000); });
  }
}

const FACE_FALLBACK = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#808890" fill-opacity=".25"/><circle cx="20" cy="16" r="6" fill="#808890"/><path d="M8 40c1-9 7-12 12-12s11 3 12 12z" fill="#808890"/></svg>');
// Coloured abbreviation badge shown when a team logo can't be loaded (offline, or cdn.nba.com blocked).
function logoFallback(abbr = "", color = "") {
  const c = /^#[0-9a-f]{6}$/i.test(color) ? color : "#6b7480", n = parseInt(c.slice(1), 16);
  const lum = (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255, fg = lum > 0.62 ? "#111" : "#fff";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><circle cx="20" cy="20" r="19" fill="${c}"/><text x="20" y="25" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="${abbr.length > 2 ? 13 : 15}" font-weight="700" fill="${fg}">${abbr.replace(/[<>&"]/g, "")}</text></svg>`;
  return "data:image/svg+xml," + encodeURIComponent(svg);
}
// CSP forbids inline onerror handlers, so image fallbacks are handled here (error events don't bubble -> capture).
document.addEventListener("error", (e) => {
  const t = e.target; if (!(t instanceof HTMLImageElement)) return;
  if (t.classList.contains("face") && t.src !== FACE_FALLBACK) t.src = FACE_FALLBACK;
  else if (t.classList.contains("logo") && !t.dataset.fb) { t.dataset.fb = "1"; t.src = logoFallback(t.dataset.abbr, t.dataset.c); }
}, true);

async function boot() {
  store.initTheme();
  try {
    const { data: meta } = await api("/meta", {}, { ttl: 600000 });
    store.setMeta(meta); setupTopbar(meta);
  } catch (e) { $("#main").innerHTML = stateError(e, true).toString(); $("#main [data-retry]")?.addEventListener("click", () => location.reload()); return; }
  renderNav("overview");
  $("#search-btn").addEventListener("click", openPalette);
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); } else if (e.key === "/" && !/input|select|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); openPalette(); } });
  delegate(document, "click", "[data-nav]", (e, el) => { e.preventDefault(); navigate(el.dataset.nav); });
  startRouter($("#main"), { onRoute: (nav, path) => { renderNav(nav); document.title = `${$("#brand-title")?.textContent || "CourtVision AI"} — ${(NAV.find((n) => n.id === nav)?.label) || "Not found"}`; } });
  startLive();
  window.addEventListener("online", () => toast("Back online", "ok"));
  window.addEventListener("offline", () => toast("You are offline — showing the last loaded data", "err"));
}
// The standalone demo build starts the app itself once the visitor clicks "Try demo".
if (window.__CV_MANUAL_BOOT) window.__cvStart = boot; else boot();
