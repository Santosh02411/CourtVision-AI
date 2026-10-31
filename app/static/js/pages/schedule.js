import { api } from "../core/api.js";
import { store } from "../core/store.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { pageHead, provenance, notices, teamLogo, skeletonPage, stateEmpty, stateError, badge, statusBadge, seg, bindSeg } from "../ui/components.js";
import { setQuery } from "../core/router.js";

const monday = (iso) => { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return fmt.isoDate(d); };
export default async function render(ctx) {
  const { root } = ctx; const today = store.state.today;
  let start = ctx.query.from || monday(today), team = ctx.query.team || "", status = "";
  root.innerHTML = pageHead({ title: "Schedule", sub: "Current-season schedule and results, with the model's pre-game pick for upcoming games." }).toString() + html`
    <div class="toolbar"><div class="field"><label>Week</label><div class="row gap-6"><button class="btn sm" id="prev" aria-label="Previous week">${raw(icon("left"))}</button><input type="date" class="input" id="from" value="${start}"><button class="btn sm" id="next" aria-label="Next week">${raw(icon("chevron"))}</button><button class="btn sm" id="now">This week</button></div></div>
      <div class="field"><label for="team">Team</label><select id="team" class="input"><option value="">All teams</option>${store.state.teams.map((t) => html`<option value="${t.abbr}" ${t.abbr === team ? "selected" : ""}>${t.name}</option>`)}</select></div>
      <div class="field"><label>Status</label>${seg("status", [["", "All"], ["scheduled", "Upcoming"], ["final", "Final"]], "")}</div><div class="grow"></div><div id="prov"></div></div><div id="notes"></div><div id="body">${skeletonPage(1)}</div>`.toString();
  const $ = (s) => root.querySelector(s);
  const load = async () => {
    const to = fmt.addDays(start, 6); setQuery({ from: start, team });
    try {
      const { data, meta } = await api("/schedule", { from: start, to, team, status }, { signal: ctx.signal });
      $("#prov").innerHTML = provenance(meta).toString(); $("#notes").innerHTML = notices(meta).toString();
      const byDay = {}; data.games.forEach((g) => (byDay[g.date] ||= []).push(g));
      const days = Array.from({ length: 7 }, (_, i) => fmt.addDays(start, i));
      $("#body").innerHTML = data.games.length ? days.filter((d) => byDay[d]).map((d) => html`<section class="card" style="margin-bottom:14px"><div class="card-h"><h3>${fmt.date(d, { weekday: "long", month: "long", day: "numeric" })} ${d === today ? badge("live", "Today") : ""}</h3><span class="tiny muted">${byDay[d].length} games</span></div><div class="card-b flush"><div class="list">${byDay[d].map((g) => {
        const h = store.team(g.home.id) || g.home, a = store.team(g.away.id) || g.away, p = g.prediction;
        return html`<a href="#/games/${g.game_id}"><div class="li"><span class="tiny muted" style="width:64px">${g.status === "scheduled" ? fmt.time(g.start_utc) : ""}</span>${teamLogo(a, "sm")}<div class="grow"><div class="t">${a.name} <span class="muted">@</span> ${h.name}</div><div class="s">${g.arena || ""}</div></div>${g.status !== "scheduled" ? html`<b class="num">${g.away.score}–${g.home.score}</b>` : ""}${p ? html`<div class="right" style="width:110px"><b class="num">${p.pick} ${fmt.prob(p.pick === g.home.abbr ? p.home : 1 - p.home)}</b><div class="tiny muted">Prediction · ${p.confidence}</div></div>` : ""}${statusBadge(g)}</div></a>`; })}</div></div></section>`) : stateEmpty("No games this week", "Try another week or team.", "calendar").toString();
    } catch (e) { if (e.name !== "AbortError") { $("#body").innerHTML = stateError(e, true).toString(); $("#body [data-retry]")?.addEventListener("click", load); } }
  };
  const go = (d) => { start = d; $("#from").value = d; load(); };
  $("#from").addEventListener("change", (e) => e.target.value && go(e.target.value)); $("#prev").addEventListener("click", () => go(fmt.addDays(start, -7))); $("#next").addEventListener("click", () => go(fmt.addDays(start, 7))); $("#now").addEventListener("click", () => go(monday(today)));
  $("#team").addEventListener("change", (e) => { team = e.target.value; load(); }); ctx.onCleanup(bindSeg(root, "status", (v) => { status = v; load(); }));
  load();
}
