// Half-court SVG in NBA shot-chart units (1 unit = 0.1 ft). x: -250..250, y: -52..417, basket at (0,0).
import { html, raw } from "../core/dom.js";

const W = 500, H = 470, X0 = 250, Y0 = 417;
const px = (x) => X0 + x, py = (y) => Y0 - y;
const ARC_Y = Math.sqrt(237.5 ** 2 - 220 ** 2); // where the 3-pt arc meets the corner lines

function lines() {
  return `<g class="court-line">
    <rect x="${px(-250)}" y="${py(417)}" width="500" height="469" rx="4"/>
    <rect x="${px(-80)}" y="${py(142)}" width="160" height="194"/><rect x="${px(-60)}" y="${py(142)}" width="120" height="194"/>
    <path d="M${px(-60)} ${py(142)} A60 60 0 0 1 ${px(60)} ${py(142)}"/><path d="M${px(-60)} ${py(142)} A60 60 0 0 0 ${px(60)} ${py(142)}" stroke-dasharray="6 6"/>
    <path d="M${px(-220)} ${py(-52)} V${py(ARC_Y)} A237.5 237.5 0 0 1 ${px(220)} ${py(ARC_Y)} V${py(-52)}"/>
    <path d="M${px(-40)} ${py(0)} A40 40 0 0 1 ${px(40)} ${py(0)}"/>
    <path d="M${px(-60)} ${py(417)} A60 60 0 0 1 ${px(60)} ${py(417)}" />
    <line x1="${px(-30)}" x2="${px(30)}" y1="${py(-7.5)}" y2="${py(-7.5)}" stroke-width="3"/><circle cx="${px(0)}" cy="${py(0)}" r="7.5"/>
  </g>`;
}

const ZONE_SHAPES = {
  "Above the Break 3": `<rect x="0" y="${py(417)}" width="500" height="${H - 1}"/>`,
  "Left Corner 3": `<rect x="${px(-250)}" y="${py(ARC_Y)}" width="30" height="${ARC_Y + 52}"/>`,
  "Right Corner 3": `<rect x="${px(220)}" y="${py(ARC_Y)}" width="30" height="${ARC_Y + 52}"/>`,
  "Mid-Range": `<path d="M${px(-220)} ${py(-52)} V${py(ARC_Y)} A237.5 237.5 0 0 1 ${px(220)} ${py(ARC_Y)} V${py(-52)} Z"/>`,
  "In The Paint (Non-RA)": `<rect x="${px(-80)}" y="${py(142)}" width="160" height="194"/>`,
  "Restricted Area": `<path d="M${px(-40)} ${py(-52)} V${py(0)} A40 40 0 0 1 ${px(40)} ${py(0)} V${py(-52)} Z"/>`,
};
const ZONE_LABEL_POS = { "Above the Break 3": [0, 300], "Left Corner 3": [-235, 20], "Right Corner 3": [235, 20], "Mid-Range": [-140, 110], "In The Paint (Non-RA)": [0, 96], "Restricted Area": [0, 14] };

/** diff (pp vs league) -> colour on a diverging scale. */
export function diffColor(diff) {
  if (diff == null) return "var(--surface-3)";
  const k = Math.max(-1, Math.min(1, diff / 12));
  return k >= 0 ? `color-mix(in srgb, var(--pos) ${Math.round(k * 78)}%, var(--court))` : `color-mix(in srgb, var(--neg) ${Math.round(-k * 78)}%, var(--court))`;
}
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function courtSvg({ mode = "zones", zones = [], bins = [], shots = [], teamColor = null }) {
  let layers = "";
  if (mode === "zones") {
    const byZone = Object.fromEntries(zones.map((z) => [z.zone, z]));
    layers += Object.entries(ZONE_SHAPES).map(([name, shape]) => {
      const z = byZone[name];
      const tip = z ? `<b>${name}</b>${z.fgm}/${z.fga} · ${z.fg_pct}% FG<br>League avg ${z.league_fg_pct ?? "—"}% (${z.diff > 0 ? "+" : ""}${z.diff ?? "—"} pts)<br>${z.freq_pct}% of shots · model xFG ${z.xfg_pct}%` : `<b>${name}</b>No attempts`;
      return `<g transform="translate(0 0)" class="zone" style="fill:${diffColor(z?.diff)}" data-tip="${esc(tip)}">${shape.replace("<", "<")}</g>`;
    }).join("");
  } else if (mode === "heat") {
    const max = Math.max(1, ...bins.map((b) => b.fga));
    layers += bins.map((b) => { const pct = b.fgm / b.fga, a = Math.min(1, 0.18 + 0.82 * Math.sqrt(b.fga / max)); const col = `color-mix(in srgb, var(--accent) ${Math.round(pct * 100)}%, var(--info))`;
      return `<rect x="${px(b.x) - 15}" y="${py(b.y) - 15}" width="30" height="30" rx="6" fill="${col}" fill-opacity="${a.toFixed(2)}" data-tip="${esc(`<b>${b.fgm}/${b.fga}</b> · ${(pct * 100).toFixed(0)}% FG`)}"/>`; }).join("");
  }
  let overlay = "";
  if (mode === "zones") {
    overlay = zones.map((z) => { const p = ZONE_LABEL_POS[z.zone]; if (!p) return ""; const corner = z.zone.includes("Corner"), x = corner ? (p[0] < 0 ? px(-247) : px(247)) : px(p[0]), a = corner ? (p[0] < 0 ? "start" : "end") : "middle";
      return `<text class="zone-label ${corner ? "c" : ""}" text-anchor="${a}" x="${x}" y="${py(p[1])}">${z.fg_pct}%</text><text class="zone-label s" text-anchor="${a}" x="${x}" y="${py(p[1]) + 15}">${z.fga} FGA</text>`; }).join("");
  } else if (mode === "shots") {
    overlay = shots.map(([x, y, made, dist, period, xfg]) => {
      const tip = esc(`<b>${made ? "Made" : "Missed"}</b>${dist} ft · Q${period}<br>Model xFG ${(xfg * 100).toFixed(0)}%`);
      return made ? `<circle cx="${px(x)}" cy="${py(y)}" r="4.2" fill="var(--pos)" fill-opacity=".8" stroke="var(--court)" stroke-width="1" data-tip="${tip}"/>`
        : `<g data-tip="${tip}"><path d="M${px(x) - 3.4} ${py(y) - 3.4}l6.8 6.8m0-6.8l-6.8 6.8" stroke="var(--neg)" stroke-width="1.7" stroke-opacity=".7" stroke-linecap="round"/></g>`;
    }).join("");
  }
  return raw(`<div class="court-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Half-court shot chart"><rect class="court-bg" width="${W}" height="${H}" rx="6"/>${layers}${lines()}${overlay}</svg></div>`);
}

/** Live-game shot map: both teams on one half court, coloured by team, sized by model xFG. */
export function gameShotMap(shots, teams) {
  const dots = shots.map((s) => {
    const col = teams[s.team_id]?.primary || "var(--accent)", r = 3 + s.quality * 4;
    const tip = esc(`<b>${s.player || "Shot"}</b>${s.made ? "Made" : "Missed"} ${s.pts}PT · ${s.dist ?? "?"} ft<br>Q${s.period} ${s.clock}<br>Model xFG ${(s.quality * 100).toFixed(0)}%`);
    return s.made ? `<circle cx="${px(s.x)}" cy="${py(Math.abs(s.y) > 420 ? 840 - Math.abs(s.y) : s.y)}" r="${r}" fill="${col}" fill-opacity=".85" stroke="var(--court)" stroke-width="1" data-tip="${tip}"/>`
      : `<g data-tip="${tip}"><path d="M${px(s.x) - r} ${py(s.y) - r}l${2 * r} ${2 * r}m0 ${-2 * r}l${-2 * r} ${2 * r}" stroke="${col}" stroke-width="1.6" stroke-opacity=".55" stroke-linecap="round"/></g>`;
  }).join("");
  return raw(`<div class="court-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Shot map"><rect class="court-bg" width="${W}" height="${H}" rx="6"/>${lines()}${dots}</svg></div>`);
}
