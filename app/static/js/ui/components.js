import { html, raw, esc, delegate, $$ } from "../core/dom.js";
import { icon } from "./icons.js";
import { store } from "../core/store.js";
import { fmt, hexA, pairColors } from "./format.js";

const KIND_LABEL = { live: "Live", historical: "Historical", prediction: "Prediction", derived: "Derived", model: "Model", stale: "Stale", unavailable: "Unavailable", final: "Final", scheduled: "Upcoming", synthetic: "Synthetic", real: "Real data" };
export const badge = (kind, text) => html`<span class="badge ${kind}">${text || KIND_LABEL[kind] || kind}</span>`;

/** Provenance strip: what kind of data this is + freshness. */
export function provenance(meta, extra = "") {
  if (!meta) return raw("");
  const kind = meta.kind || "historical";
  const stale = meta.status === "stale";
  const src = (meta.sources || [])[0];
  const age = src?.age_seconds != null ? ` · updated ${fmt.ago(src.age_seconds)}` : "";
  return html`<span class="row gap-6 wrap">${badge(kind)}${stale ? badge("stale", "Stale — upstream unavailable") : ""}${extra}<span class="tiny muted">${meta.season ? `Season ${meta.season}` : ""}${age}</span></span>`;
}
export const notices = (meta) => raw((meta?.notes || []).map((n) => notice(n, "warn").toString()).join(""));
export function notice(text, kind = "warn") { return html`<div class="notice ${kind === "warn" ? "" : kind}">${raw(icon(kind === "err" ? "alert" : "info"))}<div>${text}</div></div>`; }

export const teamLogo = (t, cls = "") => t ? html`<img class="logo ${cls}" src="${t.logo}" alt="" loading="lazy">` : html`<span class="logo ${cls}"></span>`;
export const face = (id, cls = "") => html`<img class="face ${cls}" src="https://cdn.nba.com/headshots/nba/latest/1040x760/${id}.png" alt="" loading="lazy">`;

export const skel = (h = 16, w = "100%", mb = 8) => html`<div class="skel" style="height:${h}px;width:${w};margin-bottom:${mb}px"></div>`;
export function skeletonCards(n = 4, h = 150) { return html`<div class="games">${Array.from({ length: n }, () => html`<div class="skel" style="height:${h}px"></div>`)}</div>`; }
export function skeletonPage(rows = 3) { return html`<div class="col gap-14">${skel(34, "260px", 4)}${skel(14, "420px", 14)}<div class="grid">${Array.from({ length: rows * 2 }, (_, i) => html`<div class="card s6"><div class="card-b">${skel(14, "40%")}${skel(150)}</div></div>`)}</div></div>`; }

export function stateEmpty(title, text = "", ic = "inbox") { return html`<div class="state">${raw(icon(ic))}<h4>${title}</h4>${text ? html`<p>${text}</p>` : ""}</div>`; }
export function stateError(err, retry = false) {
  const code = err?.code, offline = code === "network";
  const title = offline ? "You appear to be offline" : code === "data_unavailable" ? "Data source unavailable" : "Something went wrong";
  const text = err?.message || "Unexpected error.";
  return html`<div class="card"><div class="state err">${raw(icon(offline ? "wifi" : "alert"))}<h4>${title}</h4><p>${text}</p>${retry ? html`<button class="btn" data-retry>${raw(icon("refresh"))} Try again</button>` : ""}</div></div>`;
}

export function kpi({ label, value, sub = "", count = null, dec = 1, suffix = "", tip = "" }) {
  const v = count != null ? html`<span data-count="${count}" data-dec="${dec}" data-suffix="${suffix}">${fmt.num(count, dec)}${suffix}</span>` : value;
  return html`<div class="kpi" title="${tip}"><div class="kpi-label">${label}</div><div class="kpi-value ${count == null ? "txt" : ""}">${v}</div><div class="kpi-sub">${sub}</div></div>`;
}
export function animateCounts(root = document) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  $$("[data-count]", root).forEach((el) => {
    const end = parseFloat(el.dataset.count), dec = +el.dataset.dec || 0, suf = el.dataset.suffix || "";
    if (Number.isNaN(end)) return;
    if (reduce) { el.textContent = end.toFixed(dec) + suf; return; }
    const t0 = performance.now(), dur = 700;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = (end * e).toFixed(dec) + suf; if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  });
}

export const confidenceMeter = (label) => {
  const n = label === "High" ? 3 : label === "Medium" ? 2 : 1;
  return html`<span class="conf">${[1, 2, 3].map((i) => html`<i class="${i <= n ? "on" : ""}"></i>`)} ${label} confidence</span>`;
};

export function wpBar(home, away, p, labels = true) {
  const hp = Math.max(0, Math.min(1, p ?? 0.5)), ph = (hp * 100).toFixed(1), pa = (100 - hp * 100).toFixed(1);
  const [hc, ac] = pairColors(home, away);
  return html`<div class="wpbar" role="img" aria-label="Win probability ${home.abbr} ${ph}%"><i style="width:${pa}%;background:${ac}"></i><i style="width:${ph}%;background:${hc}"></i></div>
    ${labels ? html`<div class="wp-legend"><span><b>${away.abbr}</b> ${pa}%</span><span><b>${home.abbr}</b> ${ph}%</span></div>` : ""}`;
}

export function statusBadge(g) {
  if (g.status === "live") return html`<span class="badge live">${g.status_text || `Q${g.period} ${fmt.clock(g.clock)}`}</span>`;
  if (g.status === "final") return badge("final", g.status_text || "Final");
  return html`<span class="badge scheduled">${fmt.time(g.start_utc) || g.status_text || "Upcoming"}</span>`;
}
export function gameCard(g) {
  const h = store.team(g.home.id) || g.home, a = store.team(g.away.id) || g.away;
  const fin = g.status === "final", hs = g.home.score, as = g.away.score;
  const homeLose = fin && hs < as, awayLose = fin && as < hs;
  let wp = null, wpLabel = "";
  if (g.status === "live" && g.live_wp != null) { wp = g.live_wp; wpLabel = "Live win prob. (score & clock model)"; }
  else if (g.status === "scheduled" && g.prediction) { wp = g.prediction.home; wpLabel = `Prediction · ${g.prediction.confidence} confidence${g.prediction.fitted ? "" : " · uncalibrated"}`; }
  const rec = (t) => (t.wins != null ? `${t.wins}-${t.losses}` : "");
  return html`<a class="gcard ${g.status}" href="#/games/${g.game_id}" aria-label="${a.name} at ${h.name}">
    <div class="gc-top"><span>${g.label || g.series || fmt.date(g.date)}</span>${statusBadge(g)}</div>
    <div class="gc-team ${awayLose ? "lose" : ""}">${teamLogo(a)}<div class="nm">${a.name}<small>${rec(g.away)}</small></div><div class="score">${as ?? ""}</div></div>
    <div class="gc-team ${homeLose ? "lose" : ""}">${teamLogo(h)}<div class="nm">${h.name}<small>${rec(g.home)}</small></div><div class="score">${hs ?? ""}</div></div>
    ${wp != null ? html`${wpBar(h, a, wp)}<div class="gc-foot"><span>${wpLabel}</span>${badge(g.status === "live" ? "live" : "prediction", g.status === "live" ? "Live" : "Prediction")}</div>` : html`<div class="gc-foot"><span>${g.arena || ""}</span><span>${raw(icon("chevron"))}</span></div>`}
  </a>`;
}

export const trendArrow = (v, d = 1) => v == null ? raw("—") : html`<span class="${v > 0 ? "pos" : v < 0 ? "neg" : "muted"}">${raw(icon(v > 0 ? "up" : "down", ""))}</span>`;
export const formChip = (label, delta) => {
  if (!label) return raw("");
  const cls = ["Hot", "Warm", "Warming"].includes(label) ? "hot" : ["Cold", "Cool", "Cooling"].includes(label) ? "cold" : "";
  return html`<span class="chip ${cls}">${["Hot", "Warm", "Warming"].includes(label) ? raw(icon("flame")) : ""}${label}${delta != null ? ` ${fmt.signed(delta)}` : ""}</span>`;
};
export const bar = (value, max, cls = "") => html`<div class="bar-cell"><div class="bar"><i class="${cls}" style="width:${Math.max(0, Math.min(100, (value / max) * 100))}%"></i></div></div>`;

export function sparkline(values, { w = 120, h = 32, color = "var(--accent)" } = {}) {
  const v = values.filter((x) => x != null); if (v.length < 2) return raw("");
  const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const pts = v.map((y, i) => `${(i / (v.length - 1)) * w},${h - 3 - ((y - lo) / r) * (h - 6)}`).join(" ");
  return raw(`<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>`);
}

/** Sortable table. cfg.columns: {key,label,n?,sort?(row),render?(row),title?}. Re-renders its own body on sort. */
export function sortableTable(container, cfg) {
  let { sortKey, sortDir = "desc" } = cfg;
  const cols = cfg.columns, rowsAll = () => cfg.rows;
  const val = (c, r) => (c.sort ? c.sort(r) : r[c.key]);
  const draw = () => {
    const col = cols.find((c) => c.key === sortKey);
    let rows = [...rowsAll()];
    if (col) rows.sort((a, b) => {
      const x = val(col, a), y = val(col, b);
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      const c = typeof x === "string" ? x.localeCompare(y) : x - y; return sortDir === "asc" ? c : -c;
    });
    if (cfg.limit) rows = rows.slice(0, cfg.limit);
    container.innerHTML = html`<div class="tbl-wrap" style="${cfg.maxHeight ? `max-height:${cfg.maxHeight}px` : ""}"><table class="tbl">
      <thead><tr>${cfg.rank ? html`<th class="rank">#</th>` : ""}${cols.map((c) => html`<th class="${c.n ? "n" : ""} ${c.nosort ? "" : "sortable"} ${c.key === sortKey ? "sorted" : ""}" data-key="${c.key}" ${c.title ? html`title="${c.title}"` : ""} aria-sort="${c.key === sortKey ? (sortDir === "asc" ? "ascending" : "descending") : "none"}">${c.label}<span class="arr">${c.key === sortKey ? (sortDir === "asc" ? "▲" : "▼") : ""}</span></th>`)}</tr></thead>
      <tbody>${rows.map((r, i) => html`<tr class="${cfg.href ? "click" : ""}" ${cfg.href ? html`data-href="${cfg.href(r)}"` : ""}>${cfg.rank ? html`<td class="rank">${i + 1}</td>` : ""}${cols.map((c) => html`<td class="${c.n ? "n" : ""}">${c.render ? c.render(r) : (r[c.key] ?? "—")}</td>`)}</tr>`)}</tbody></table></div>
      ${rows.length ? "" : stateEmpty("Nothing matches these filters", "Try clearing a filter or searching for something else.")}`.toString();
    cfg.onDraw?.(container);
  };
  container.addEventListener("click", (e) => {
    const th = e.target.closest("th.sortable");
    if (th) { const k = th.dataset.key; if (k === sortKey) sortDir = sortDir === "desc" ? "asc" : "desc"; else { sortKey = k; sortDir = cols.find((c) => c.key === k)?.asc ? "asc" : "desc"; } draw(); return; }
    const tr = e.target.closest("tr[data-href]"); if (tr && !e.target.closest("a")) location.hash = tr.dataset.href;
  });
  draw();
  return { redraw: draw, setRows(r) { cfg.rows = r; draw(); } };
}

/** Segmented control: <div class="seg" data-seg="name"> ... */
export const seg = (name, options, value) => html`<div class="seg" data-seg="${name}" role="tablist">${options.map(([v, l]) => html`<button type="button" role="tab" data-v="${v}" class="${String(v) === String(value) ? "on" : ""}" aria-selected="${String(v) === String(value)}">${l}</button>`)}</div>`;
export function bindSeg(root, name, fn) {
  return delegate(root, "click", `[data-seg="${name}"] button`, (e, b) => {
    b.parentElement.querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", x === b); });
    fn(b.dataset.v);
  });
}

// ---- tooltip -----------------------------------------------------------------
let tipEl;
export const tip = {
  show(content, x, y) {
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tooltip"; document.body.appendChild(tipEl); }
    tipEl.innerHTML = content; tipEl.classList.add("on");
    const r = tipEl.getBoundingClientRect();
    tipEl.style.left = `${Math.min(x + 14, innerWidth - r.width - 10)}px`; tipEl.style.top = `${Math.min(y + 14, innerHeight - r.height - 10)}px`;
  },
  hide() { tipEl?.classList.remove("on"); },
};
export function bindTips(root) {
  const off = [];
  root.addEventListener("mousemove", (e) => { const t = e.target.closest("[data-tip]"); if (t) tip.show(t.dataset.tip, e.clientX, e.clientY); else tip.hide(); });
  root.addEventListener("mouseleave", () => tip.hide());
  return () => { tip.hide(); };
}

export const toast = (msg, kind = "") => {
  const host = document.getElementById("toasts"), el = document.createElement("div");
  el.className = `toast ${kind}`; el.textContent = msg; host.appendChild(el); setTimeout(() => el.remove(), 3800);
};

export function pageHead({ title, sub = "", right = "", crumbs = "" }) {
  return html`${crumbs ? html`<div class="crumbs">${crumbs}</div>` : ""}<div class="page-head"><div><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ""}</div><div class="row wrap">${right}</div></div>`;
}
export const card = (title, body, { right = "", cls = "", bodyCls = "" } = {}) => html`<section class="card ${cls}">${title ? html`<div class="card-h"><h3>${title}</h3>${right}</div>` : ""}<div class="card-b ${bodyCls}">${body}</div></section>`;

/** AI analyst card: loads /ai/brief lazily and types the text out. */
export function aiBriefCard(id = "ai-brief") {
  return html`<section class="brief" id="${id}"><h3>${raw(icon("sparkles"))} AI Analyst</h3><div class="ai-body">${skel(12, "92%")}${skel(12, "80%")}${skel(12, "60%", 0)}</div></section>`;
}
export async function loadBrief(root, apiFn, params, id = "ai-brief") {
  const el = root.querySelector(`#${id} .ai-body`); if (!el) return;
  try {
    const { data } = await apiFn("/ai/brief", params, { ttl: 60000 });
    const label = data.generated_by === "gemini" ? html`<span class="badge derived">Written by Gemini</span>` : data.generated_by === "claude" ? html`<span class="badge derived">Written by Claude</span>` : html`<span class="badge derived">Rule-based summary</span>`;
    el.innerHTML = html`<p class="${matchMedia("(prefers-reduced-motion: reduce)").matches ? "" : "typing"}" id="${id}-text"></p><div class="src">${label}<span>Generated only from the verified facts below${data.note ? ` · ${data.note}` : ""}</span></div>
      <details style="margin-top:10px"><summary class="small t2" style="cursor:pointer">Facts used (${data.facts.length})</summary><ul class="small t2" style="margin:8px 0 0;padding-left:18px">${data.facts.map((f) => html`<li>${f}</li>`)}</ul></details>`.toString();
    const p = el.querySelector(`#${id}-text`), text = data.text; let i = 0;
    const tick = () => { i = Math.min(text.length, i + 3); p.textContent = text.slice(0, i); if (i < text.length && p.isConnected) setTimeout(tick, 12); else p.classList.remove("typing"); };
    matchMedia("(prefers-reduced-motion: reduce)").matches ? (p.textContent = text) : tick();
  } catch (e) { el.innerHTML = `<p class="muted small">${esc(e.message || "AI briefing unavailable.")}</p>`; }
}
