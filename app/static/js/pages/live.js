import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { pageHead, provenance, notices, gameCard, skeletonCards, stateEmpty, stateError, seg, bindSeg, badge, animateCounts, kpi } from "../ui/components.js";
import { navigate, setQuery } from "../core/router.js";

export default async function render(ctx) {
  const { root } = ctx;
  let date = ctx.query.date || store.state.today, filter = "all", data = null, meta = null;
  root.innerHTML = pageHead({ title: "Live Games", sub: "Real-time scoreboard with live win probability. Scores come from the NBA live feed; probabilities are model estimates." }).toString() + html`
    <div class="toolbar"><div class="field"><label>Date</label><div class="row gap-6"><button class="btn sm" id="prev" aria-label="Previous day">${raw(icon("left"))}</button><input type="date" class="input" id="date" value="${date}"><button class="btn sm" id="next" aria-label="Next day">${raw(icon("chevron"))}</button><button class="btn sm" id="today-btn">Today</button></div></div>
      <div class="field"><label>Status</label>${seg("status", [["all", "All"], ["live", "Live"], ["final", "Final"], ["scheduled", "Upcoming"]], "all")}</div><div class="grow"></div><div id="prov"></div></div>
    <div id="notes"></div><div id="kpis" class="kpis"></div><div id="games">${skeletonCards(6)}</div>
    <section class="card" style="margin-top:20px"><div class="card-h"><h3>Headlines</h3>${badge("live", "Context only")}</div><div class="card-b flush" id="news"></div></section>`.toString();
  const $ = (s) => root.querySelector(s);

  const draw = () => {
    if (!data) return;
    const list = data.games.filter((g) => filter === "all" || g.status === filter);
    $("#games").innerHTML = list.length ? `<div class="games stagger">${list.map((g, i) => gameCard(g).toString().replace("<a ", `<a style="--i:${Math.min(i, 12)}" `)).join("")}</div>`
      : stateEmpty(data.games.length ? "No games match this filter" : "No games on this date", data.games.length ? "Try another status." : "Pick another date or check the schedule.", "calendar").toString();
    const live = data.games.filter((g) => g.status === "live").length;
    $("#kpis").innerHTML = [kpi({ label: "Games", count: data.games.length, dec: 0, sub: fmt.date(date) }), kpi({ label: "Live now", count: live, dec: 0, sub: live ? "Updating in real time" : "None in progress" }),
      kpi({ label: "Final", count: data.games.filter((g) => g.status === "final").length, dec: 0, sub: "Completed" }), kpi({ label: "Upcoming", count: data.games.filter((g) => g.status === "scheduled").length, dec: 0, sub: "Pre-game odds shown" })].join("");
    animateCounts(root);
  };
  const load = async (force = false) => {
    try {
      const r = await api("/scoreboard", { date }, { signal: ctx.signal, ttl: 4000, force });
      data = r.data; meta = r.meta; $("#prov").innerHTML = provenance(meta).toString(); $("#notes").innerHTML = notices(meta).toString(); draw();
    } catch (e) { if (e.name !== "AbortError") $("#games").innerHTML = stateError(e, true).toString(), $("#games [data-retry]")?.addEventListener("click", () => load(true)); }
  };
  const go = (d) => { date = d; $("#date").value = d; setQuery({ date: d }); load(); };
  $("#date").addEventListener("change", (e) => e.target.value && go(e.target.value));
  $("#prev").addEventListener("click", () => go(fmt.addDays(date, -1))); $("#next").addEventListener("click", () => go(fmt.addDays(date, 1)));
  $("#today-btn").addEventListener("click", () => go(store.state.today));
  ctx.onCleanup(bindSeg(root, "status", (v) => { filter = v; draw(); }));
  await load();

  // live merge from the socket/ticker
  const off = store.on("live", ({ games }) => {
    if (!data || date !== store.state.today || !games.length) return;
    const by = Object.fromEntries(games.map((g) => [g.game_id, g])); let changed = false;
    data.games = data.games.map((g) => { const n = by[g.game_id]; if (!n) return g; const m = { ...g, status: n.status, status_text: n.status_text, period: n.period, clock: n.clock, home: { ...g.home, ...n.home }, away: { ...g.away, ...n.away }, live_wp: n.live_wp ?? g.live_wp }; if (m.home.score !== g.home.score || m.away.score !== g.away.score || m.status !== g.status) changed = true; return m; });
    if (changed) draw();
  });
  ctx.onCleanup(off);

  api("/news", {}, { signal: ctx.signal, ttl: 300000 }).then(({ data: n }) => {
    $("#news").innerHTML = n.articles.length ? `<div class="list">${n.articles.slice(0, 8).map((a) => html`<a href="${a.url}" target="_blank" rel="noopener noreferrer"><div class="li"><div class="grow"><div class="t" style="white-space:normal">${a.headline}</div><div class="s">${a.source} ${a.published ? "· " + fmt.date(a.published) : ""}</div></div>${raw(icon("chevron"))}</div></a>`).join("")}</div>` : stateEmpty("No headlines", "").toString();
  }).catch(() => { $("#news").innerHTML = stateEmpty("Headlines unavailable", "News is optional context and doesn't affect any model.").toString(); });
}
