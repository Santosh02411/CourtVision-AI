import { store } from "../core/store.js";
import { hexA } from "./format.js";

const registry = new Set();
export const colors = () => {
  const cs = getComputedStyle(document.documentElement), g = (n) => cs.getPropertyValue(n).trim();
  return { text: g("--chart-text"), grid: g("--grid"), accent: g("--accent"), pos: g("--pos"), neg: g("--neg"), info: g("--info"), warn: g("--warn"), home: g("--home"), away: g("--away"), surface: g("--surface"), surface3: g("--surface-3"), border: g("--border-strong"), fg: g("--text") };
};
export function baseOptions(c, extra = {}) {
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 650, easing: "easeOutCubic" },
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: false, labels: { color: c.text, usePointStyle: true, boxWidth: 8, font: { family: "Inter", size: 12 } } },
      tooltip: { backgroundColor: c.surface3, titleColor: c.fg, bodyColor: c.fg, borderColor: c.border, borderWidth: 1, padding: 10, cornerRadius: 9, displayColors: true, boxPadding: 4, titleFont: { family: "Inter", weight: "600" }, bodyFont: { family: "Inter" } } },
    scales: {}, ...extra,
  };
}
export const axis = (c, o = {}) => ({ grid: { color: c.grid, drawTicks: false }, border: { display: false }, ticks: { color: c.text, font: { family: "Inter", size: 11 }, padding: 6, ...(o.ticks || {}) }, ...o, ticks: { color: c.text, font: { family: "Inter", size: 11 }, padding: 6, ...(o.ticks || {}) } });

/** builder(colors) -> Chart.js config. Charts rebuild automatically on theme change. */
export function makeChart(canvas, builder, owner) {
  const entry = { canvas, builder, chart: null };
  entry.chart = new Chart(canvas, builder(colors()));
  registry.add(entry); owner?.push(entry);
  return entry;
}
export function disposeCharts(list) { list.forEach((e) => { try { e.chart.destroy(); } catch { /* already gone */ } registry.delete(e); }); list.length = 0; }
store.on("theme", () => {
  requestAnimationFrame(() => registry.forEach((e) => {
    if (!e.canvas.isConnected) { registry.delete(e); return; }
    try { e.chart.destroy(); e.chart = new Chart(e.canvas, e.builder(colors())); } catch { /* ignore */ }
  }));
});

export const plugins = {
  quarterLines: (labels = true) => ({
    id: "quarterLines",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales: { x } } = chart, c = colors(); ctx.save(); ctx.strokeStyle = c.grid; ctx.fillStyle = c.text; ctx.font = "600 10.5px Inter"; ctx.textAlign = "left";
      [720, 1440, 2160, 2880].forEach((t, i) => { const px = x.getPixelForValue(t); if (px < a.left || px > a.right) return; ctx.beginPath(); ctx.setLineDash([3, 4]); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke(); if (labels) { ctx.setLineDash([]); ctx.fillText(i < 3 ? `end Q${i + 1}` : "end Q4", px + 4, a.top + 11); } });
      ctx.restore();
    },
  }),
  pointLabels: {
    id: "pointLabels",
    afterDatasetsDraw(chart) {
      const { ctx } = chart, c = colors();
      chart.data.datasets.forEach((ds, di) => { if (!ds.pointLabels) return; const meta = chart.getDatasetMeta(di); ctx.save(); ctx.font = "650 10.5px Inter"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        meta.data.forEach((pt, i) => { const label = ds.pointLabels[i]; if (!label) return; ctx.fillStyle = ds.labelColors?.[i] || c.fg; ctx.globalAlpha = .95; ctx.fillText(label, pt.x, pt.y - 11); }); ctx.restore(); });
    },
  },
  midLine: (value, color) => ({ id: "midLine", afterDatasetsDraw(chart) { const { ctx, chartArea: a, scales: { y } } = chart, py = y.getPixelForValue(value); ctx.save(); ctx.strokeStyle = color; ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.moveTo(a.left, py); ctx.lineTo(a.right, py); ctx.stroke(); ctx.restore(); } }),
};
export const teamColor = (t) => t?.primary || colors().accent;
export { hexA };
