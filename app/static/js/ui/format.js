export const fmt = {
  num(v, d = 1) { return v == null || Number.isNaN(+v) ? "—" : (+v).toFixed(d); },
  int(v) { return v == null || Number.isNaN(+v) ? "—" : Math.round(+v).toLocaleString("en-US"); },
  pct(v, d = 1) { return v == null || Number.isNaN(+v) ? "—" : `${(+v).toFixed(d)}%`; },
  prob(p, d = 0) { return p == null ? "—" : `${(p * 100).toFixed(d)}%`; },
  signed(v, d = 1) { return v == null || Number.isNaN(+v) ? "—" : `${+v > 0 ? "+" : ""}${(+v).toFixed(d)}`; },
  date(iso, opts = { weekday: "short", month: "short", day: "numeric" }) {
    if (!iso) return "—"; const d = new Date(`${iso.slice(0, 10)}T12:00:00`); return d.toLocaleDateString("en-US", opts);
  },
  time(utc) { if (!utc) return ""; const d = new Date(utc); return Number.isNaN(+d) ? "" : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); },
  ago(sec) { if (sec == null) return ""; if (sec < 5) return "just now"; if (sec < 90) return `${Math.round(sec)}s ago`; if (sec < 5400) return `${Math.round(sec / 60)} min ago`; if (sec < 172800) return `${Math.round(sec / 3600)} h ago`; return `${Math.round(sec / 86400)} d ago`; },
  clock(c) { if (!c) return ""; const m = /PT(\d+)M([\d.]+)S/.exec(c); return m ? `${+m[1]}:${String(Math.floor(+m[2])).padStart(2, "0")}` : c; },
  ord(n) { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); },
  isoDate(d) { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); },
  addDays(iso, n) { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + n); return fmt.isoDate(d); },
};
export const hexA = (hex, a) => { const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(hex || ""); return m ? `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})` : hex; };

const rgb = (h) => { const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(h || ""); return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : null; };
const dist = (a, b) => { const x = rgb(a), y = rgb(b); return x && y ? Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) : 999; };
/** Team colours for a matchup; swaps the away colour when the two franchises' colours are too close to tell apart. */
export function pairColors(home, away) {
  const hc = home?.primary || "#5b9dff";
  let ac = away?.primary || "#ff7a1a";
  if (dist(hc, ac) < 110) { ac = away?.secondary && dist(hc, away.secondary) >= 110 ? away.secondary : dist(hc, "#ff7a1a") >= 110 ? "#ff7a1a" : "#f5b73b"; }
  return [hc, ac];
}
