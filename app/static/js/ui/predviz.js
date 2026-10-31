import { html, raw } from "../core/dom.js";
import { fmt, pairColors } from "./format.js";
import { icon } from "./icons.js";
import { badge, confidenceMeter, teamLogo, notice } from "./components.js";

const RAW_HELP = {
  elo_diff: (v) => `Elo gap (home − away): ${fmt.signed(v * 100, 0)} points`,
  margin_diff: (v) => `Season margin edge: ${fmt.signed(v)} pts/game (shrunk toward 0 for small samples)`,
  form_diff: (v) => `Last-10 margin edge: ${fmt.signed(v)} pts/game`,
  rest_diff: (v) => `Rest-day edge for home: ${fmt.signed(v, 0)} days`,
  b2b_home: (v) => (v ? "Home team is on the 2nd night of a back-to-back" : "Home team is rested"),
  b2b_away: (v) => (v ? "Away team is on the 2nd night of a back-to-back" : "Away team is rested"),
  availability: (v) => `Estimated net injury impact: ${fmt.signed(v)} pts for the home side`,
};

export function gauge(home, away, pHome) {
  const [hCol, aCol] = pairColors(home, away);
  const len = Math.PI * 80, pa = 1 - pHome;
  const fav = pHome >= 0.5 ? home : away, pf = Math.max(pHome, pa);
  return html`<div class="gauge"><svg viewBox="0 0 200 112" role="img" aria-label="${fav.abbr} ${fmt.prob(pf)} win probability">
    <path d="M20 100A80 80 0 0 1 180 100" fill="none" stroke="var(--surface-3)" stroke-width="16" stroke-linecap="butt"/>
    <path class="g-away" d="M20 100A80 80 0 0 1 180 100" fill="none" stroke="${aCol}" stroke-width="16" style="stroke-dasharray:0 ${len};transition:stroke-dasharray 1s cubic-bezier(.2,.7,.2,1)" data-da="${(len * pa).toFixed(1)} ${len.toFixed(1)}"/>
    <path class="g-home" d="M20 100A80 80 0 0 1 180 100" fill="none" stroke="${hCol}" stroke-width="16" style="stroke-dasharray:0 ${len};stroke-dashoffset:${-(len * pa).toFixed(1)};transition:stroke-dasharray 1s cubic-bezier(.2,.7,.2,1) .1s" data-da="${(len * pHome).toFixed(1)} ${len.toFixed(1)}"/>
    <rect x="97.5" y="14" width="5" height="10" rx="2" fill="var(--text-3)" opacity=".5"/></svg>
    <div class="gv"><b>${fmt.prob(pf)}</b><span>${fav.abbr} to win</span></div></div>
    <div class="row between small" style="margin-top:8px"><span class="row gap-6">${teamLogo(away, "sm")}<b>${away.abbr}</b> ${fmt.prob(pa)}</span><span class="row gap-6"><b>${home.abbr}</b> ${fmt.prob(pHome)} ${teamLogo(home, "sm")}</span></div>`;
}
export function animateGauges(root) { requestAnimationFrame(() => requestAnimationFrame(() => root.querySelectorAll("[data-da]").forEach((p) => { p.style.strokeDasharray = p.dataset.da; }))); }

export function factorBars(pr) {
  const max = Math.max(5, ...pr.factors.map((f) => Math.abs(f.contribution_pp)));
  return html`<div>${pr.factors.map((f) => {
    const w = Math.min(50, (Math.abs(f.contribution_pp) / max) * 50), homeSide = f.contribution_logit > 0;
    const [hC, aC] = pairColors(pr.home, pr.away); const col = f.favors === pr.home.abbr ? hC : f.favors === pr.away.abbr ? aC : "var(--text-3)";
    const tip = `<b>${f.label}</b>${(RAW_HELP[f.key] || (() => ""))(f.raw_value)}<br>Log-odds contribution ${fmt.signed(f.contribution_logit, 3)}`;
    return html`<div class="factor" data-tip="${tip}"><span>${f.label}</span><div class="track"><div class="fill" style="${homeSide ? `left:50%;width:${w}%` : `right:50%;width:${w}%`};background:${col}"></div></div><b class="num right" style="color:${col}">${f.favors === "neutral" ? "0.0" : fmt.signed(Math.abs(f.contribution_pp) * (homeSide ? 1 : -1))}<span class="tiny muted"> pp</span></b></div>`;
  })}<div class="row between tiny muted" style="margin-top:6px"><span>← favours ${pr.away.abbr}</span><span>favours ${pr.home.abbr} →</span></div></div>`;
}

export function contextTable(pr) {
  const c = pr.context, h = pr.home.abbr, a = pr.away.abbr;
  const row = (label, hv, av, better = "high") => { const hn = +hv, an = +av, hw = better === "high" ? hn > an : hn < an, aw = better === "high" ? an > hn : an < hn;
    return html`<tr><td class="${aw ? "pos" : ""} num right">${av}</td><td class="center muted tiny">${label}</td><td class="${hw ? "pos" : ""} num">${hv}</td></tr>`; };
  return html`<table class="tbl"><thead><tr><th class="n">${a}</th><th class="center">Metric</th><th>${h}</th></tr></thead><tbody>
    ${row("Elo rating", fmt.num(c.elo.home, 0), fmt.num(c.elo.away, 0))}${row("Season margin / game", fmt.signed(c.season_margin.home, 1), fmt.signed(c.season_margin.away, 1))}
    ${row("Last-10 margin (shrunk)", fmt.signed(c.last10_margin.home, 2), fmt.signed(c.last10_margin.away, 2))}${row("Rest days", c.rest_days.home, c.rest_days.away)}${row("Games played", c.games_played.home, c.games_played.away)}</tbody></table>`;
}

export function availabilityBlock(pr) {
  const av = pr.availability; if (!av || (!av.home && !av.away)) return notice("Injury reports unavailable — the probability does not include availability adjustments.", "info");
  const side = (tm, a) => html`<div><div class="lbl" style="margin-bottom:6px">${tm.abbr}</div>${a && a.players.length ? a.players.map((p) => html`<div class="row between small" style="padding:4px 0"><span>${p.player_id ? html`<a href="#/players/${p.player_id}" class="accent">${p.player}</a>` : p.player} <span class="chip">${p.status}</span></span><span class="num muted">${p.matched ? fmt.signed(-p.impact_pts) + " pts est." : "no stats match"}</span></div>`) : html`<div class="small muted">No reported absences.</div>`}</div>`;
  return html`<div class="grid" style="gap:16px">${[side(pr.home, av.home), side(pr.away, av.away)].map((x) => html`<div class="s6">${x}</div>`)}</div><div class="tiny muted" style="margin-top:8px">Impact is an estimate from each player's PIE and minutes (capped at 7 pts); statuses come from ESPN's public injury report.</div>`;
}

export function h2hBlock(pr) {
  const h = pr.head_to_head; if (!h || !h.games) return html`<div class="small muted">No meetings in the last three seasons.</div>`;
  return html`<div class="row between" style="margin-bottom:8px"><b>${h.a} ${h.a_wins}–${h.b_wins} ${h.b}</b><span class="small muted">avg margin ${h.a} ${fmt.signed(h.avg_margin_a)} · last ${h.games} meetings (3 seasons)</span></div>
    <div class="list" style="margin:0 -16px -16px">${h.recent.slice(0, 5).map((g) => html`<div><div class="row between small"><span>${fmt.date(g.date, { month: "short", day: "numeric", year: "2-digit" })}</span><b class="num">${g.away} ${g.away_pts} – ${g.home_pts} ${g.home}</b></div></div>`)}</div>`;
}

export function modelNote(pr) {
  const m = pr.model, ev = m.evaluation;
  return html`<div class="small t2">${m.fitted ? html`${badge("real", "Fitted on real games")} Out-of-sample ${ev?.test_season}: <b>${fmt.pct(ev?.accuracy * 100)}</b> accuracy · log loss <b>${ev?.log_loss}</b> vs ${ev?.baselines?.home_rate_log_loss} for a home-rate baseline.` : html`${badge("synthetic", "Uncalibrated prior")} ${m.warning}`} <a class="accent" href="#/models">Model details →</a></div>`;
}

export function predictionPanel(pr) {
  return html`<div class="grid">
    <section class="card s5"><div class="card-h"><h3>${raw(icon("target"))} Win probability</h3>${badge("prediction")}</div><div class="card-b">${gauge(pr.home, pr.away, pr.probabilities.home)}
      <div class="row between" style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border)"><div><div class="lbl">Model pick</div><b style="font-size:16px">${pr.pick === pr.home.abbr ? pr.home.name : pr.away.name}</b></div><div class="right"><div class="lbl">Implied spread</div><b class="num" style="font-size:16px">${pr.home.abbr} ${fmt.signed(-pr.implied_spread)}</b></div></div>
      <div style="margin-top:12px">${confidenceMeter(pr.confidence.label)}<ul class="small t2" style="margin:8px 0 0;padding-left:18px">${pr.confidence.reasons.map((r) => html`<li>${r}</li>`)}</ul></div></div>
      <div class="card-f">${modelNote(pr)}</div></section>
    <section class="card s7"><div class="card-h"><h3>Why the model says this</h3><span class="tiny muted">Exact additive attribution vs. an average game (${fmt.prob(pr.baseline_probability)} home)</span></div><div class="card-b">${factorBars(pr)}
      <p class="tiny muted" style="margin:10px 0 0">Each bar is a factor's share of the swing in home win probability (percentage points). The pre-game model is a logistic regression, so these contributions are exact SHAP values. Hover a bar for the raw input.</p></div></section>
    <section class="card s6"><div class="card-h"><h3>Team context</h3></div><div class="card-b flush">${contextTable(pr)}</div></section>
    <section class="card s6"><div class="card-h"><h3>Head to head</h3></div><div class="card-b">${h2hBlock(pr)}</div></section>
    <section class="card s12"><div class="card-h"><h3>Availability</h3><span class="tiny muted">Reported injuries (ESPN) · included in the probability</span></div><div class="card-b">${availabilityBlock(pr)}</div></section></div>`;
}
